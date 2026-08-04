"""Detect overlapping task write scopes before dispatch."""

from __future__ import annotations

import argparse
import json
import sys

from runtime_utils import read_object
from validate_planning import _approval_records, classify_scope_overlap, normalize_scope, scopes_overlap


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--approval-root")
    args = parser.parse_args()
    try:
        tasks = read_object(args.input).get("tasks")
        if not isinstance(tasks, list):
            raise ValueError("tasks must be an array")
        task_edges = {task.get("task_id"): list(task.get("depends_on", [])) for task in tasks}
        groups = {
            task.get("shared_write_group")
            for task in tasks
            if isinstance(task.get("shared_write_group"), str) and task.get("shared_write_group").strip()
        }
        approvals = _approval_records({}, args.approval_root, groups)
        overlaps: list[dict[str, str]] = []
        for index, left_task in enumerate(tasks):
            for right_task in tasks[index + 1:]:
                for left_scope in left_task.get("write_scope", []):
                    for right_scope in right_task.get("write_scope", []):
                        left_scope = normalize_scope(left_scope)
                        right_scope = normalize_scope(right_scope)
                        if not scopes_overlap(left_scope, right_scope):
                            continue
                        classification = classify_scope_overlap(left_task, right_task, task_edges, approvals)
                        overlaps.append({"left_task": left_task.get("task_id"), "left_scope": left_scope, "right_task": right_task.get("task_id"), "right_scope": right_scope, "classification": classification})
        overlaps.sort(key=lambda item: (str(item["left_task"]), item["left_scope"], str(item["right_task"]), item["right_scope"], item["classification"]))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"SCOPE_OVERLAP_FAILED: {exc}", file=sys.stderr)
        return 1
    invalid = {"CONFLICT", "INVALID_SHARED_WRITE_APPROVAL"}
    result = {"overlaps": overlaps, "valid": not any(item["classification"] in invalid for item in overlaps)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
