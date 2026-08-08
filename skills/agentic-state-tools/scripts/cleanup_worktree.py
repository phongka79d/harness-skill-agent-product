"""Record a worktree cleanup decision for a completed controlled task."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from validate_state import validate_runtime  # noqa: E402
from runtime_utils import (  # noqa: E402
    append_event,
    read_json,
    refresh_checklist,
    require_task_index_consistent,
    runtime_root,
    safe_child,
    task_state_path,
    utc_now,
    validate_task_id,
    write_json_atomic,
)
from worktree import WorktreeError, verify_identity  # noqa: E402

STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"
TASK_SCHEMA = HERE.parents[1] / "schemas" / "task-state.schema.json"
CLEANUP_SCHEMA = HERE.parents[1] / "schemas" / "worktree-cleanup.schema.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--outcome", choices=["REMOVED", "KEPT", "REBOUND"], required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()
    try:
        root = runtime_root(args.project_root)
        state = read_json(root / "state.json")
        validate_file(state, STATE_SCHEMA, "state")
        require_task_index_consistent(root, state)
        validate_runtime(root, state)
        task_id = validate_task_id(args.task_id)
        task_path = task_state_path(root, task_id)
        task = read_json(task_path)
        validate_file(task, TASK_SCHEMA, f"task {task_id}")
        identity = task.get("worktree_identity")
        if identity is None:
            raise ValueError("task has no bound worktree to clean up")
        if task["status"] not in {"COMPLETED", "ACCEPTED"}:
            raise ValueError("cleanup requires a completed or accepted task")
        approval = str(args.approval_reference).strip()
        if not approval or task.get("approval_reference") != approval:
            raise ValueError("approval_reference does not match the active task approval")
        summary = str(args.summary).strip()
        if not summary:
            raise ValueError("summary must be non-empty")
        verify_identity(args.project_root, identity, allow_dirty=True)
        decision = {
            "schema_version": 1,
            "task_id": task_id,
            "workflow_decision_hash": task["workflow_decision_hash"],
            "worktree": identity,
            "outcome": args.outcome,
            "approval_reference": approval,
            "summary": summary,
            "recorded_at": utc_now(),
        }
        validate_file(decision, CLEANUP_SCHEMA, "worktree cleanup decision")
        write_json_atomic(safe_child(root, "artifacts", task_id, "worktree-cleanup.json"), decision)
        append_event(
            args.project_root,
            "WORKTREE_CLEANUP_RECORDED",
            {
                "task_id": task_id,
                "outcome": decision["outcome"],
                "workflow_decision_hash": decision["workflow_decision_hash"],
            },
        )
        refresh_checklist(args.project_root)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, WorktreeError) as exc:
        print(f"CLEANUP_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
