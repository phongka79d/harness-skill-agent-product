"""Acquire one task, file, or resource lock as a generated runtime artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from append_event import append_event_for_root
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    LOCK_DIRECTORIES,
    lease_expiry,
    lock_artifact_path,
    process_is_alive,
    parse_timestamp,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
    write_json_exclusive,
)
from validate_payload import validate
from write_artifact import write_validated
from runtime_utils import read_json


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/lock.schema.json"
RECLAIM_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/lock-reclaim.schema.json"


def normalize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("lock payload must be an object")
    kind = payload.get("kind")
    if kind not in LOCK_DIRECTORIES:
        raise ValueError(f"lock.kind must be one of {sorted(LOCK_DIRECTORIES)}")
    for field in ("key", "owner", "run_id"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"lock.{field} must be a non-empty string")
    seconds = payload.get("lease_seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
        raise ValueError("lock.lease_seconds must be a positive integer")
    if "task_id" in payload and (not isinstance(payload["task_id"], str) or not payload["task_id"].strip()):
        raise ValueError("lock.task_id must be a non-empty string when provided")
    if payload.get("task_id"):
        validate_identifier(payload["task_id"], "task_id")
    return dict(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="agentic-state-tools")
    args = parser.parse_args()
    try:
        payload = normalize(read_payload(args.input))
        with runtime_lock(args.project_root) as root:
            target = lock_artifact_path(root, payload["kind"], payload["key"])
            reclaimed: dict[str, Any] | None = None
            if target.is_file():
                try:
                    existing = read_json(target)
                    if not isinstance(existing, dict):
                        raise ValueError("existing lock must be an object")
                    expires_at = parse_timestamp(existing.get("expires_at"))
                except (OSError, ValueError, TypeError) as exc:
                    raise ValueError(f"existing lock is unreadable: {exc}") from exc
                if expires_at > datetime.now(timezone.utc):
                    raise ValueError(f"lock is already held: {payload['kind']}:{payload['key']}")
                owner_pid = existing.get("owner_pid")
                if isinstance(owner_pid, int) and not isinstance(owner_pid, bool) and process_is_alive(owner_pid):
                    raise ValueError(f"expired lock owner is still live: pid={owner_pid}")
                reclaimed = existing
                target.unlink()
            record = dict(payload)
            record["lock_id"] = record.get("lock_id") or f"LOCK-{payload['kind'].upper()}-{uuid.uuid4().hex[:12].upper()}"
            record["owner_pid"] = record.get("owner_pid", os.getpid())
            record["owner_identity"] = record.get("owner_identity") or f"{record['owner']}:{record['run_id']}:{record['owner_pid']}"
            record["acquired_at"] = utc_now()
            record["expires_at"] = lease_expiry(payload["lease_seconds"])
            errors = validate(record, read_json(SCHEMA))
            if errors:
                raise ValueError("; ".join(errors))
            try:
                write_json_exclusive(target, record)
            except FileExistsError as exc:
                raise ValueError(f"lock is already held: {payload['kind']}:{payload['key']}") from exc
            if reclaimed is not None:
                old_lock_id = str(reclaimed.get("lock_id") or "LOCK-UNKNOWN")
                old_owner_pid = reclaimed.get("owner_pid") if isinstance(reclaimed.get("owner_pid"), int) else None
                owner_liveness = "DEAD" if old_owner_pid is not None else "UNKNOWN"
                reclaim = {
                    "schema_version": 1,
                    "reclaim_id": f"RECLAIM-{old_lock_id}-{record['lock_id']}",
                    "old_lock_id": old_lock_id,
                    "new_lock_id": record["lock_id"],
                    "old_owner": str(reclaimed.get("owner") or "unknown"),
                    "old_owner_pid": old_owner_pid,
                    "reclaimed_at": utc_now(),
                    "owner_liveness": owner_liveness,
                    "reason": "expired lock owner was not live" if old_owner_pid is not None else "legacy lock had no owner identity",
                    "evidence": {"old_expires_at": reclaimed.get("expires_at"), "old_owner_identity": reclaimed.get("owner_identity")},
                }
                reclaim_hash = hashlib.sha256(json.dumps(reclaim, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                reclaim["evidence_hash"] = reclaim_hash
                write_validated(args.project_root, f"recovery/lock-reclaim-{reclaim['reclaim_id']}.json", reclaim, RECLAIM_SCHEMA)
                reclaim_event = {
                    "type": "LOCK_RECLAIMED",
                    "actor": args.actor,
                    "run_id": record["run_id"],
                    "data": {"old_lock_id": reclaimed.get("lock_id"), "old_owner": reclaimed.get("owner"), "kind": record["kind"], "key": record["key"], "reclaim_id": reclaim["reclaim_id"], "evidence_hash": reclaim["evidence_hash"]},
                }
                if record.get("task_id"):
                    reclaim_event["task_id"] = record["task_id"]
                append_event_for_root(root, reclaim_event)
            event = {
                "type": "LOCK_ACQUIRED",
                "actor": args.actor,
                "run_id": record["run_id"],
                "data": {"lock_id": record["lock_id"], "kind": record["kind"], "key": record["key"]},
            }
            if record.get("task_id"):
                event["task_id"] = record["task_id"]
            append_event_for_root(root, event)
    except RuntimeNotInitializedError as exc:
        print(f"LOCK_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"LOCK_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"LOCK_ACQUIRED: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
