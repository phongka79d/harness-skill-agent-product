"""Resolve a task's safe execution policy without mutating runtime state."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_utils import read_object
from worktree_manager import validate_isolation_proof

CONFIG_SKILL = Path(__file__).resolve().parents[2] / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))

from load_config import load_config  # noqa: E402


VALID_REQUESTED_MODES = {"SYNC", "AUTO", "ASYNC_PREFERRED", "ASYNC_REQUIRED"}
RECOVERY_STATES = {"BLOCKED", "ESCALATED", "RECOVERY_PENDING", "STALE", "RESUMING", "PAUSED", "ABORTED_UNSAFE"}
TERMINAL_STATES = {"ACCEPTED", "CANCELLED", "SUPERSEDED", "ARCHIVED", "COMPLETED"}
ASYNC_RISK_FLAGS = {"destructive_operation", "deployment", "schema_migration", "infrastructure", "shared_state", "concurrency"}
SYNC_OPERATION_TYPES = {"destructive", "destructive_operation", "deployment", "migration", "schema_migration", "infrastructure", "shared_configuration"}


def _timestamp(now: datetime | None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _requested_mode(task: dict[str, Any]) -> str:
    policy = task.get("execution_policy")
    value = policy.get("requested_mode") if isinstance(policy, dict) else task.get("requested_mode")
    if value is None:
        value = task.get("execution_mode", "AUTO")
    normalized = str(value).upper()
    legacy = {"ASYNC": "ASYNC_PREFERRED", "SYNC": "SYNC", "AUTO": "AUTO"}
    normalized = legacy.get(normalized, normalized)
    if normalized not in VALID_REQUESTED_MODES:
        raise ValueError("execution policy requested_mode must be SYNC, AUTO, ASYNC_PREFERRED, or ASYNC_REQUIRED")
    return normalized


def _active_task_count(active_tasks: list[dict[str, Any]], queue: dict[str, Any]) -> int:
    if isinstance(queue.get("active_tasks"), list):
        return len(queue["active_tasks"])
    if isinstance(queue.get("tasks"), list):
        active = {"RUNNING", "DISPATCHED", "QUEUED_ASYNC", "QUEUED_SYNC", "ASYNC"}
        return sum(1 for item in queue["tasks"] if isinstance(item, dict) and str(item.get("status", item.get("queue_state", ""))).upper() in active)
    return len(active_tasks)


def _overlaps(left: list[Any], right: list[Any]) -> bool:
    def normalize(value: Any) -> str:
        return str(value).replace("\\", "/").strip().rstrip("/") or "."

    for left_scope in left:
        left_value = normalize(left_scope)
        for right_scope in right:
            right_value = normalize(right_scope)
            if left_value == right_value or left_value.startswith(right_value + "/") or right_value.startswith(left_value + "/"):
                return True
    return False


def _eligibility_reason(
    task: dict[str, Any],
    *,
    config: dict[str, Any],
    active_tasks: list[dict[str, Any]],
    queue: dict[str, Any],
    lease: dict[str, Any] | None,
    isolation_proof: Any,
    now: datetime | None,
) -> str | None:
    policy = config.get("async_execution")
    if not isinstance(policy, dict) or policy.get("capability_enabled") is not True:
        return "ASYNC_CAPABILITY_DISABLED"
    if policy.get("allow_task_opt_in") is not True:
        return "ASYNC_TASK_OPT_IN_DISABLED"
    if policy.get("require_isolated_worktree") is True and not validate_isolation_proof(task, isolation_proof):
        return "ISOLATION_PROOF_MISSING"
    status = str(task.get("status", "")).upper()
    if status in RECOVERY_STATES:
        return f"RECOVERY_STATE_{status}"
    if status in TERMINAL_STATES:
        return f"TASK_STATE_{status}"
    if task.get("scope_conflict") is True:
        return "SCOPE_CONFLICT"
    if task.get("dependencies_pending") is True:
        return "DEPENDENCY_NOT_CLEAR"
    dependencies = task.get("depends_on", [])
    accepted = set(task.get("accepted_dependency_ids", []))
    if isinstance(dependencies, list) and dependencies and not set(dependencies).issubset(accepted):
        active_statuses = {str(item.get("task_id")): str(item.get("status", "")).upper() for item in active_tasks if isinstance(item, dict)}
        if any(active_statuses.get(str(dependency)) != "ACCEPTED" for dependency in dependencies):
            return "DEPENDENCY_NOT_CLEAR"
    planning = config.get("planning", {})
    agents = config.get("agents", {})
    owner = task.get("owner")
    aliases = planning.get("owner_aliases", {}) if isinstance(planning, dict) else {}
    owner_id = aliases.get(owner, owner) if isinstance(aliases, dict) else owner
    agent = agents.get(owner_id) if isinstance(agents, dict) else None
    capabilities = agent.get("capabilities", []) if isinstance(agent, dict) else []
    task_capabilities = planning.get("task_type_capabilities", {}) if isinstance(planning, dict) else {}
    required_capability = task_capabilities.get(str(task.get("task_type", "")).lower()) if isinstance(task_capabilities, dict) else None
    if not isinstance(agent, dict) or not isinstance(owner_id, str) or not required_capability or required_capability not in capabilities:
        return "OWNER_CAPABILITY_MISSING"
    risk_flags = task.get("risk_flags", {})
    if isinstance(risk_flags, dict) and any(risk_flags.get(flag) is True for flag in ASYNC_RISK_FLAGS):
        return "OPERATION_REQUIRES_SYNC"
    operation_type = str(task.get("operation_type") or task.get("operation_kind") or task.get("task_type") or "").lower()
    if operation_type in SYNC_OPERATION_TYPES:
        return "OPERATION_REQUIRES_SYNC"
    if policy.get("require_disjoint_write_scope") is True:
        task_scope = task.get("write_scope", []) if isinstance(task.get("write_scope", []), list) else []
        for active in active_tasks:
            if isinstance(active, dict) and active.get("task_id") != task.get("task_id") and _overlaps(task_scope, active.get("write_scope", [])):
                return "SCOPE_CONFLICT"
    if _active_task_count(active_tasks, queue) >= int(policy.get("max_parallel_tasks", 1)):
        return "ASYNC_CAPACITY_EXCEEDED"
    if isinstance(queue.get("available_slots"), int) and queue["available_slots"] < 1:
        return "QUEUE_SLOT_UNAVAILABLE"
    if policy.get("require_separate_branch") is True:
        branch = isolation_proof.get("branch_name") if isinstance(isolation_proof, dict) else None
        if not isinstance(branch, str) or not branch.strip() or branch in {"main", "master"}:
            return "SEPARATE_BRANCH_MISSING"
    if policy.get("require_pinned_plan_revision") is True:
        plan_revision = task.get("plan_revision")
        proof_revision = isolation_proof.get("plan_revision") if isinstance(isolation_proof, dict) else None
        if not isinstance(plan_revision, int) or plan_revision < 1 or proof_revision != plan_revision:
            return "PLAN_REVISION_UNPINNED"
    if policy.get("require_pinned_input_hashes") is True:
        hashes = task.get("input_artifact_hashes")
        if not isinstance(hashes, dict) or not hashes or any(not isinstance(value, str) or not value for value in hashes.values()):
            return "INPUT_HASHES_UNPINNED"
    if lease is None or not isinstance(lease, dict) or not lease.get("expires_at"):
        return "LEASE_MISSING"
    try:
        expires_at = datetime.fromisoformat(str(lease["expires_at"]).replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if expires_at <= current.astimezone(timezone.utc):
            return "LEASE_EXPIRED"
    except (TypeError, ValueError):
        return "LEASE_INVALID"
    if task.get("merge_independent") is not True:
        return "MERGE_NOT_INDEPENDENT"
    return None


def resolve_execution_policy(
    task: dict[str, Any],
    *,
    config: dict[str, Any],
    active_tasks: list[dict[str, Any]],
    queue: dict[str, Any],
    lease: dict[str, Any] | None,
    isolation_proof: Any,
    now: datetime | None,
) -> dict[str, Any]:
    requested = _requested_mode(task)
    resolved_at = _timestamp(now)
    base = {
        "requested_mode": requested,
        "resolved_mode": "SYNC",
        "resolution_reason": "REQUESTED_SYNC" if requested == "SYNC" else "",
        "resolved_by": "resolve_execution_mode",
        "resolved_at": resolved_at,
        "isolation_proof": isolation_proof if isinstance(isolation_proof, dict) else None,
    }
    if requested == "SYNC":
        return base
    reason = _eligibility_reason(
        task,
        config=config,
        active_tasks=active_tasks,
        queue=queue,
        lease=lease,
        isolation_proof=isolation_proof,
        now=now,
    )
    if reason is None:
        base["resolved_mode"] = "ASYNC"
        base["resolution_reason"] = "ASYNC_ELIGIBLE"
        return base
    if requested == "ASYNC_REQUIRED":
        base["resolved_mode"] = "BLOCKED"
        base["resolution_reason"] = reason
        return base
    base["resolution_reason"] = f"FALLBACK_TO_SYNC:{reason}"
    return base


def resolve_execution_mode(
    task: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    active_tasks: list[dict[str, Any]] | None = None,
    queue: dict[str, Any] | None = None,
    lease: dict[str, Any] | None = None,
    isolation_proof: Any = None,
    now: datetime | None = None,
    scope_conflict: bool = False,
    dependencies_pending: bool = False,
) -> dict[str, Any] | str:
    """Return a complete policy for the new API or a legacy mode string for old callers."""
    legacy = config is None and active_tasks is None and queue is None and lease is None and now is None
    selected_config = config or load_config()
    if legacy:
        legacy_task = dict(task)
        if scope_conflict:
            legacy_task["scope_conflict"] = True
        if dependencies_pending:
            legacy_task["dependencies_pending"] = True
        old_execution = selected_config.get("execution", {})
        requested = str(legacy_task.get("execution_mode", "auto")).lower()
        if requested == "auto":
            requested = str(old_execution.get("default_mode", "sync")).lower()
            if requested == "auto":
                requested = "async" if old_execution.get("async_execution_enabled") is True else "sync"
        if requested == "sync" or legacy_task.get("scope_conflict") is True or legacy_task.get("dependencies_pending") is True or str(legacy_task.get("status", "")).upper() in RECOVERY_STATES:
            return "SYNC"
        if not (old_execution.get("async_execution_enabled") is True and old_execution.get("async_requires_isolated_worktree") is True and selected_config.get("version_control", {}).get("isolated_worktrees") is True):
            return "BLOCKED" if requested == "async" else "SYNC"
        return "ASYNC" if validate_isolation_proof(legacy_task, isolation_proof) else "BLOCKED"
    return resolve_execution_policy(
        task,
        config=selected_config,
        active_tasks=active_tasks or [],
        queue=queue or {},
        lease=lease,
        isolation_proof=isolation_proof,
        now=now,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--scope-conflict", action="store_true")
    parser.add_argument("--dependencies-pending", action="store_true")
    parser.add_argument("--isolation-proof")
    args = parser.parse_args()
    try:
        task = read_object(args.input)
        if not isinstance(task, dict):
            raise ValueError("task input must be an object")
        task = dict(task)
        if args.scope_conflict:
            task["scope_conflict"] = True
        if args.dependencies_pending:
            task["dependencies_pending"] = True
        proof = read_object(args.isolation_proof) if args.isolation_proof else None
        result = resolve_execution_mode(
            task,
            config=load_config(),
            active_tasks=[],
            queue={},
            lease=None,
            isolation_proof=proof,
            now=datetime.now(timezone.utc),
        )
        output = {"task_id": task.get("task_id"), "execution_mode": result["resolved_mode"], "execution_policy": result}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"EXECUTION_MODE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
