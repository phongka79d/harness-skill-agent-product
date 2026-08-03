"""Validate event journal uniqueness and the generated state snapshot."""

from __future__ import annotations

import argparse
import sys

from runtime_utils import RuntimeLockedError, apply_event, empty_state, iter_events, read_object, runtime_lock


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()
    try:
        with runtime_lock(args.project_root) as root:
            events = iter_events(root / "runtime" / "events.jsonl")
            state = read_object(root / "runtime" / "state.json")
            ids = [event.get("event_id") for event in events]
            if any(not event_id for event_id in ids) or len(ids) != len(set(ids)):
                raise ValueError("event IDs must be present and unique")
            if state.get("revision") != len(events):
                raise ValueError(f"state revision {state.get('revision')} != event count {len(events)}")
            if events and state.get("last_event_id") != events[-1]["event_id"]:
                raise ValueError("state last_event_id does not match the event journal")
            if not isinstance(state.get("updated_at"), str) or not state["updated_at"].strip():
                raise ValueError("state updated_at must be a non-empty string")
            rebuilt = empty_state()
            for event in events:
                rebuilt = apply_event(rebuilt, event)
            if not events:
                # An empty journal has no authoritative event timestamp; preserve the
                # initialization timestamp while comparing the remaining snapshot.
                rebuilt["updated_at"] = state["updated_at"]
            if state != rebuilt:
                raise ValueError("state snapshot does not match replayed event journal")
    except RuntimeLockedError as exc:
        print(f"STATE_BUSY: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(f"STATE_INVALID: {exc}", file=sys.stderr)
        return 1
    print("STATE_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
