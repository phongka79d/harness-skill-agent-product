"""Emit deterministic state-machine consumer data from the authoritative source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime_utils import write_json_atomic
from state_transition_registry import build_state_machine


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        definition = build_state_machine()
        json.loads(Path(args.input).read_text(encoding="utf-8"))
        artifact = definition
        if args.output:
            write_json_atomic(args.output, artifact)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"STATE_ARTIFACTS_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
