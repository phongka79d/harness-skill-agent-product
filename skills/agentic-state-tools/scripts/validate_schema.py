"""Validate a JSON object against a bundled schema."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()
    try:
        value = json.loads(Path(args.input).read_text(encoding="utf-8"))
        validate_file(value, args.schema, "payload")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PAYLOAD_REJECTED: {exc}", file=sys.stderr)
        return 1
    print("PAYLOAD_VALID")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
