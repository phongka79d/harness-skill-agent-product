"""Validate runtime, task references, bindings, paths, and active-task invariants."""
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
    require_task_index_consistent,
    runtime_root,
    task_state_path,
    validate_task_id,
)

OPEN = {"TODO", "IN_PROGRESS", "BLOCKED"}
STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"
TASK_SCHEMA = HERE.parents[1] / "schemas" / "task-state.schema.json"


def validate_runtime(root: Path, state: dict) -> None:
    require_task_index_consistent(root, state)

    open_ids: list[str] = []
    tasks = state.get("tasks", {})
    if not isinstance(tasks, dict):
        raise ValueError("state.tasks must be an object")
    for raw_task_id, summary in tasks.items():
        task_id = validate_task_id(raw_task_id)
        if not isinstance(summary, dict):
            raise ValueError(f"state summary must be an object: {task_id}")
        task_path = task_state_path(root, task_id)
        task = read_json(task_path)
        validate_file(task, TASK_SCHEMA, f"task {task_id}")
        if task["task_id"] != task_id:
            raise ValueError(f"task id mismatch for {task_id}")
        if (
            task["status_revision"] != summary.get("status_revision")
            or task["work_revision"] != summary.get("work_revision")
            or task["status"] != summary.get("status")
            or task["summary"] != summary.get("summary")
        ):
            raise ValueError(f"state summary mismatch for {task_id}")
        if task["status"] in OPEN:
            open_ids.append(task_id)
            if task["workflow_decision_hash"] != state["workflow_decision_hash"]:
                raise ValueError(
                    f"open task {task_id} is bound to another workflow decision"
                )
            if task["profile_hash"] != state["profile_hash"]:
                raise ValueError(f"open task {task_id} profile binding mismatch")

    if len(open_ids) > 1:
        raise ValueError("single-active-task runtime has more than one open task")
    expected_active = open_ids[0] if open_ids else None
    if state.get("active_task_id") != expected_active:
        raise ValueError(f"active_task_id mismatch; expected {expected_active!r}")
    expected_status = "ACTIVE" if open_ids else "IDLE"
    if state.get("status") != expected_status:
        raise ValueError(f"runtime status mismatch; expected {expected_status}")

    worktree = state.get("worktree", {})
    state_identity = state.get("worktree_identity")
    if isinstance(worktree, dict) and worktree.get("required"):
        if open_ids:
            active_task = read_json(task_state_path(root, open_ids[0]))
            if state_identity is None and active_task.get("worktree_identity") is None:
                pass
            elif state_identity is None or active_task.get("worktree_identity") != state_identity:
                raise ValueError("runtime and active task worktree identities disagree")
        elif state_identity is not None:
            bound_tasks = [
                read_json(task_state_path(root, task_id)).get("worktree_identity")
                for task_id in tasks
            ]
            if state_identity not in bound_tasks:
                raise ValueError("runtime worktree identity is not bound to a recorded task")
    elif state_identity is not None:
        raise ValueError("disabled worktree runtime must not retain a runtime identity")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()
    try:
        root = runtime_root(args.project_root)
        state = read_json(root / "state.json")
        validate_file(state, STATE_SCHEMA, "state")
        validate_runtime(root, state)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"STATE_REJECTED: {exc}", file=sys.stderr)
        return 1
    print("STATE_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
