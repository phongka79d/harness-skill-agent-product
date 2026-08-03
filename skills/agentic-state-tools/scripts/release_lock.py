"""Release a lock only when its identity matches the submitting owner and run."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from append_event import append_event_for_root
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    LOCK_DIRECTORIES,
    lock_artifact_path,
    read_object,
    read_payload,
    runtime_lock,
)


def normalize(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("release payload must be an object")
    for field in ("kind", "key", "lock_id", "owner", "run_id"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"release.{field} must be a non-empty string")
    if payload["kind"] not in LOCK_DIRECTORIES:
        raise ValueError(f"release.kind must be one of {sorted(LOCK_DIRECTORIES)}")
    return {field: payload[field] for field in ("kind", "key", "lock_id", "owner", "run_id")}


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
            if not target.is_file():
                raise ValueError(f"lock is not held: {payload['kind']}:{payload['key']}")
            record = read_object(target)
            for field in ("lock_id", "owner", "run_id"):
                if record.get(field) != payload[field]:
                    raise ValueError(f"lock identity mismatch for {field}")
            target.unlink()
            event = {
                "type": "LOCK_RELEASED",
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
    print(f"LOCK_RELEASED: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
