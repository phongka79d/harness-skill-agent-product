"""Rebuild runtime/state.json by replaying the immutable event journal."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    agent_path,
    apply_event,
    empty_state,
    ensure_runtime_initialized,
    iter_events,
    runtime_lock,
    write_json_atomic,
)


def rebuild_state_for_root(root: Path) -> dict:
    state = empty_state()
    seen: set[str] = set()
    for event in iter_events(root / "runtime" / "events.jsonl"):
        event_id = event["event_id"]
        if event_id in seen:
            raise ValueError(f"duplicate event_id: {event_id}")
        seen.add(event_id)
        state = apply_event(state, event)
    write_json_atomic(root / "runtime" / "state.json", state)
    return state


def rebuild_state(project_root: str, *, acquire_lock: bool = True) -> dict:
    if acquire_lock:
        with runtime_lock(project_root) as root:
            return rebuild_state_for_root(root)
    return rebuild_state_for_root(ensure_runtime_initialized(project_root))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()
    try:
        state = rebuild_state(args.project_root)
    except RuntimeNotInitializedError as exc:
        print(f"REBUILD_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError) as exc:
        print(f"REBUILD_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
