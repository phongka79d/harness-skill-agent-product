"""Record a task heartbeat and refresh its generated lease artifact."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from append_event import append_event_for_root
from render_checklist import render_checklist_for_root
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    lease_expiry,
    read_object,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
)
from write_artifact import write_validated


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/lease.schema.json"


def normalize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("heartbeat payload must be an object")
    for field in ("task_id", "owner", "run_id"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"heartbeat.{field} must be a non-empty string")
    seconds = payload.get("lease_seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
        raise ValueError("heartbeat.lease_seconds must be a positive integer")
    record = dict(payload)
    validate_identifier(record["task_id"], "task_id")
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
            task_path = root / "work" / payload["task_id"] / "task-state.json"
            if not task_path.is_file():
                raise ValueError(f"task state does not exist for {payload['task_id']}")
            task_state = read_object(task_path)
            if str(task_state.get("status", "")).upper() not in {"RUNNING", "REVIEWING"}:
                raise ValueError("heartbeat requires an active RUNNING or REVIEWING task")

            lease_path = task_path.parent / "lease.json"
            existing = read_object(lease_path) if lease_path.is_file() else None
            if existing:
                for field in ("owner", "run_id"):
                    if existing.get(field) != payload[field]:
                        raise ValueError(f"lease identity mismatch for {field}")
                acquired_at = existing.get("acquired_at")
            else:
                acquired_at = utc_now()
            now = utc_now()
            lease = {
                "task_id": payload["task_id"],
                "owner": payload["owner"],
                "run_id": payload["run_id"],
                "acquired_at": acquired_at,
                "last_heartbeat": now,
                "lease_seconds": payload["lease_seconds"],
                "expires_at": lease_expiry(payload["lease_seconds"]),
                "owner_pid": existing.get("owner_pid", os.getpid()) if existing else os.getpid(),
                "owner_identity": existing.get("owner_identity", f"{payload['owner']}:{payload['run_id']}") if existing else f"{payload['owner']}:{payload['run_id']}",
            }
            target = write_validated(
                args.project_root,
                f"work/{payload['task_id']}/lease.json",
                lease,
                SCHEMA,
            )
            append_event_for_root(
                root,
                {
                    "type": "HEARTBEAT_RECORDED",
                    "actor": args.actor,
                    "task_id": payload["task_id"],
                    "run_id": payload["run_id"],
                    "data": {"expires_at": lease["expires_at"], "owner": payload["owner"]},
                },
            )
            render_checklist_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"HEARTBEAT_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"HEARTBEAT_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"HEARTBEAT_RECORDED: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
