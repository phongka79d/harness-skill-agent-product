"""Prove that a terminal task has no owned lease, lock, or unresolved operation."""

from __future__ import annotations

import argparse
import json
import sys

from runtime_utils import TERMINAL_STATUSES, ensure_runtime_initialized, inspect_terminal_cleanup, read_object


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    try:
        root = ensure_runtime_initialized(args.project_root)
        task_path = root / "work" / args.task_id / "task-state.json"
        result = inspect_terminal_cleanup(root, args.task_id)
        if not task_path.is_file():
            result["reasons"].append("task state is missing")
        else:
            status = str(read_object(task_path).get("status", "")).upper()
            if status not in TERMINAL_STATUSES:
                result["reasons"].append(f"task status is not terminal: {status or '<missing>'}")
        result["reasons"] = sorted(set(result["reasons"]))
        result["valid"] = not result["reasons"]
        result["classification"] = "CLEAN" if result["valid"] else "NEEDS_RECONCILIATION"
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"TERMINAL_CLEANUP_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
