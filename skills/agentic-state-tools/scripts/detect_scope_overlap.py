"""Detect overlapping task write scopes before dispatch."""

from __future__ import annotations

import argparse
import json
import sys

from runtime_utils import read_object
from validate_planning import normalize_scope, scopes_overlap


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        tasks = read_object(args.input).get("tasks")
        if not isinstance(tasks, list):
            raise ValueError("tasks must be an array")
        overlaps: list[dict[str, str]] = []
        scopes = [(task.get("task_id"), normalize_scope(scope)) for task in tasks for scope in task.get("write_scope", [])]
        for index, (left_task, left_scope) in enumerate(scopes):
            for right_task, right_scope in scopes[index + 1:]:
                if left_task != right_task and scopes_overlap(left_scope, right_scope):
                    overlaps.append({"left_task": left_task, "left_scope": left_scope, "right_task": right_task, "right_scope": right_scope})
        overlaps.sort(key=lambda item: (str(item["left_task"]), item["left_scope"], str(item["right_task"]), item["right_scope"]))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"SCOPE_OVERLAP_FAILED: {exc}", file=sys.stderr)
        return 1
    result = {"overlaps": overlaps, "valid": not overlaps}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not overlaps else 1


if __name__ == "__main__":
    raise SystemExit(main())
