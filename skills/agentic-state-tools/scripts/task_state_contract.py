"""Shared task-state identity and merge rules."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


IMMUTABLE_FIELDS = frozenset({
    "task_id", "plan_id", "plan_revision", "batch_id", "requirement_ids",
    "depends_on", "read_scope", "write_scope", "review_contract", "run_id",
    "attempt_id", "dispatch_id", "worktree_path", "branch_name",
    "input_artifact_hashes",
})
MUTABLE_FIELDS = frozenset({
    "status", "progress", "checkpoint", "error", "blocker", "result_summary",
    "output_artifact_hashes", "review_verdict", "updated_at", "revision",
    "previous_revision",
})
EXECUTION_IDENTITY_FIELDS = ("run_id", "attempt_id", "dispatch_id")


def merge_task_state(current: dict[str, object] | None, update: dict[str, object]) -> dict[str, object]:
    """Return a full next state while rejecting identity changes."""

    if not isinstance(update, dict):
        raise ValueError("task-state update must be an object")
    if current is None:
        return deepcopy(update)
    if not isinstance(current, dict):
        raise ValueError("current task state must be an object")

    next_state = deepcopy(current)
    for field in IMMUTABLE_FIELDS:
        if field in update:
            if field not in current or current[field] != update[field]:
                raise ValueError(f"immutable task-state field changed or newly introduced: {field}")
    for field in MUTABLE_FIELDS:
        if field in update:
            next_state[field] = deepcopy(update[field])
    return next_state


def _identity_records(queue: dict[str, object], task_id: object) -> list[dict[str, Any]]:
    if not isinstance(queue, dict):
        return []
    if any(field in queue for field in EXECUTION_IDENTITY_FIELDS):
        return [queue]
    records: list[dict[str, Any]] = []
    for collection_name in ("tasks", "task_states", "dispatches"):
        collection = queue.get(collection_name)
        if not isinstance(collection, list):
            continue
        for record in collection:
            if isinstance(record, dict) and record.get("task_id") == task_id:
                records.append(record)
    return records


def _validate_record_identity(state: dict[str, object], record: dict[str, Any], source: str, *, require_fields: bool = True) -> None:
    if "task_id" in record and record.get("task_id") != state.get("task_id"):
        raise ValueError(f"{source} task_id does not match task state")
    for field in EXECUTION_IDENTITY_FIELDS:
        if field in state and (field in record or require_fields) and state.get(field) != record.get(field):
            raise ValueError(f"{source} {field} does not match task state")


def validate_execution_identity(state: dict[str, object], lease: dict[str, object] | None, queue: dict[str, object] | None) -> None:
    """Reject a state whose run, attempt, or dispatch binding disagrees with durable evidence."""

    if not isinstance(state, dict):
        raise ValueError("task state must be an object")
    if lease is not None:
        _validate_record_identity(state, lease, "lease", require_fields=False)
    if queue is not None:
        for record in _identity_records(queue, state.get("task_id")):
            _validate_record_identity(state, record, "queue")
