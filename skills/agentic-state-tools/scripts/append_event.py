"""Validate and append one immutable event, then rebuild derived views."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from rebuild_state import rebuild_state_for_root
from render_checklist import render_checklist
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    append_jsonl,
    ensure_runtime_initialized,
    iter_events,
    next_event_id,
    read_payload,
    runtime_lock,
    utc_now,
    apply_event,
    empty_state,
    validate_event_preconditions,
    validate_event,
)


def append_event_for_root(root, event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    events_path = root / "runtime" / "events.jsonl"
    events = iter_events(events_path)
    record = dict(event)
    record.setdefault("event_id", next_event_id(events))
    record.setdefault("timestamp", utc_now())
    validate_event(record)
    validate_event_preconditions(root, record)
    if any(item["event_id"] == record["event_id"] for item in events):
        raise ValueError(f"event_id already exists: {record['event_id']}")
    replayed = empty_state()
    for existing in events:
        replayed = apply_event(replayed, existing)
    apply_event(replayed, record)
    append_jsonl(events_path, record)
    return record, rebuild_state_for_root(root)


def append_event(
    project_root: str,
    event: dict[str, Any],
    *,
    acquire_lock: bool = True,
    refresh_checklist: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if acquire_lock:
        with runtime_lock(project_root) as root:
            record, state = append_event_for_root(root, event)
            if refresh_checklist:
                render_checklist(project_root, acquire_lock=False)
            return record, state
    root = ensure_runtime_initialized(project_root)
    record, state = append_event_for_root(root, event)
    if refresh_checklist:
        render_checklist(project_root, acquire_lock=False)
    return record, state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True, help="JSON file path or - for stdin")
    args = parser.parse_args()
    try:
        event = read_payload(args.input)
        if not isinstance(event, dict):
            raise ValueError("event must be a JSON object")
        record, state = append_event(args.project_root, event)
    except RuntimeNotInitializedError as exc:
        print(f"EVENT_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError) as exc:
        print(f"EVENT_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"EVENT_ACCEPTED: {record['event_id']} revision={state['revision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
