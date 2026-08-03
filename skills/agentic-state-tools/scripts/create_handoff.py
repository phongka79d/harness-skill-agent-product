"""Validate and write a generated executor handoff artifact."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from append_event import append_event
from render_checklist import render_checklist
from runtime_utils import RuntimeLockedError, RuntimeNotInitializedError, next_revision, read_object, read_payload, runtime_lock, utc_now, validate_identifier
from write_artifact import write_validated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="executor")
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
        if not isinstance(payload, dict):
            raise ValueError("handoff must be an object")
        validate_identifier(args.task_id, "task_id")
        payload = dict(payload)
        payload["task_id"] = args.task_id
        payload.setdefault("handoff_id", f"HANDOFF-{args.task_id}-{utc_now().replace(':', '').replace('-', '')}")
        payload.setdefault("created_at", utc_now())
        with runtime_lock(args.project_root) as root:
            existing = root / "work" / args.task_id / "handoff.json"
            existing_revision = int(read_object(existing).get("revision", 0)) if existing.is_file() else 0
            payload["revision"] = next_revision(payload, existing_revision)
            target = write_validated(
                args.project_root,
                f"work/{args.task_id}/handoff.json",
                payload,
                Path(__file__).resolve().parents[1] / "schemas/handoff.schema.json",
            )
            append_event(
                args.project_root,
                {"type": "HANDOFF_CREATED", "actor": args.actor, "task_id": args.task_id, "data": {"handoff_id": payload["handoff_id"]}},
                acquire_lock=False,
                refresh_checklist=False,
            )
            render_checklist(args.project_root, acquire_lock=False)
    except RuntimeNotInitializedError as exc:
        print(f"HANDOFF_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"HANDOFF_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"HANDOFF_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
