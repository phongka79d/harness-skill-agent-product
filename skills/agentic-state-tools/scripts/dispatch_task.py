"""Validate and record a dispatch decision without spawning an agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime_utils import read_payload, write_json_atomic
from dispatch_contract import validate_dispatch_schema

CONFIG_SKILL = Path(__file__).resolve().parents[2] / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))

from load_config import load_config, validate_dispatch_selection  # noqa: E402


def normalize_dispatch(value: object, config: dict[str, object]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("dispatch must be an object")
    validate_dispatch_schema(value)
    result = dict(value)
    for field in ("dispatch_id", "task_id", "agent_role", "selected_owner", "selected_model"):
        if not isinstance(result.get(field), str) or not str(result[field]).strip():
            raise ValueError(f"dispatch.{field} must be a non-empty string")
    validate_dispatch_selection(result, config)
    mode = str(result.get("selected_mode", "")).upper()
    if mode not in {"ASYNC", "SYNC"}:
        raise ValueError("dispatch.selected_mode must be ASYNC or SYNC")
    result["selected_mode"] = mode
    if not isinstance(result.get("input_revisions"), dict):
        raise ValueError("dispatch.input_revisions must be an object")
    if not isinstance(result.get("approval_references"), list) or any(not isinstance(item, str) for item in result["approval_references"]):
        raise ValueError("dispatch.approval_references must be an array of strings")
    if not isinstance(result.get("evidence"), dict):
        raise ValueError("dispatch.evidence must be an object")
    architecture_owner = result["evidence"].get("architecture_owner")
    if architecture_owner is not None and architecture_owner != result["selected_owner"]:
        raise ValueError("dispatch cannot change architecture ownership")
    result["status"] = "RECORDED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        result = normalize_dispatch(read_payload(args.input), load_config())
        if args.output:
            write_json_atomic(args.output, result)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"DISPATCH_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
