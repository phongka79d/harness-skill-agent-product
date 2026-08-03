"""Apply an approved change as a new immutable versioned plan artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime_utils import read_object, read_payload, utc_now, write_json_atomic
from validate_change_request import validate_change_request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        request = read_payload(args.request)
        approval = read_object(args.approval)
        record = validate_change_request(request, approval, applying=True)
        target_path = Path(args.target).resolve()
        output_path = Path(args.output).resolve()
        if target_path == output_path:
            raise ValueError("historical target and new plan output must be different files")
        target = read_object(target_path)
        if target.get("plan_id") != record["target_id"] or str(target.get("version")) != record["target_version"]:
            raise ValueError("target plan does not match change request target and version")
        new_plan = dict(target)
        new_plan["version"] = record["new_version"]
        new_plan["supersedes_id"] = record["supersedes_id"]
        new_plan["change_request_id"] = record["change_request_id"]
        new_plan["change_status"] = "APPLIED"
        new_plan["applied_at"] = utc_now()
        new_plan["requested_changes"] = list(record["requested_changes"])
        if isinstance(new_plan.get("revision"), int) and not isinstance(new_plan["revision"], bool):
            new_plan["revision"] += 1
        write_json_atomic(output_path, new_plan)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"CHANGE_APPLY_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(new_plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
