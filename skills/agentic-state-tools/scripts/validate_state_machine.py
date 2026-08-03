"""Validate state-machine source and its generated consumer schemas."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runtime_utils import read_json


def validate_definition(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["state-machine must be an object"]
    statuses = value.get("statuses")
    terminal = value.get("terminal_statuses")
    non_state = value.get("non_state_events")
    if not isinstance(statuses, dict) or not statuses:
        return ["state-machine.statuses must be a non-empty object"]
    if not isinstance(terminal, list) or any(not isinstance(item, str) for item in terminal):
        errors.append("state-machine.terminal_statuses must be an array of strings")
        terminal = []
    if not isinstance(non_state, list) or any(not isinstance(item, str) for item in non_state):
        errors.append("state-machine.non_state_events must be an array of strings")
        non_state = []
    events: list[str] = []
    for status, item in statuses.items():
        if not isinstance(status, str) or not status:
            errors.append("status names must be non-empty strings")
            continue
        if not isinstance(item, dict):
            errors.append(f"status {status} must be an object")
            continue
        event = item.get("event")
        if not isinstance(event, str) or event != event.upper() or not event:
            errors.append(f"status {status} must define an uppercase event")
        elif event in events or event in non_state:
            errors.append(f"duplicate event name: {event}")
        else:
            events.append(event)
        for actor in ("executor", "reviewer"):
            transitions = item.get(actor)
            if not isinstance(transitions, list) or any(not isinstance(target, str) for target in transitions):
                errors.append(f"status {status}.{actor} must be an array of status names")
            else:
                for target in transitions:
                    if target not in statuses:
                        errors.append(f"status {status}.{actor} references missing target {target}")
        if (status in terminal) != (item.get("terminal", status in terminal)):
            errors.append(f"terminal flag mismatch for {status}")
    for status in terminal:
        if status not in statuses:
            errors.append(f"terminal status is undefined: {status}")
    if set(events) & set(non_state):
        errors.append("state and non-state event names overlap")

    root = Path(__file__).resolve().parents[1]
    task_schema = read_json(root / "schemas/task-state.schema.json")
    task_enum = task_schema.get("properties", {}).get("status", {}).get("enum", [])
    if set(task_enum) != set(statuses):
        errors.append("task-state.schema.json status enum differs from state-machine")
    event_schema = read_json(root / "schemas/event.schema.json")
    event_enum = event_schema.get("properties", {}).get("type", {}).get("enum", [])
    if set(event_enum) != set(events + non_state):
        errors.append("event.schema.json type enum differs from state-machine")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        errors = validate_definition(read_json(args.input))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"STATE_MACHINE_INVALID: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"STATE_MACHINE_INVALID: {error}", file=sys.stderr)
        return 1
    print("STATE_MACHINE_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
