"""Internal validated writer for optional task artifacts."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from runtime_utils import (  # noqa: E402
    append_event,
    read_json,
    require_task_index_consistent,
    runtime_root,
    sanitize_for_persistence,
    task_artifact_path,
    task_state_path,
    validate_task_id,
    write_json_atomic,
)


def load_and_validate(
    input_path: str, schema_name: str, label: str
) -> dict[str, Any]:
    payload = read_json(input_path)
    validate_file(payload, HERE.parents[1] / "schemas" / schema_name, label)
    return payload


def ensure_task_binding(project_root: str, task_id: str) -> dict[str, Any]:
    root = runtime_root(project_root)
    state_path = root / "state.json"
    if not state_path.is_file():
        raise ValueError("runtime is not initialized")
    state = read_json(state_path)
    validate_file(state, HERE.parents[1] / "schemas" / "state.schema.json", "state")
    require_task_index_consistent(root, state)
    safe_id = validate_task_id(task_id)
    task_path = task_state_path(root, safe_id)
    if not task_path.is_file():
        raise ValueError(f"task is not recorded: {safe_id}")
    task = read_json(task_path)
    validate_file(task, HERE.parents[1] / "schemas" / "task-state.schema.json", f"task {safe_id}")
    if task["task_id"] != safe_id:
        raise ValueError(f"task id mismatch: {safe_id}")
    if safe_id not in state["tasks"]:
        raise ValueError(f"task is missing from runtime index: {safe_id}")
    summary = state["tasks"][safe_id]
    for field in ("status", "status_revision", "work_revision", "summary"):
        if task[field] != summary.get(field):
            raise ValueError(f"runtime task summary mismatch for {safe_id}: {field}")
    return task


def persist_artifact(
    project_root: str,
    payload: dict[str, Any],
    filename: str,
    event_type: str,
) -> dict[str, Any]:
    task_id = validate_task_id(payload.get("task_id"))
    ensure_task_binding(project_root, task_id)
    safe_payload = sanitize_for_persistence(payload)
    root = runtime_root(project_root)
    target = task_artifact_path(root, task_id, filename)
    write_json_atomic(target, safe_payload)
    append_event(
        project_root,
        event_type,
        {"task_id": task_id, "artifact": str(target.relative_to(root.resolve()))},
    )
    return safe_payload


def write_artifact(
    project_root: str,
    input_path: str,
    schema_name: str,
    filename: str,
    event_type: str,
) -> dict[str, Any]:
    payload = load_and_validate(input_path, schema_name, filename)
    return persist_artifact(project_root, payload, filename, event_type)
