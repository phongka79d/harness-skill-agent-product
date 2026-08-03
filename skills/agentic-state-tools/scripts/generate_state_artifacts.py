"""Emit deterministic state-machine consumer data from the authoritative source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime_utils import write_json_atomic
from state_machine import event_status_map, load_state_machine, status_event_map
from validate_state_machine import validate_definition


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        definition = load_state_machine() if Path(args.input).resolve() == Path(__file__).resolve().parents[1] / "schemas/state-machine.json" else json.loads(Path(args.input).read_text(encoding="utf-8"))
        errors = validate_definition(definition)
        if errors:
            raise ValueError("; ".join(errors))
        artifact = {
            "schema_version": definition["schema_version"],
            "terminal_statuses": sorted(definition["terminal_statuses"]),
            "status_to_event": status_event_map(definition),
            "event_to_status": event_status_map(definition),
            "non_state_events": sorted(definition["non_state_events"]),
        }
        if args.output:
            write_json_atomic(args.output, artifact)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"STATE_ARTIFACTS_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
