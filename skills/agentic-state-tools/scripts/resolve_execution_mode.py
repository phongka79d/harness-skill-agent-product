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


VALID_REQUESTED_MODES = {
    "SYNC",
    "SYNC_WRITE",
    "AUTO",
    "PARALLEL_READ_ONLY",
    "ASYNC_PREFERRED",
    "ASYNC_REQUIRED",
    "ASYNC_ISOLATED_WRITE",
}
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
        raise ValueError("execution policy requested_mode must be SYNC_WRITE, AUTO, PARALLEL_READ_ONLY, or ASYNC_ISOLATED_WRITE")
    return normalized


def _legacy_mode_output(task: dict[str, Any], requested: str, resolved: str) -> str:
    """Keep old aliases readable while exposing the explicit HSP-502 modes."""

    raw_policy = task.get("execution_policy")
    raw = raw_policy.get("requested_mode") if isinstance(raw_policy, dict) else task.get("execution_mode", "AUTO")
    raw = str(raw).upper()
    if raw in {"SYNC", "AUTO"} and resolved == "SYNC_WRITE":
        return "SYNC"
    if raw in {"ASYNC", "ASYNC_PREFERRED", "ASYNC_REQUIRED", "AUTO"} and resolved == "ASYNC_ISOLATED_WRITE":
        return "ASYNC"
    return resolved


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


def _parallel_read_only_active_count(active_tasks: list[dict[str, Any]], queue: dict[str, Any]) -> int:
    records: list[dict[str, Any]] = [item for item in active_tasks if isinstance(item, dict)]
    queue_active = queue.get("active_tasks")
    if isinstance(queue_active, list):
        records.extend(item for item in queue_active if isinstance(item, dict))
    else:
        queue_tasks = queue.get("tasks")
        if isinstance(queue_tasks, list):
            active_statuses = {"RUNNING", "DISPATCHED", "QUEUED_ASYNC", "QUEUED_SYNC", "ASYNC"}
            records.extend(
                item
                for item in queue_tasks
                if isinstance(item, dict)
                and str(item.get("status", item.get("queue_state", ""))).upper() in active_statuses
            )
    identities: set[str] = set()
    anonymous = 0
    for item in records:
        policy = item.get("execution_policy")
        requested = policy.get("requested_mode") if isinstance(policy, dict) else item.get("execution_mode")
        if str(requested or "").upper() != "PARALLEL_READ_ONLY":
            continue
        task_id = item.get("task_id")
        if isinstance(task_id, str) and task_id:
            identities.add(task_id)
        else:
            anonymous += 1
    return len(identities) + anonymous


def _parallel_read_only_reason(
    task: dict[str, Any],
    *,
    config: dict[str, Any],
    active_tasks: list[dict[str, Any]],
    queue: dict[str, Any],
) -> str | None:
    policy = config.get("parallel_read_only")
    if not isinstance(policy, dict) or policy.get("capability_enabled") is not True:
        return "PARALLEL_READ_ONLY_DISABLED"
    status = str(task.get("status", "")).upper()
    if status in RECOVERY_STATES:
        return f"RECOVERY_STATE_{status}"
    if status in TERMINAL_STATES:
        return f"TASK_STATE_{status}"
    if task.get("dependencies_pending") is True:
        return "DEPENDENCY_NOT_CLEAR"
    dependencies = task.get("depends_on", [])
    if not isinstance(dependencies, list) or dependencies:
        return "PARALLEL_DEPENDENCY_NOT_INDEPENDENT"

    question = task.get("exploration_question", task.get("investigation_question"))
    if not isinstance(question, str) or not question.strip():
        return "EXPLORATION_QUESTION_MISSING"
    if policy.get("require_independent_questions") is True and task.get("independent_question") is not True:
        return "INDEPENDENT_QUESTION_UNCONFIRMED"
    normalized_question = question.strip().casefold()
    for active in active_tasks:
        if not isinstance(active, dict) or active.get("task_id") == task.get("task_id"):
            continue
        active_policy = active.get("execution_policy")
        active_requested = active_policy.get("requested_mode") if isinstance(active_policy, dict) else active.get("execution_mode")
        if str(active_requested or "").upper() != "PARALLEL_READ_ONLY":
            continue
        active_question = active.get("exploration_question", active.get("investigation_question"))
        if isinstance(active_question, str) and active_question.strip().casefold() == normalized_question:
            return "EXPLORATION_QUESTION_NOT_INDEPENDENT"

    write_scope = task.get("write_scope")
    if policy.get("require_read_only_scope") is True and (not isinstance(write_scope, list) or write_scope):
        return "READ_ONLY_SCOPE_REQUIRED"
    if task.get("writes") is True or task.get("can_write") is True:
        return "READ_ONLY_PERMISSION_REQUIRED"
    read_scope = task.get("read_scope", task.get("files_to_read", []))
    if not isinstance(read_scope, list) or not read_scope:
        return "READ_SCOPE_MISSING"

    if policy.get("require_context_capacity") is True:
        capacity = task.get("context_capacity_available", task.get("context_available"))
        if capacity is not True:
            return "CONTEXT_CAPACITY_UNAVAILABLE"
        token_capacity = task.get("token_capacity_available", task.get("token_budget_available"))
        if token_capacity is not True:
            return "TOKEN_CAPACITY_UNAVAILABLE"
    if policy.get("require_deterministic_reconciliation") is True:
        deterministic = task.get("deterministic_reconciliation", task.get("reconcile_deterministically"))
        strategy = task.get("reconciliation_strategy", task.get("reconciliation_plan"))
        if deterministic is not True or not isinstance(strategy, str) or not strategy.strip():
            return "RECONCILIATION_NOT_DETERMINISTIC"
        contract = task.get("reconciliation_contract")
        if not isinstance(contract, dict):
            return "RECONCILIATION_CONTRACT_MISSING"
        if contract.get("order") != ["task_id", "path", "symbol"]:
            return "RECONCILIATION_ORDER_UNPINNED"
        if contract.get("preserve_source_locations") is not True:
            return "SOURCE_LOCATIONS_UNPRESERVED"
        if contract.get("block_on_conflict") is not True or contract.get("block_on_material_unknown") is not True:
            return "RECONCILIATION_BLOCK_POLICY_UNSAFE"

    if policy.get("require_read_only_scope") is True and task.get("write_forbidden") is not True:
        return "WRITE_PROHIBITION_UNCONFIRMED"

    planning = config.get("planning", {})
    agents = config.get("agents", {})
    owner = task.get("owner")
    aliases = planning.get("owner_aliases", {}) if isinstance(planning, dict) else {}
    owner_id = aliases.get(owner, owner) if isinstance(aliases, dict) else owner
    agent = agents.get(owner_id) if isinstance(agents, dict) else None
    capabilities = agent.get("capabilities", []) if isinstance(agent, dict) else []
    if not isinstance(agent, dict) or "repository_reading" not in capabilities or "evidence_gathering" not in capabilities:
        return "EXPLORER_CAPABILITY_MISSING"

    if _parallel_read_only_active_count(active_tasks, queue) >= int(policy.get("max_parallel_tasks", 1)):
        return "PARALLEL_READ_ONLY_CAPACITY_EXCEEDED"
    if isinstance(queue.get("available_slots"), int) and queue["available_slots"] < 1:
        return "QUEUE_SLOT_UNAVAILABLE"
    return None


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
    default_resolved = "SYNC_WRITE" if requested not in {"SYNC_WRITE", "SYNC", "AUTO"} else "SYNC"
    if requested == "SYNC_WRITE":
        default_resolved = _legacy_mode_output(task, requested, "SYNC_WRITE")
    base = {
        "requested_mode": requested,
        "resolved_mode": default_resolved,
        "resolution_reason": "REQUESTED_SYNC_WRITE" if requested == "SYNC_WRITE" else ("REQUESTED_SYNC" if requested == "SYNC" else ""),
        "resolved_by": "resolve_execution_mode",
        "resolved_at": resolved_at,
        "isolation_proof": isolation_proof if isinstance(isolation_proof, dict) else None,
    }
    if requested in {"SYNC", "SYNC_WRITE"}:
        return base
    if requested == "PARALLEL_READ_ONLY":
        reason = _parallel_read_only_reason(
            task,
            config=config,
            active_tasks=active_tasks,
            queue=queue,
        )
        if reason is None:
            base["resolved_mode"] = "PARALLEL_READ_ONLY"
            base["resolution_reason"] = "PARALLEL_READ_ONLY_ELIGIBLE"
        else:
            base["resolved_mode"] = "BLOCKED"
            base["resolution_reason"] = reason
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
        base["resolved_mode"] = _legacy_mode_output(task, requested, "ASYNC_ISOLATED_WRITE")
        base["resolution_reason"] = "ASYNC_ELIGIBLE"
        return base
    if requested == "ASYNC_REQUIRED":
        base["resolved_mode"] = "BLOCKED"
        base["resolution_reason"] = reason
        return base
    if requested == "ASYNC_ISOLATED_WRITE":
        base["resolved_mode"] = "BLOCKED"
        base["resolution_reason"] = reason
        return base
    base["resolved_mode"] = _legacy_mode_output(task, requested, "SYNC_WRITE")
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
        legacy_policy = legacy_task.get("execution_policy")
        requested_value = legacy_policy.get("requested_mode") if isinstance(legacy_policy, dict) else legacy_task.get("execution_mode", "auto")
        requested = str(requested_value).lower()
        if requested in {"sync_write", "parallel_read_only", "async_isolated_write"}:
            policy = resolve_execution_policy(
                legacy_task,
                config=selected_config,
                active_tasks=[],
                queue={},
                lease=None,
                isolation_proof=isolation_proof,
                now=None,
            )
            return policy["resolved_mode"]
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
