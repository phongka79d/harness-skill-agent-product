"""Prepare and bind one controlled task to a deterministic Git worktree."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

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
    task_state_path,
    validate_task_id,
    utc_now,
    write_json_atomic,
)
from worktree import (  # noqa: E402
    WorktreeError,
    prepare_identity,
    verify_identity,
    worktree_base_dir,
)

STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"
TASK_SCHEMA = HERE.parents[1] / "schemas" / "task-state.schema.json"
DECISION_SCHEMA = HERE.parents[1] / "schemas" / "workflow-decision.schema.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--decision")
    args = parser.parse_args()
    try:
        root = runtime_root(args.project_root)
        state = read_json(root / "state.json")
        validate_file(state, STATE_SCHEMA, "state")
        require_task_index_consistent(root, state)
        validate_runtime(root, state)
        contract = state.get("worktree")
        if state.get("execution_depth") != "controlled" or not isinstance(contract, dict) or not contract.get("required"):
            raise ValueError("worktree preparation requires a controlled runtime")
        task_id = validate_task_id(args.task_id or state.get("active_task_id"))
        if state.get("active_task_id") != task_id:
            raise ValueError("task must be the active runtime task")
        task_path = task_state_path(root, task_id)
        task = read_json(task_path)
        validate_file(task, TASK_SCHEMA, f"task {task_id}")
        if task["status"] != "IN_PROGRESS":
            raise ValueError("worktree preparation requires an IN_PROGRESS task")
        approval = str(args.approval_reference).strip()
        if not approval or task.get("approval_reference") != approval:
            raise ValueError("approval_reference does not match the active task approval")
        if contract.get("prepare_approval_required") and not approval:
            raise ValueError("approval_reference is required before worktree preparation")
        if args.decision:
            decision = read_json(args.decision)
            validate_file(decision, DECISION_SCHEMA, "workflow decision")
            if decision.get("decision_hash") != state.get("workflow_decision_hash"):
                raise ValueError("decision does not match the initialized runtime")
            if decision.get("worktree") != contract:
                raise ValueError("decision worktree contract does not match runtime")
        if state.get("worktree_identity") is not None or task.get("worktree_identity") is not None:
            if state.get("worktree_identity") != task.get("worktree_identity"):
                raise WorktreeError("runtime and task worktree identities disagree", "INSPECT_WORKTREE_IDENTITY")
            verify_identity(args.project_root, state["worktree_identity"], allow_dirty=True)
            raise ValueError("task already has a bound worktree")
        if not contract.get("enabled"):
            raise ValueError("worktree contract is disabled")
        # The parent is deterministic and exact; Git itself creates only the target.
        parent = worktree_base_dir(args.project_root)
        if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
            raise ValueError("worktree parent is not a real directory")
        parent.mkdir(parents=True, exist_ok=True)
        identity = prepare_identity(args.project_root, task_id, state["workflow_decision_hash"])
        validate_file(identity, HERE.parents[1] / "schemas" / "worktree.schema.json", "worktree identity")
        task["worktree_identity"] = identity
        task["updated_at"] = utc_now()
        state["worktree_identity"] = identity
        state["revision"] = int(state["revision"]) + 1
        state["updated_at"] = utc_now()
        validate_file(task, TASK_SCHEMA, f"task {task_id}")
        validate_file(state, STATE_SCHEMA, "state")
        write_json_atomic(task_path, task)
        write_json_atomic(root / "state.json", state)
        append_event(args.project_root, "WORKTREE_PREPARED", {"task_id": task_id, "path": identity["path"], "branch": identity["branch"]})
        refresh_checklist(args.project_root)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, WorktreeError) as exc:
        print(f"WORKTREE_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(identity, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
