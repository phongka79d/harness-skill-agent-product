"""Persist an approval record as a generated runtime artifact."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from append_event import append_event_for_root
from runtime_utils import RuntimeLockedError, RuntimeNotInitializedError, next_revision, read_object, read_payload, runtime_lock, utc_now, validate_identifier
from write_artifact import write_validated


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/approval.schema.json"

PRIMARY_ONLY_TARGETS = {"MASTER_PLAN", "SUB_PLAN", "CHANGE_REQUEST", "RUBRIC_OVERRIDE", "ARCHITECTURE_CHANGE", "PLAN_SUPERSEDE", "PROFILE", "ROLLBACK"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="primary-agent")
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
        if not isinstance(payload, dict):
            raise ValueError("approval must be an object")
        payload = dict(payload)
        target_type = payload.get("target_type")
        target_id = payload.get("target_id")
        if not isinstance(target_type, str) or not target_type.strip():
            raise ValueError("approval.target_type must be a non-empty string")
        if not isinstance(target_id, str) or not target_id.strip():
            raise ValueError("approval.target_id must be a non-empty string")
        validate_identifier(target_type, "target_type")
        validate_identifier(target_id, "target_id")
        if str(payload.get("decision", "")).upper() == "APPROVED" and target_type.upper() in PRIMARY_ONLY_TARGETS and args.actor.lower() not in {"primary", "primary-agent"}:
            raise ValueError(f"{target_type} approvals require the Primary Agent")
        with runtime_lock(args.project_root) as root:
            relative = f"approvals/{target_type}-{target_id}.json"
            target = root / relative
            existing_revision = int(read_object(target).get("revision", 0)) if target.is_file() else 0
            payload.setdefault("approval_id", f"APR-{target_type}-{target_id}-{existing_revision + 1}")
            payload["created_at"] = utc_now()
            payload["revision"] = next_revision(payload, existing_revision)
            output = write_validated(args.project_root, relative, payload, SCHEMA)
            append_event_for_root(root, {"type": "APPROVAL_RECORDED", "actor": args.actor, "data": {"approval_id": payload["approval_id"], "target_type": target_type, "target_id": target_id, "decision": payload["decision"]}})
    except RuntimeNotInitializedError as exc:
        print(f"APPROVAL_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"APPROVAL_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"APPROVAL_WRITTEN: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
