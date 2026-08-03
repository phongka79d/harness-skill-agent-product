"""Atomically issue a new execution identity for a recoverable task."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from append_event import append_event_for_root
from dispatch_transaction import _append_operation
from render_checklist import render_checklist_for_root
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    read_object,
    read_payload,
    lease_expiry,
    runtime_lock,
    utc_now,
    write_json_atomic,
)
from task_state_contract import validate_execution_identity
from validate_payload import validate
from write_artifact import write_validated


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/attempt-reissue.schema.json"
TASK_SCHEMA = ROOT / "schemas/task-state.schema.json"
LEASE_SCHEMA = ROOT / "schemas/lease.schema.json"
ALLOWED_STATUSES = {"REPAIR_REQUIRED", "STALE", "RECOVERY_PENDING"}


def _validate_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("attempt reissue must be an object")
    errors = validate(payload, read_object(SCHEMA))
    if errors:
        raise ValueError("invalid attempt reissue: " + "; ".join(errors))
    return dict(payload)


def _replace_identity(record: dict[str, Any], task_id: str, identity: dict[str, str]) -> None:
    if record.get("task_id") == task_id:
        record.update(identity)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--actor", default="agentic-state-tools")
    args = parser.parse_args()
    target = None
    try:
        payload = _validate_payload(read_payload(args.input))
        task_id = payload["task_id"]
        expected_revision = args.expected_revision if args.expected_revision is not None else payload.get("expected_revision")
        if args.expected_revision is not None and payload.get("expected_revision") is not None and payload["expected_revision"] != args.expected_revision:
            raise ValueError("--expected-revision does not match payload.expected_revision")
        with runtime_lock(args.project_root) as root:
            task_path = root / "work" / task_id / "task-state.json"
            queue_path = root / "runtime" / "queue.json"
            lease_path = root / "work" / task_id / "lease.json"
            if not task_path.is_file() or not queue_path.is_file():
                raise ValueError("reissue requires current task and queue artifacts")
            current = read_object(task_path)
            current_revision = current.get("revision", 0)
            if expected_revision is not None and expected_revision != current_revision:
                raise ValueError(f"stale revision: expected {expected_revision}, current {current_revision}")
            status = str(current.get("status", "")).upper()
            if status not in ALLOWED_STATUSES:
                raise ValueError(f"task status is not reissuable: {status}")
            for field in ("run_id", "attempt_id", "dispatch_id"):
                if not isinstance(current.get(field), str) or not current[field].strip():
                    raise ValueError(f"current task is missing {field}")

            queue = read_object(queue_path)
            identity = {
                "run_id": payload["new_run_id"],
                "attempt_id": payload["new_attempt_id"],
                "dispatch_id": payload["new_dispatch_id"],
            }
            task_records = [record for record in queue.get("tasks", []) if isinstance(record, dict) and record.get("task_id") == task_id]
            state_records = [record for record in queue.get("task_states", []) if isinstance(record, dict) and record.get("task_id") == task_id]
            dispatch_records = [record for record in queue.get("dispatches", []) if isinstance(record, dict) and record.get("task_id") == task_id]
            if not task_records or not state_records or not dispatch_records:
                raise ValueError("reissue requires task, task-state, and dispatch queue bindings")

            old_queue = json.loads(json.dumps(queue))
            old_task = json.loads(json.dumps(current))
            old_lease = read_object(lease_path) if lease_path.is_file() else None
            operation_id = f"OP-{task_id}-REISSUE-{uuid.uuid4().hex[:12].upper()}"
            operation = {
                "operation_id": operation_id,
                "task_id": task_id,
                "run_id": identity["run_id"],
                "type": "OTHER",
                "status": "STARTED",
                "command": "REISSUE_TASK_ATTEMPT",
                "actor": args.actor,
                "result_summary": payload["reason"],
            }
            _append_operation(root, task_id, operation)
            try:
                next_task = dict(current)
                next_task.update({"status": "QUEUED_SYNC", "previous_revision": current_revision, "revision": current_revision + 1, "updated_at": utc_now(), **identity})
                write_validated(str(args.project_root), f"work/{task_id}/task-state.json", next_task, TASK_SCHEMA)
                for collection in (queue["tasks"], queue["task_states"], queue["dispatches"]):
                    for record in collection:
                        if isinstance(record, dict) and record.get("task_id") == task_id:
                            _replace_identity(record, task_id, identity)
                            record["revision"] = next_task["revision"]
                            if record in queue["tasks"]:
                                record["queue_state"] = "DISPATCHED"
                            if record in queue["task_states"]:
                                record["status"] = "QUEUED_SYNC"
                queue["revision"] = int(queue.get("revision", 0)) + 1
                write_json_atomic(queue_path, queue)

                lease = dict(old_lease or {})
                lease_seconds = int(lease.get("lease_seconds", 300))
                lease.update({"task_id": task_id, "owner": lease.get("owner", "executor"), "run_id": identity["run_id"], "attempt_id": identity["attempt_id"], "dispatch_id": identity["dispatch_id"], "task_revision": next_task["revision"], "acquired_at": utc_now(), "last_heartbeat": utc_now(), "lease_seconds": lease_seconds, "expires_at": lease_expiry(lease_seconds)})
                write_validated(str(args.project_root), f"work/{task_id}/lease.json", lease, LEASE_SCHEMA)
                validate_execution_identity(next_task, lease, queue)
                append_event_for_root(root, {"type": "OPERATION_RECORDED", "actor": args.actor, "task_id": task_id, "run_id": identity["run_id"], "data": {"operation": "REISSUE_TASK_ATTEMPT", "operation_id": operation_id, "attempt_id": identity["attempt_id"], "dispatch_id": identity["dispatch_id"]}})
                append_event_for_root(root, {"type": "TASK_QUEUED_SYNC", "actor": args.actor, "task_id": task_id, "run_id": identity["run_id"], "data": {"operation": "REISSUE_TASK_ATTEMPT", "attempt_id": identity["attempt_id"], "dispatch_id": identity["dispatch_id"], "reason": payload["reason"]}})
                _append_operation(root, task_id, {**operation, "status": "COMPLETED", "phase": "COMMIT", "commit_marker": operation_id, "result_summary": "task attempt reissued"})
                render_checklist_for_root(root)
                target = task_path
            except Exception:
                write_json_atomic(queue_path, old_queue)
                write_validated(str(args.project_root), f"work/{task_id}/task-state.json", old_task, TASK_SCHEMA)
                if old_lease is None:
                    if lease_path.is_file():
                        lease_path.unlink()
                else:
                    write_validated(str(args.project_root), f"work/{task_id}/lease.json", old_lease, LEASE_SCHEMA)
                try:
                    _append_operation(root, task_id, {**operation, "status": "FAILED", "phase": "ROLLBACK", "rollback_marker": operation_id, "result_summary": "task attempt reissue failed"})
                except Exception:
                    pass
                raise
    except RuntimeNotInitializedError as exc:
        print(f"TASK_REISSUE_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"TASK_REISSUE_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"TASK_ATTEMPT_REISSUED: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
