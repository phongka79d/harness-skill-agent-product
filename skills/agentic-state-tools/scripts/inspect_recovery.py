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
    utc_now,
    validate_identifier,
    write_json_atomic,
)
from write_artifact import write_validated


OPERATION_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/operation.schema.json"


def inspect_workspace(root: Path, checkpoint: dict | None) -> dict:
    snapshot = capture_workspace(
        root,
        expected_files=[value for value in (checkpoint or {}).get("files_modified", []) if isinstance(value, str)],
        expected_base=(checkpoint or {}).get("base_commit"),
    )
    snapshot["status"] = snapshot["workspace_status"]
    return snapshot

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

    if status in {"PENDING", "READY", "QUEUED", "WAITING", "COMPLETED", "ACCEPTED"}:
        classification = "NEEDS_RECONCILIATION" if operation_reasons else "SAFE_TO_RESUME"
        reasons = operation_reasons or [f"status {status} has no active side effect"]
    elif status in {"RUNNING", "STALE", "RECOVERY_PENDING", "RESUMING"}:
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
            workspace = inspect_workspace(root, checkpoint)
            safe = checkpoint.get("resume_safe", True)
            classification = "SAFE_TO_RESUME" if safe and not operation_reasons and not workspace["mismatch"] else "NEEDS_RECONCILIATION"
            if not safe:
                reasons = ["checkpoint explicitly forbids automatic resume", *operation_reasons]
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
