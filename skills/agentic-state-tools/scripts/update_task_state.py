"""Validate and atomically update one executor-owned task-state artifact."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from append_event import append_event, append_event_for_root
from render_checklist import render_checklist
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    STATUS_TO_EVENT_TYPE,
    TERMINAL_STATUSES,
    assert_terminal_cleanup_safe,
    cleanup_task_runtime,
    inspect_terminal_cleanup,
    read_object,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
)
from validate_transition import is_allowed_transition
from write_artifact import write_validated


INITIAL_STATUSES = {"PENDING", "READY", "QUEUED", "QUEUED_ASYNC", "QUEUED_SYNC"}


def append_cleanup_events(root, task_id: str, cleanup: dict) -> None:
    for lease in cleanup["leases"]:
        append_event_for_root(
            root,
            {"type": "LEASE_RELEASED", "actor": "agentic-state-tools", "task_id": task_id, "run_id": lease.get("run_id"), "data": {"reason": "terminal_task"}},
        )
    for lock in cleanup["locks"]:
        append_event_for_root(
            root,
            {"type": "LOCK_RELEASED", "actor": "agentic-state-tools", "task_id": task_id, "run_id": lock.get("run_id"), "data": {"lock_id": lock.get("lock_id"), "kind": lock.get("kind"), "key": lock.get("key"), "reason": "terminal_task"}},
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="executor")
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
        if not isinstance(payload, dict) or not isinstance(payload.get("task_id"), str) or not payload["task_id"]:
            raise ValueError("task-state requires a non-empty string task_id")
        payload = dict(payload)
        task_id = payload["task_id"]
        validate_identifier(task_id, "task_id")
        requested_status = str(payload.get("status", "")).upper()
        if not requested_status:
            raise ValueError("task-state requires status")
        if requested_status not in STATUS_TO_EVENT_TYPE:
            raise ValueError(f"unsupported task status: {requested_status}")
        if requested_status == "ACCEPTED":
            raise ValueError("only create_review.py may mark a task ACCEPTED")
        if "review_status" in payload:
            raise ValueError("review_status is derived from review.json and cannot be submitted by an executor")

        with runtime_lock(args.project_root) as root:
            target = root / "work" / task_id / "task-state.json"
            current = read_object(target) if target.exists() else None
            current_revision = int(current.get("revision", 0)) if current else 0
            expected = int(payload.pop("expected_revision", current_revision))
            if expected != current_revision:
                raise ValueError(f"stale revision: expected {expected}, current {current_revision}")
            if current:
                current_status = str(current.get("status", "")).upper()
                if not is_allowed_transition(current_status, requested_status, actor="executor"):
                    raise ValueError(f"invalid executor transition: {current_status} -> {requested_status}")
            elif requested_status not in INITIAL_STATUSES:
                raise ValueError(f"initial task status must be one of {sorted(INITIAL_STATUSES)}")

            if requested_status in TERMINAL_STATUSES:
                assert_terminal_cleanup_safe(root, task_id)

            payload["status"] = requested_status
            if requested_status in TERMINAL_STATUSES:
                payload["next_action"] = "none"
            payload["previous_revision"] = current_revision if current else None
            payload["revision"] = current_revision + 1
            payload["updated_at"] = utc_now()
            target = write_validated(
                args.project_root,
                f"work/{task_id}/task-state.json",
                payload,
                Path(__file__).resolve().parents[1] / "schemas/task-state.schema.json",
            )
            cleanup = cleanup_task_runtime(root, task_id) if requested_status in TERMINAL_STATUSES else {"leases": [], "locks": []}
            if requested_status in TERMINAL_STATUSES:
                post_cleanup = inspect_terminal_cleanup(root, task_id)
                if not post_cleanup["valid"]:
                    raise ValueError("terminal cleanup could not be verified: " + "; ".join(post_cleanup["reasons"]))
            append_event(
                args.project_root,
                {
                    "type": STATUS_TO_EVENT_TYPE[requested_status],
                    "actor": args.actor,
                    "task_id": task_id,
                    "data": {"task_revision": payload["revision"]},
                },
                acquire_lock=False,
                refresh_checklist=False,
            )
            append_cleanup_events(root, task_id, cleanup)
            render_checklist(args.project_root, acquire_lock=False)
    except RuntimeNotInitializedError as exc:
        print(f"TASK_STATE_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"TASK_STATE_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"TASK_STATE_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
