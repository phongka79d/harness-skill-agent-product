"""Validate and atomically record one task-bound verification result."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rebuild_state import rebuild_state_for_root
from runtime_transaction import RuntimeTransaction, TransactionError
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    next_revision,
    parse_timestamp,
    prepare_event_log,
    read_object,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
)
from validate_payload import validate
from verification_contract import (
    PHASES,
    STATUSES,
    load_task_state,
    normalize_relevant_files,
    validate_hash,
    validate_identity,
    workspace_hash,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "verification-evidence.schema.json"


def normalize(payload: Any, *, project_root: str | Path, root: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("verification evidence must be an object")
    record = dict(payload)
    task_id = record.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("verification evidence requires task_id")
    validate_identifier(task_id, "task_id")
    task_state = load_task_state(root, task_id)
    validate_identity(record, task_state, label="evidence")

    evidence_id = record.get("evidence_id")
    if evidence_id is None:
        evidence_id = f"E-{task_id}-{utc_now().replace(':', '').replace('-', '').replace('.', '')}"
    validate_identifier(evidence_id, "evidence_id")
    record["evidence_id"] = evidence_id

    case_id = record.get("verification_case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("verification evidence requires verification_case_id")
    validate_identifier(case_id, "verification_case_id")
    phase = str(record.get("phase", "")).upper()
    if phase not in PHASES:
        raise ValueError("verification evidence phase must be RED, GREEN, or BROAD")
    record["phase"] = phase
    verification_type = record.get("verification_type")
    if not isinstance(verification_type, str) or not verification_type.strip():
        raise ValueError("verification evidence requires verification_type")
    command = record.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("verification evidence.command is required")
    exit_code = record.get("exit_code")
    if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code < 0):
        raise ValueError("verification evidence.exit_code must be a non-negative integer or null")

    expected_status = "FAIL" if phase == "RED" and exit_code not in (None, 0) else "PASS" if exit_code == 0 else "NOT_RUN"
    status = str(record.get("status", expected_status)).upper()
    if status not in STATUSES:
        raise ValueError("verification evidence.status is invalid")
    if phase == "RED":
        if exit_code is None or exit_code == 0:
            raise ValueError("RED evidence must fail with a non-zero exit code")
        signature = record.get("failure_signature")
        if not isinstance(signature, str) or not signature.strip():
            raise ValueError("RED evidence requires failure_signature")
    elif phase in {"GREEN", "BROAD"} and (status != "PASS" or exit_code != 0):
        raise ValueError(f"{phase} evidence must have PASS status and exit_code 0")
    if phase == "RED" and status not in {"PASS", "FAIL"}:
        raise ValueError("RED evidence must record a FAIL result")
    if phase not in {"RED", "GREEN", "BROAD"} and status == "PASS" and exit_code != 0:
        raise ValueError("a passing verification result requires exit_code 0")
    if phase not in {"RED", "GREEN", "BROAD"} and status == "NOT_RUN" and exit_code is not None:
        raise ValueError("NOT_RUN evidence must use a null exit_code")
    if phase in {"GREEN", "BROAD"} and status != expected_status:
        raise ValueError(f"verification evidence.status does not match exit_code for {phase}")
    record["status"] = status

    acceptance_ids = record.get("acceptance_criterion_ids")
    if not isinstance(acceptance_ids, list) or not acceptance_ids or any(not isinstance(item, str) or not item.strip() for item in acceptance_ids):
        raise ValueError("verification evidence requires acceptance_criterion_ids")
    record["acceptance_criterion_ids"] = sorted(set(acceptance_ids))
    record["relevant_files"] = normalize_relevant_files(record.get("relevant_files"))
    current_hash = workspace_hash(project_root, record["relevant_files"])
    if record.get("workspace_hash") is not None and record.get("workspace_hash") != current_hash:
        validate_hash(record.get("workspace_hash"))
        raise ValueError("verification evidence.workspace_hash is stale for the current workspace")
    record["workspace_hash"] = current_hash
    snapshot_head = None
    try:
        from capture_workspace import capture_workspace

        snapshot_head = capture_workspace(project_root).get("head_commit")
    except (OSError, TypeError, ValueError):
        snapshot_head = None
    if snapshot_head:
        record.setdefault("base_commit", snapshot_head)
    record["recorded_at"] = record.get("recorded_at") or utc_now()
    parse_timestamp(record["recorded_at"])
    record["task_id"] = task_id
    errors = validate(record, read_object(SCHEMA), base_path=SCHEMA.parent)
    if errors:
        raise ValueError("verification evidence schema validation failed: " + "; ".join(errors))
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="verification-recorder")
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
        with runtime_lock(args.project_root) as root:
            record = normalize(payload, project_root=root.parent, root=root)
            relative = f"work/{record['task_id']}/verification/{record['evidence_id']}.json"
            target = root / relative
            if target.exists():
                raise ValueError(f"verification evidence already exists: {record['evidence_id']}")
            event_relative, event_revision, event_content, _ = prepare_event_log(
                root,
                {
                    "type": "VERIFICATION_EVIDENCE_RECORDED",
                    "actor": args.actor,
                    "task_id": record["task_id"],
                    "run_id": record["run_id"],
                    "data": {
                        "evidence_id": record["evidence_id"],
                        "verification_case_id": record["verification_case_id"],
                        "phase": record["phase"],
                        "task_revision": record["task_revision"],
                    },
                },
                artifact_overrides={relative: record},
            )
            transaction = RuntimeTransaction(
                args.project_root,
                operation_type="VERIFICATION_EVIDENCE",
                idempotency_key=f"verification-evidence:{record['task_id']}:{record['evidence_id']}",
                expected_revisions={relative: 0, event_relative: event_revision},
            )
            transaction.prepare([relative, event_relative])
            transaction.stage_json(relative, record, SCHEMA)
            transaction.stage_text(event_relative, event_content)
            transaction.commit()
            rebuild_state_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"VERIFICATION_EVIDENCE_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, TransactionError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"VERIFICATION_EVIDENCE_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"VERIFICATION_EVIDENCE_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
