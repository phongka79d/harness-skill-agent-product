"""Persist one decision-bound integrated review for an explicit task set."""
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
    append_event,
    read_json,
    refresh_checklist,
    require_scope_coverage,
    bound_worktree_identity,
    require_task_index_consistent,
    runtime_root,
    safe_child,
    sanitize_for_persistence,
    task_state_path,
    utc_now,
    validate_task_id,
    write_json_atomic,
    verify_workspace_snapshot,
)
from review_validation import (  # noqa: E402
    validate_review_contract,
    validate_review_outcome,
)

STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"
TASK_SCHEMA = HERE.parents[1] / "schemas" / "task-state.schema.json"
BATCH_SCHEMA = HERE.parents[1] / "schemas" / "batch-review.schema.json"
CALLER_FIELDS = {
    "schema_version",
    "task_ids",
    "review_mode",
    "review_rubric_id",
    "review_rubric_version",
    "criteria",
    "outcome",
    "summary",
    "findings",
    "workspace",
    "workspace_summary",
}
REVIEWABLE = {"IN_PROGRESS", "COMPLETED", "ACCEPTED"}


def _load_tasks(root: Path, state: dict, task_ids: object) -> list[dict]:
    if not isinstance(task_ids, list) or not task_ids:
        raise ValueError("task_ids must be a non-empty array")
    normalized = [validate_task_id(task_id) for task_id in task_ids]
    if len(normalized) != len(set(normalized)):
        raise ValueError("task_ids must be unique")
    tasks: list[dict] = []
    for task_id in sorted(normalized):
        if task_id not in state["tasks"]:
            raise ValueError(f"task is missing from runtime index: {task_id}")
        path = task_state_path(root, task_id)
        if not path.is_file():
            raise ValueError(f"task state is missing: {task_id}")
        task = read_json(path)
        validate_file(task, TASK_SCHEMA, f"task {task_id}")
        if task["task_id"] != task_id:
            raise ValueError(f"task id mismatch: {task_id}")
        if task["status"] not in REVIEWABLE:
            raise ValueError(
                f"task is not reviewable; expected IN_PROGRESS, COMPLETED, or ACCEPTED: {task_id}"
            )
        summary = state["tasks"][task_id]
        for field in ("status", "status_revision", "work_revision", "summary"):
            if task[field] != summary.get(field):
                raise ValueError(f"runtime task summary mismatch for {task_id}: {field}")
        tasks.append(task)
    return tasks


def _bindings(tasks: list[dict]) -> list[dict]:
    return [
        {
            "task_id": task["task_id"],
            "work_revision": task["work_revision"],
            "task_workflow_decision_hash": task["workflow_decision_hash"],
        }
        for task in tasks
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        supplied = read_json(args.input)
        unknown = sorted(set(supplied) - CALLER_FIELDS)
        if unknown:
            raise ValueError(
                "caller must not supply derived batch-review fields: " + ", ".join(unknown)
            )
        root = runtime_root(args.project_root)
        state = read_json(root / "state.json")
        validate_file(state, STATE_SCHEMA, "state")
        require_task_index_consistent(root, state)
        tasks = _load_tasks(root, state, supplied.get("task_ids"))
        first_task_id = tasks[0]["task_id"]
        verified_files = verify_workspace_snapshot(args.project_root, supplied.get("workspace"), first_task_id)
        for task in tasks:
            require_scope_coverage(args.project_root, task, verified_files)
        result = {
            "schema_version": 3,
            "workflow_decision_hash": state["workflow_decision_hash"],
            "tasks": _bindings(tasks),
            "review_mode": str(supplied.get("review_mode", "")).strip(),
            "review_rubric_id": supplied.get("review_rubric_id"),
            "review_rubric_version": supplied.get("review_rubric_version"),
            "criteria": supplied.get("criteria"),
            "outcome": str(supplied.get("outcome", "")).strip().upper(),
            "summary": str(supplied.get("summary", "")).strip(),
            "findings": supplied.get("findings", []),
            "workspace": {"files": verified_files},
            "workspace_summary": str(supplied.get("workspace_summary", "")).strip(),
            "recorded_at": utc_now(),
        }
        identity = bound_worktree_identity(args.project_root, first_task_id)
        if identity is not None:
            result["workspace"]["worktree"] = identity
        result = sanitize_for_persistence(result)
        validate_review_outcome(result["outcome"], result["findings"])
        validate_review_contract(result, "integration")
        validate_file(result, BATCH_SCHEMA, "batch review")
        write_json_atomic(safe_child(root, "batch-review.json"), result)
        append_event(
            args.project_root,
            "BATCH_REVIEW_WRITTEN",
            {
                "workflow_decision_hash": result["workflow_decision_hash"],
                "task_ids": [item["task_id"] for item in result["tasks"]],
                "outcome": result["outcome"],
            },
        )
        refresh_checklist(args.project_root)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"ARTIFACT_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
