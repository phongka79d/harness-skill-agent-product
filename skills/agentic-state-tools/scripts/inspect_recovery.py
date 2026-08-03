"""Classify a task's recovery safety from state and checkpoint evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from append_event import append_event
from capture_workspace import capture_workspace
from operation_ledger import read_operation_ledger
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    parse_timestamp,
    read_object,
    runtime_lock,
    inspect_terminal_cleanup,
    utc_now,
    validate_identifier,
    write_json_atomic,
)
from task_state_contract import validate_execution_identity
from write_artifact import write_validated


OPERATION_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/operation.schema.json"


def _policy(resume: str, *, requires_lease: bool, inspect_git: bool, rollback: bool, terminal: bool) -> dict[str, object]:
    return {
        "resume": resume,
        "requires_lease": requires_lease,
        "inspect_git": inspect_git,
        "rollback": rollback,
        "terminal": terminal,
        "unsupported": False,
    }


RECOVERY_POLICIES = {
    "PENDING": _policy("SAFE_TO_RESUME", requires_lease=False, inspect_git=False, rollback=False, terminal=False),
    "READY": _policy("SAFE_TO_RESUME", requires_lease=False, inspect_git=False, rollback=False, terminal=False),
    "QUEUED": _policy("SAFE_TO_RESUME", requires_lease=True, inspect_git=True, rollback=False, terminal=False),
    "QUEUED_ASYNC": _policy("SAFE_TO_RESUME", requires_lease=True, inspect_git=True, rollback=False, terminal=False),
    "QUEUED_SYNC": _policy("SAFE_TO_RESUME", requires_lease=True, inspect_git=True, rollback=False, terminal=False),
    "WAITING": _policy("SAFE_TO_RESUME", requires_lease=False, inspect_git=False, rollback=False, terminal=False),
    "WAITING_DEPENDENCY": _policy("SAFE_TO_RESUME", requires_lease=False, inspect_git=False, rollback=False, terminal=False),
    "WAITING_RESOURCE_LOCK": _policy("SAFE_TO_RESUME", requires_lease=False, inspect_git=True, rollback=False, terminal=False),
    "RUNNING": _policy("NEEDS_RECONCILIATION", requires_lease=True, inspect_git=True, rollback=True, terminal=False),
    "CHECKPOINTED": _policy("NEEDS_RECONCILIATION", requires_lease=True, inspect_git=True, rollback=True, terminal=False),
    "BLOCKED": _policy("NEEDS_RECONCILIATION", requires_lease=False, inspect_git=True, rollback=False, terminal=False),
    "STALE": _policy("NEEDS_RECONCILIATION", requires_lease=True, inspect_git=True, rollback=True, terminal=False),
    "RECOVERY_PENDING": _policy("NEEDS_RECONCILIATION", requires_lease=True, inspect_git=True, rollback=True, terminal=False),
    "RESUMING": _policy("NEEDS_RECONCILIATION", requires_lease=True, inspect_git=True, rollback=True, terminal=False),
    "REVIEWING": _policy("NEEDS_RECONCILIATION", requires_lease=False, inspect_git=True, rollback=False, terminal=False),
    "REPAIR_REQUIRED": _policy("NEEDS_RECONCILIATION", requires_lease=False, inspect_git=True, rollback=False, terminal=False),
    "COMPLETED": _policy("SAFE_TO_RESUME", requires_lease=False, inspect_git=True, rollback=False, terminal=False),
    "ACCEPTED": _policy("TERMINAL", requires_lease=False, inspect_git=False, rollback=False, terminal=True),
    "PAUSED": _policy("NEEDS_RECONCILIATION", requires_lease=False, inspect_git=True, rollback=False, terminal=False),
    "DEFERRED": _policy("NEEDS_RECONCILIATION", requires_lease=False, inspect_git=False, rollback=False, terminal=False),
    "ESCALATED": _policy("NEEDS_RECONCILIATION", requires_lease=False, inspect_git=True, rollback=True, terminal=False),
    "CANCELLED": _policy("TERMINAL", requires_lease=False, inspect_git=True, rollback=False, terminal=True),
    "SUPERSEDED": _policy("TERMINAL", requires_lease=False, inspect_git=True, rollback=False, terminal=True),
    "ARCHIVED": _policy("TERMINAL", requires_lease=False, inspect_git=False, rollback=False, terminal=True),
    "ABORTED_UNSAFE": _policy("TERMINAL", requires_lease=True, inspect_git=True, rollback=True, terminal=True),
}


def recovery_policy(status: str) -> dict[str, object]:
    normalized = str(status).upper()
    policy = RECOVERY_POLICIES.get(normalized)
    if policy is None:
        return {
            "resume": "UNSAFE_TO_RESUME",
            "requires_lease": False,
            "inspect_git": True,
            "rollback": True,
            "terminal": False,
            "unsupported": True,
        }
    return dict(policy)


def inspect_workspace(root: Path, checkpoint: dict | None) -> dict:
    snapshot = capture_workspace(
        root,
        expected_files=[value for value in (checkpoint or {}).get("files_modified", []) if isinstance(value, str)],
        expected_base=(checkpoint or {}).get("base_commit"),
    )
    snapshot["status"] = snapshot["workspace_status"]
    return snapshot


def validate_checkpoint_binding(task: dict, checkpoint: dict) -> list[str]:
    """Compare optional checkpoint identity fields with the current task snapshot."""

    errors: list[str] = []
    if checkpoint.get("task_id") != task.get("task_id"):
        errors.append("checkpoint task_id does not match task state")
    task_revision = checkpoint.get("task_revision")
    if task_revision is not None and task_revision != task.get("revision"):
        errors.append("checkpoint task revision does not match task state")
    checkpoint_attempt = checkpoint.get("attempt_id")
    task_attempt = task.get("attempt_id")
    if checkpoint_attempt is not None and task_attempt is not None and checkpoint_attempt != task_attempt:
        errors.append("checkpoint attempt_id does not match task state")
    checkpoint_hashes = checkpoint.get("input_artifact_hashes")
    task_hashes = task.get("input_artifact_hashes")
    if checkpoint_hashes is not None:
        if not isinstance(checkpoint_hashes, dict) or not isinstance(task_hashes, dict):
            errors.append("checkpoint input artifact hashes cannot be verified")
        elif checkpoint_hashes != task_hashes:
            errors.append("checkpoint input artifact hashes do not match task state")
    return errors


def validate_lease_binding(task: dict, lease: dict) -> list[str]:
    """Ensure a lease belongs to the current task revision and execution attempt."""

    errors: list[str] = []
    if lease.get("task_id") != task.get("task_id"):
        errors.append("lease task_id does not match task state")
    if "revision" in task and lease.get("task_revision") is not None and lease.get("task_revision") != task.get("revision"):
        errors.append("lease task revision does not match task state")
    for field in ("run_id", "attempt_id", "dispatch_id"):
        expected = task.get(field)
        actual = lease.get(field)
        if expected is not None and actual is not None and actual != expected:
            errors.append(f"lease {field} does not match task state")
    if not isinstance(lease.get("owner_identity"), str) or not lease["owner_identity"].strip():
        errors.append("lease owner_identity is missing")
    return errors


def reconcile_runtime_artifacts(root: Path, task_id: str, task_status: str) -> list[str]:
    """Compare task state with available durable snapshot, queue, and graph evidence."""

    reasons: list[str] = []
    runtime_root = root / "runtime"
    state_path = runtime_root / "state.json"
    if state_path.is_file():
        try:
            snapshot = read_object(state_path)
            snapshot_status = snapshot.get("task_statuses", {}).get(task_id) if isinstance(snapshot.get("task_statuses"), dict) else None
            if snapshot_status is not None and str(snapshot_status).upper() != task_status:
                reasons.append(f"state snapshot status mismatch: {snapshot_status} != {task_status}")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"runtime state snapshot is unreadable: {exc}")

    queue_path = runtime_root / "queue.json"
    queue_entry = None
    queue = None
    if queue_path.is_file():
        try:
            queue = read_object(queue_path)
            task_entries = queue.get("tasks", [])
            if isinstance(task_entries, list):
                queue_entry = next((item for item in task_entries if isinstance(item, dict) and item.get("task_id") == task_id), None)
            else:
                reasons.append("queue tasks collection is malformed")
            if queue_entry is not None:
                queue_state = str(queue_entry.get("queue_state", "")).upper()
                if task_status in {"RUNNING", "QUEUED", "QUEUED_ASYNC", "QUEUED_SYNC"} and queue_state not in {"DISPATCHED", "RUNNING", "QUEUED"}:
                    reasons.append(f"queue state does not match active task: {queue_state}")
            task_path = root / "work" / task_id / "task-state.json"
            if task_path.is_file() and isinstance(queue, dict):
                try:
                    validate_execution_identity(read_object(task_path), None, queue)
                except ValueError as exc:
                    reasons.append(f"queue execution identity mismatch: {exc}")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"queue is unreadable: {exc}")

    graph_path = runtime_root / "graph.json"
    if queue_entry is not None and graph_path.is_file():
        try:
            graph = read_object(graph_path)
            if task_id not in graph.get("nodes", []):
                reasons.append("execution graph is missing the queued task node")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"execution graph is unreadable: {exc}")
    return sorted(set(reasons))

def persist_reconciliation(root: Path, result: dict) -> dict:
    task_id = result["task_id"]
    created_at = utc_now()
    record = {
        "schema_version": 1,
        "reconciliation_id": "pending",
        "task_id": task_id,
        "classification": result["classification"],
        "status": result.get("status", ""),
        "next_action": result.get("next_action"),
        "reasons": list(result.get("reasons", [])),
        "workspace": result.get("workspace", {}),
        "created_at": created_at,
    }
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    evidence_hash = hashlib.sha256(canonical).hexdigest()
    record["reconciliation_id"] = f"REC-{task_id}-{evidence_hash[:12]}"
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    record["evidence_hash"] = hashlib.sha256(canonical).hexdigest()
    write_validated(str(root.parent), f"recovery/reconciliation-{task_id}.json", record, Path(__file__).resolve().parents[1] / "schemas/reconciliation.schema.json")
    result["reconciliation_id"] = record["reconciliation_id"]
    result["reconciliation_hash"] = record["evidence_hash"]
    return result


def inspect_task(root: Path, task_id: str) -> dict:
    validate_identifier(task_id, "task_id")
    task_path = root / "work" / task_id / "task-state.json"
    if not task_path.is_file():
        return {"task_id": task_id, "classification": "UNSAFE_TO_RESUME", "reasons": ["task state is missing"]}
    try:
        task = read_object(task_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"task_id": task_id, "classification": "UNSAFE_TO_RESUME", "reasons": [f"task state is unreadable: {exc}"]}

    status = str(task.get("status", "")).upper()
    policy = recovery_policy(status)
    if policy["unsupported"]:
        return {
            "task_id": task_id,
            "classification": "UNSAFE_TO_RESUME",
            "status": status,
            "next_action": task.get("next_action"),
            "inspected_at": utc_now(),
            "reasons": [f"unsupported task status {status or '<missing>'}"],
        }
    checkpoint_path = task_path.parent / "checkpoint.json"
    workspace = {"status": "NOT_INSPECTED", "mismatch": False, "reasons": ["workspace inspection is not required for this status"]}
    try:
        operations = read_operation_ledger(task_path.parent / "operations.jsonl", task_id, OPERATION_SCHEMA)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "task_id": task_id,
            "classification": "UNSAFE_TO_RESUME",
            "status": status,
            "next_action": task.get("next_action"),
            "inspected_at": utc_now(),
            "reasons": [f"operation ledger is unreadable: {exc}"],
        }
    unresolved_operations = [
        operation
        for operation in operations
        if operation["status"] in {"STARTED", "UNKNOWN"}
    ]
    operation_reasons = [
        f"operation {operation['operation_id']} has unresolved status {operation['status']}"
        for operation in unresolved_operations
    ]
    runtime_reasons = reconcile_runtime_artifacts(root, task_id, status)
    if runtime_reasons and not policy["terminal"]:
        return {
            "task_id": task_id,
            "classification": "NEEDS_RECONCILIATION",
            "status": status,
            "next_action": task.get("next_action"),
            "inspected_at": utc_now(),
            "workspace": inspect_workspace(root, None) if policy["inspect_git"] else workspace,
            "reasons": [*runtime_reasons, *operation_reasons],
        }

    if policy["terminal"]:
        cleanup = inspect_terminal_cleanup(root, task_id)
        terminal_reasons = [*runtime_reasons, *cleanup["reasons"]]
        if terminal_reasons:
            return {
                "task_id": task_id,
                "classification": "NEEDS_RECONCILIATION",
                "status": status,
                "next_action": "reconcile terminal cleanup",
                "inspected_at": utc_now(),
                "workspace": workspace,
                "reasons": terminal_reasons + operation_reasons,
            }
        return {
            "task_id": task_id,
            "classification": "SAFE_TO_RESUME",
            "status": status,
            "next_action": "none",
            "inspected_at": utc_now(),
            "workspace": workspace,
            "reasons": [f"status {status} is terminal; resume is not applicable", *operation_reasons],
        }

    if status == "REVIEWING":
        review_path = task_path.parent / "review.json"
        if not review_path.is_file():
            return {
                "task_id": task_id,
                "classification": "NEEDS_RECONCILIATION",
                "status": status,
                "next_action": task.get("next_action"),
                "inspected_at": utc_now(),
                "workspace": workspace,
                "reasons": ["reviewing task has no review artifact", *operation_reasons],
            }
        return {
            "task_id": task_id,
            "classification": "NEEDS_RECONCILIATION",
            "status": status,
            "next_action": task.get("next_action"),
            "inspected_at": utc_now(),
            "workspace": inspect_workspace(root, None),
            "reasons": ["review artifact exists but state transition is not reconciled", *operation_reasons],
        }

    if status in {"QUEUED_ASYNC", "QUEUED_SYNC"} and policy["requires_lease"]:
        lease_path = task_path.parent / "lease.json"
        if not lease_path.is_file():
            return {
                "task_id": task_id,
                "classification": "NEEDS_RECONCILIATION",
                "status": status,
                "next_action": task.get("next_action"),
                "inspected_at": utc_now(),
                "workspace": workspace,
                "reasons": ["dispatched queued task has no lease", *operation_reasons],
            }
        try:
            lease = read_object(lease_path)
            lease_errors = validate_lease_binding(task, lease)
            expiry = parse_timestamp(lease.get("expires_at"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "task_id": task_id,
                "classification": "UNSAFE_TO_RESUME",
                "status": status,
                "next_action": task.get("next_action"),
                "inspected_at": utc_now(),
                "workspace": workspace,
                "reasons": [f"queued task lease is unreadable: {exc}"],
            }
        if lease_errors or expiry <= datetime.now(timezone.utc):
            reasons = lease_errors or ["dispatched queued task lease has expired"]
            return {
                "task_id": task_id,
                "classification": "NEEDS_RECONCILIATION",
                "status": status,
                "next_action": task.get("next_action"),
                "inspected_at": utc_now(),
                "workspace": workspace,
                "reasons": [*reasons, *operation_reasons],
            }

    if status in {"REPAIR_REQUIRED", "BLOCKED", "PAUSED", "DEFERRED", "ESCALATED", "WAITING_DEPENDENCY", "WAITING_RESOURCE_LOCK", "QUEUED_ASYNC", "QUEUED_SYNC"}:
        classification = "NEEDS_RECONCILIATION" if policy["resume"] != "SAFE_TO_RESUME" else "SAFE_TO_RESUME"
        return {
            "task_id": task_id,
            "classification": classification,
            "status": status,
            "next_action": task.get("next_action"),
            "inspected_at": utc_now(),
            "workspace": inspect_workspace(root, None) if policy["inspect_git"] else workspace,
            "reasons": [f"status {status} has explicit recovery policy", *operation_reasons],
        }

    if status in {"PENDING", "READY", "QUEUED", "WAITING", "COMPLETED", "ACCEPTED"}:
        classification = "NEEDS_RECONCILIATION" if operation_reasons else "SAFE_TO_RESUME"
        reasons = operation_reasons or [f"status {status} has no active side effect"]
    elif status in {"RUNNING", "CHECKPOINTED", "STALE", "RECOVERY_PENDING", "RESUMING"}:
        lease_path = task_path.parent / "lease.json"
        if not lease_path.is_file():
            return {
                "task_id": task_id,
                "classification": "NEEDS_RECONCILIATION",
                "status": status,
                "next_action": task.get("next_action"),
                "inspected_at": utc_now(),
                "workspace": workspace,
                "reasons": ["active task has no lease", *operation_reasons],
            }
        try:
            lease = read_object(lease_path)
            expires_at = parse_timestamp(lease.get("expires_at"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "task_id": task_id,
                "classification": "UNSAFE_TO_RESUME",
                "status": status,
                "next_action": task.get("next_action"),
                "inspected_at": utc_now(),
                "reasons": [f"lease is unreadable: {exc}"],
            }
        lease_binding_errors = validate_lease_binding(task, lease)
        if lease_binding_errors:
            return {
                "task_id": task_id,
                "classification": "NEEDS_RECONCILIATION",
                "status": status,
                "next_action": task.get("next_action"),
                "inspected_at": utc_now(),
                "workspace": workspace,
                "reasons": lease_binding_errors,
            }
        if expires_at <= datetime.now(timezone.utc):
            return {
                "task_id": task_id,
                "classification": "NEEDS_RECONCILIATION",
                "status": status,
                "next_action": task.get("next_action"),
                "inspected_at": utc_now(),
                "workspace": inspect_workspace(root, None),
                "reasons": ["active task lease has expired", *operation_reasons],
            }
        if not checkpoint_path.is_file():
            classification = "NEEDS_RECONCILIATION"
            reasons = ["active task has no checkpoint", *operation_reasons]
        else:
            try:
                checkpoint = read_object(checkpoint_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return {"task_id": task_id, "classification": "UNSAFE_TO_RESUME", "reasons": [f"checkpoint is unreadable: {exc}"]}
            binding_errors = validate_checkpoint_binding(task, checkpoint)
            workspace = inspect_workspace(root, checkpoint)
            safe = checkpoint.get("resume_safe", True)
            classification = "SAFE_TO_RESUME" if safe and not binding_errors and not operation_reasons and not workspace["mismatch"] else "NEEDS_RECONCILIATION"
            if not safe:
                reasons = ["checkpoint explicitly forbids automatic resume", *operation_reasons]
            elif binding_errors:
                reasons = binding_errors + operation_reasons
            elif operation_reasons:
                reasons = operation_reasons
            elif workspace["mismatch"]:
                reasons = ["workspace does not agree with checkpoint", *workspace["reasons"]]
            else:
                reasons = ["checkpoint and task state are readable"]
    else:
        classification = "UNSAFE_TO_RESUME"
        reasons = [f"unsupported task status {status or '<missing>'}"]

    return {
        "task_id": task_id,
        "classification": classification,
        "status": status,
        "next_action": task.get("next_action"),
        "inspected_at": utc_now(),
        "workspace": workspace,
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id")
    args = parser.parse_args()
    try:
        with runtime_lock(args.project_root) as root:
            task_ids = [args.task_id] if args.task_id else [path.parent.name for path in sorted((root / "work").glob("*/task-state.json"))]
            results = [persist_reconciliation(root, inspect_task(root, task_id)) for task_id in task_ids]
            output = {"schema_version": 1, "inspected_at": utc_now(), "results": results}
            write_json_atomic(root / "recovery" / "recovery-state.json", output)
            for result in results:
                append_event(
                    args.project_root,
                    {"type": "RECOVERY_INSPECTED", "actor": "agentic-state-tools", "task_id": result["task_id"], "data": result},
                    acquire_lock=False,
                    refresh_checklist=False,
                )
    except RuntimeNotInitializedError as exc:
        print(f"RECOVERY_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"RECOVERY_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
