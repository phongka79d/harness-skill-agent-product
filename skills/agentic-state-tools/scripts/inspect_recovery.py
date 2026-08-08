"""Classify validated runtime state after interruption; never retry a side effect."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from runtime_utils import (  # noqa: E402
    read_json,
    resolve_workspace_context,
    runtime_root,
    task_index_diff,
    task_state_path,
)
from validate_state import validate_runtime  # noqa: E402
from worktree import WorktreeError  # noqa: E402

STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"
TASK_SCHEMA = HERE.parents[1] / "schemas" / "task-state.schema.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()
    try:
        root = runtime_root(args.project_root)
        state = read_json(root / "state.json")
        validate_file(state, STATE_SCHEMA, "state")
        try:
            index_issues = task_index_diff(root, state)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            result = {
                "status": "RECOVERY_REQUIRED",
                "active_task": None,
                "next_action": "RECONCILE_TASK_INDEX",
                "index_issues": {"missing_files": [], "orphan_files": []},
                "reason": str(exc),
                "rule": "inspect task files and state index; never delete or retry automatically",
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if index_issues["missing_files"] or index_issues["orphan_files"]:
            result = {
                "status": "RECOVERY_REQUIRED",
                "active_task": None,
                "next_action": "RECONCILE_TASK_INDEX",
                "index_issues": index_issues,
                "rule": "inspect task files and state index; never delete or retry automatically",
            }
        else:
            try:
                validate_runtime(root, state)
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                result = {
                    "status": "RECOVERY_REQUIRED",
                    "active_task": None,
                    "next_action": "RECONCILE_RUNTIME_STATE",
                    "index_issues": index_issues,
                    "reason": str(exc),
                    "rule": "reconcile runtime invariants before inspecting workspace or retrying",
                }
            else:
                active = state["active_task_id"]
                if active:
                    task = read_json(task_state_path(root, active))
                    validate_file(task, TASK_SCHEMA, f"task {active}")
                    if task["task_id"] != active:
                        raise ValueError("active task id does not match its task artifact")
                    action = (
                        "INSPECT_WORKSPACE"
                        if task["status"] in {"TODO", "IN_PROGRESS", "BLOCKED"}
                        else "NO_ACTION"
                    )
                    reason = None
                    contract = state.get("worktree", {})
                    if contract.get("required") and task["status"] in {"TODO", "IN_PROGRESS", "BLOCKED"}:
                        if task.get("worktree_identity") is None:
                            action = "PREPARE_WORKTREE"
                            reason = "controlled task has no bound worktree"
                        else:
                            try:
                                resolve_workspace_context(
                                    args.project_root,
                                    task_id=active,
                                    allow_dirty=False,
                                )
                            except WorktreeError as exc:
                                action = exc.action
                                reason = str(exc)
                else:
                    task = None
                    action = "NO_ACTION"
                    reason = None
                result = {
                    "status": "RECOVERY_REQUIRED" if action != "NO_ACTION" else "CLEAN",
                    "active_task": task,
                    "next_action": action,
                    "index_issues": index_issues,
                    "rule": "inspect actual workspace and provider outcome before any retry",
                }
                if reason:
                    result["reason"] = reason
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"RECOVERY_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
