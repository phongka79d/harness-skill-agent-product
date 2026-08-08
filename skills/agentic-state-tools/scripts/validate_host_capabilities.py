"""Validate the external HOST-0 attestation used for controlled dispatch."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402

SCHEMA = HERE.parents[1] / "schemas" / "host-capabilities.schema.json"
REQUIRED_TRUE = (
    "skills_exposed",
    "core_loaded",
    "resolver_available",
    "verification_gate",
    "subagent_wait_enforced",
    "tool_isolation_attested",
)


def validate_capabilities(value: dict) -> dict:
    validate_file(value, SCHEMA, "host capabilities")
    missing = [name for name in REQUIRED_TRUE if value.get(name) is not True]
    if missing:
        raise ValueError("HOST-0 capability is missing or false: " + ", ".join(missing))
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        value = json.loads(Path(args.input).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("host capabilities must be an object")
        validate_capabilities(value)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"HOST_CAPABILITIES_REJECTED: {exc}", file=sys.stderr)
        return 1
    print("HOST_CAPABILITIES_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
