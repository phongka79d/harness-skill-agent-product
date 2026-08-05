"""Prove that a terminal task has no owned lease, lock, or unresolved operation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime_utils import TERMINAL_STATUSES, ensure_runtime_initialized, inspect_terminal_cleanup, read_object


def _delivery_cleanup_reasons(decision: dict[str, object]) -> list[str]:
    outcome = str(decision.get("outcome", "")).upper()
    cleanup = decision.get("cleanup")
    if not isinstance(cleanup, dict):
        return ["delivery decision cleanup evidence is missing"]
    requested = cleanup.get("requested") is True
    status = str(cleanup.get("status", "")).upper()
    if outcome in {"KEEP_BRANCH_AND_WORKTREE", "PUSH_AND_CREATE_PR"}:
        return [] if not requested and status == "PRESERVED" else ["delivery outcome requires preserved branch/worktree evidence"]
    if outcome == "DISCARD_BRANCH_AND_WORKTREE":
        if requested and cleanup.get("identity_proven") is True and status == "CLEANED":
            return []
        return ["discard delivery outcome has not recorded completed identity-proven cleanup"]
    if requested and status not in {"CLEANED", "PRESERVED"}:
        return ["requested delivery cleanup is not terminal"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--delivery-decision")
    args = parser.parse_args()
    try:
        root = ensure_runtime_initialized(args.project_root)
        task_path = root / "work" / args.task_id / "task-state.json"
        result = inspect_terminal_cleanup(root, args.task_id)
        decision_path = Path(args.delivery_decision) if args.delivery_decision else root / "work" / args.task_id / "delivery-decision.json"
        if decision_path.exists():
            decision = read_object(decision_path)
            if not isinstance(decision, dict) or decision.get("task_id") != args.task_id:
                result["reasons"].append("delivery decision identity is invalid")
            else:
                result["delivery_decision_id"] = decision.get("decision_id")
                result["delivery_outcome"] = decision.get("outcome")
                result["reasons"].extend(_delivery_cleanup_reasons(decision))
        elif args.delivery_decision:
            result["reasons"].append("requested delivery decision is missing")
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
