"""Record an idempotent side-effect operation transition."""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Any

from append_event import append_event_for_root
from operation_ledger import read_operation_ledger
from render_checklist import render_checklist_for_root
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    append_jsonl,
    read_json,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
)
from validate_payload import validate


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/operation.schema.json"
VALID_TYPES = {
    "DATABASE_MIGRATION",
    "EMAIL",
    "EXTERNAL_RESOURCE",
    "COMMIT",
    "PUSH",
    "DEPLOY",
    "DELETE",
    "DEPENDENCY_INSTALL",
    "SCHEMA_CHANGE",
    "OTHER",
}
VALID_STATUSES = {"STARTED", "COMPLETED", "FAILED", "UNKNOWN"}
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "UNKNOWN"}


def normalize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("operation payload must be an object")
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("operation.task_id must be a non-empty string")
    validate_identifier(task_id, "task_id")
    operation_type = str(payload.get("type", "")).upper()
    if operation_type not in VALID_TYPES:
        raise ValueError(f"operation.type must be one of {sorted(VALID_TYPES)}")
    status = str(payload.get("status", "")).upper()
    if status not in VALID_STATUSES:
        raise ValueError(f"operation.status must be one of {sorted(VALID_STATUSES)}")
    command = payload.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("operation.command must be a non-empty string")
    for field in ("operation_id", "run_id"):
        if field in payload and (not isinstance(payload[field], str) or not payload[field].strip()):
            raise ValueError(f"operation.{field} must be a non-empty string when provided")
    record = dict(payload)
    record["task_id"] = task_id
    record["type"] = operation_type
    record["status"] = status
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="agentic-state-tools")
    args = parser.parse_args()
    try:
        payload = normalize(read_payload(args.input))
        with runtime_lock(args.project_root) as root:
            operations_path = root / "work" / payload["task_id"] / "operations.jsonl"
            records = read_operation_ledger(operations_path, payload["task_id"], SCHEMA)
            operation_id = payload.get("operation_id") or f"OP-{payload['task_id']}-{uuid.uuid4().hex[:12].upper()}"
            existing = [record for record in records if record["operation_id"] == operation_id]
            latest = existing[-1] if existing else None
            if latest:
                for field in ("task_id", "type", "command"):
                    if latest.get(field) != payload[field]:
                        raise ValueError(f"operation identity mismatch for {field}")
                if latest.get("run_id") != payload.get("run_id"):
                    raise ValueError("operation identity mismatch for run_id")
                if latest["status"] in TERMINAL_STATUSES:
                    if latest["status"] == payload["status"]:
                        evidence_fields = ("result_checksum", "result_summary", "output_hash", "commit_marker", "rollback_marker")
                        if any(latest.get(field) is not None for field in evidence_fields):
                            if any(payload.get(field) != latest.get(field) for field in evidence_fields):
                                raise ValueError("terminal operation evidence conflicts; reconcile before retry")
                        print(f"OPERATION_IDEMPOTENT: {operation_id} status={latest['status']}")
                        return 0
                    raise ValueError("operation is terminal; inspect external state before retry")
                if latest["status"] == "STARTED" and payload["status"] == "STARTED":
                    print(f"OPERATION_IDEMPOTENT: {operation_id} status=STARTED")
                    return 0
                if latest["status"] == "STARTED" and payload["status"] not in TERMINAL_STATUSES:
                    raise ValueError("STARTED operation may only transition to a terminal status")

            record = dict(payload)
            record["operation_id"] = operation_id
            record["recorded_at"] = utc_now()
            record["revision"] = (latest["revision"] + 1) if latest else 1
            record["actor"] = args.actor
            record.setdefault("phase", "PREPARE" if record["status"] == "STARTED" else "COMMIT" if record["status"] == "COMPLETED" else "ROLLBACK")
            record.setdefault("transaction_id", operation_id)
            record.setdefault("idempotency_key", operation_id)
            errors = validate(record, read_json(SCHEMA))
            if errors:
                raise ValueError("; ".join(errors))
            append_jsonl(operations_path, record)
            event = {
                "type": "OPERATION_RECORDED",
                "actor": args.actor,
                "task_id": record["task_id"],
                "data": {"operation_id": operation_id, "status": record["status"], "type": record["type"]},
            }
            if record.get("run_id"):
                event["run_id"] = record["run_id"]
            append_event_for_root(root, event)
            render_checklist_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"OPERATION_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"OPERATION_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"OPERATION_RECORDED: {record['operation_id']} status={record['status']} revision={record['revision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
