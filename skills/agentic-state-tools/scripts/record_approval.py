"""Persist an approval record as a generated runtime artifact."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from authorization import ACTOR_TYPES, POLICY_VERSION, required_actor_type
from append_event import append_event_for_root  # compatibility seam; required events are staged below
from rebuild_state import rebuild_state_for_root
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    next_revision,
    prepare_event_log,
    read_object,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
)
from runtime_transaction import RuntimeTransaction, TransactionError


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/approval.schema.json"

PRIMARY_ONLY_TARGETS = {"MASTER_PLAN", "SUB_PLAN", "CHANGE_REQUEST", "RUBRIC_OVERRIDE", "PLAN_SUPERSEDE", "PROFILE", "ROLLBACK"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="primary-agent")
    parser.add_argument("--actor-type", choices=tuple(sorted(ACTOR_TYPES)))
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
        executing_actor_type = args.actor_type or ("primary_agent" if args.actor.lower() in {"primary", "primary-agent"} else "agent")
        payload_actor_type = payload.get("actor_type")
        if payload_actor_type is not None and payload_actor_type != executing_actor_type:
            raise ValueError("approval.actor_type must match the executing actor type")
        if str(payload.get("decision", "")).upper() == "APPROVED" and target_type.upper() in PRIMARY_ONLY_TARGETS and executing_actor_type != "primary_agent":
            raise ValueError(f"{target_type} approvals require the Primary Agent")
        actor_id = payload.get("actor_id", args.actor)
        if actor_id != args.actor:
            raise ValueError("approval.actor_id must match the executing actor")
        if payload.get("approver", args.actor) != actor_id:
            raise ValueError("approval.approver must match actor identity")
        payload["actor_id"] = actor_id
        payload["actor_type"] = executing_actor_type
        payload["action"] = payload.get("action", target_type.upper())
        required_type = required_actor_type(payload["action"])
        if required_type is not None and executing_actor_type != required_type:
            raise ValueError(f"{payload['action']} requires actor_type={required_type}")
        payload["policy_version"] = payload.get("policy_version", POLICY_VERSION)
        payload["expires_at"] = payload.get("expires_at", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z"))
        with runtime_lock(args.project_root) as root:
            if target_type.upper() == "ROLLBACK":
                plan_path = root / "recovery" / f"rollback-plan-{target_id}.json"
                plan = read_object(plan_path)
                payload.setdefault("target_revision", plan.get("revision"))
                payload.setdefault("target_hash", plan.get("plan_hash"))
                if payload.get("target_revision") != plan.get("revision") or payload.get("target_hash") != plan.get("plan_hash"):
                    raise ValueError("rollback approval must bind to the current rollback plan")
            if payload.get("target_revision") is None or payload.get("target_hash") is None:
                raise ValueError("approval requires target_revision and target_hash")
            relative = f"approvals/{target_type}-{target_id}.json"
            target = root / relative
            existing_revision = int(read_object(target).get("revision", 0)) if target.is_file() else 0
            payload.setdefault("approval_id", f"APR-{target_type}-{target_id}-{existing_revision + 1}")
            payload["created_at"] = utc_now()
            payload.setdefault("issued_at", payload["created_at"])
            payload["revision"] = next_revision(payload, existing_revision)
            output = target
            event = {
                "type": "APPROVAL_RECORDED",
                "actor": args.actor,
                "data": {
                    "approval_id": payload["approval_id"],
                    "target_type": target_type,
                    "target_id": target_id,
                    "decision": payload["decision"],
                },
            }
            event_relative, event_revision, event_content, _ = prepare_event_log(
                root,
                event,
                artifact_overrides={relative: payload},
            )
            transaction = RuntimeTransaction(
                args.project_root,
                operation_type="APPROVAL",
                idempotency_key=f"approval:{target_type}:{target_id}:{payload['revision']}",
                expected_revisions={relative: existing_revision, event_relative: event_revision},
            )
            transaction.prepare([relative, event_relative])
            transaction.stage_json(relative, payload, SCHEMA)
            transaction.stage_text(event_relative, event_content)
            transaction.commit()
            rebuild_state_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"APPROVAL_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, TransactionError, OSError, ValueError, TypeError) as exc:
        print(f"APPROVAL_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"APPROVAL_WRITTEN: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
