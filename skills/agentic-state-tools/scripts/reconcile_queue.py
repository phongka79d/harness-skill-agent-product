"""Reconcile queue entries with task, dispatch, dependency, and lock evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runtime_utils import read_object, task_dependencies, task_write_scopes
from task_state_contract import EXECUTION_IDENTITY_FIELDS
from dispatch_contract import validate_dispatch_schema

CONFIG_SKILL = Path(__file__).resolve().parents[2] / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))

from load_config import load_config, load_deployment_config, validate_config, validate_dispatch_selection  # noqa: E402


def _as_records(value: Any, field: str) -> tuple[list[dict[str, Any]], list[str]]:
    if value is None:
        return [], []
    if isinstance(value, list):
        records: list[dict[str, Any]] = []
        errors: list[str] = []
        for index, item in enumerate(value):
            if isinstance(item, dict):
                records.append(item)
            else:
                errors.append(f"INVALID_QUEUE_COLLECTION:{field}:{index}")
        return records, errors
    if isinstance(value, dict):
        records = []
        errors = []
        for key, item in value.items():
            if isinstance(item, dict):
                records.append(item)
            else:
                errors.append(f"INVALID_QUEUE_COLLECTION:{field}:{key}")
        return records, errors
    return [], [f"INVALID_QUEUE_COLLECTION:{field}"]


def reconcile_queue(
    queue: dict[str, Any],
    config: dict[str, Any] | None = None,
    deployment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contradictions: set[str] = set()
    if not isinstance(queue, dict):
        raise ValueError("queue must be an object")
    if not isinstance(queue.get("queue_id"), str) or not queue["queue_id"].strip():
        contradictions.add("MISSING_QUEUE_FIELD:queue_id")
    revision = queue.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        contradictions.add("MISSING_QUEUE_FIELD:revision")
    for field in ("tasks", "task_states", "dispatches", "locks"):
        if field not in queue:
            contradictions.add(f"MISSING_QUEUE_FIELD:{field}")
    tasks, errors = _as_records(queue.get("tasks"), "tasks")
    contradictions.update(errors)
    task_state_records, errors = _as_records(queue.get("task_states"), "task_states")
    contradictions.update(errors)
    task_states = {item.get("task_id"): item for item in task_state_records if isinstance(item.get("task_id"), str)}
    dispatch_records, errors = _as_records(queue.get("dispatches"), "dispatches")
    contradictions.update(errors)
    dispatches = {
        item.get("task_id"): item
        for item in dispatch_records
        if isinstance(item.get("task_id"), str) and item.get("task_id")
    }
    locks, errors = _as_records(queue.get("locks"), "locks")
    contradictions.update(errors)
    seen: set[str] = set()
    accepted = {item for item in queue.get("accepted_task_ids", []) if isinstance(item, str)}
    accepted.update(task_id for task_id, state in task_states.items() if str(state.get("status", "")).upper() == "ACCEPTED")
    configured = load_config() if config is None else validate_config(config)
    resolved_deployment = deployment
    if dispatch_records and resolved_deployment is None:
        try:
            resolved_deployment = load_deployment_config(config=configured)
        except ValueError as exc:
            contradictions.add(f"INVALID_DEPLOYMENT_CONFIG:{exc}")
            resolved_deployment = {}
    for index, dispatch in enumerate(dispatch_records):
        task_id = dispatch.get("task_id") if isinstance(dispatch.get("task_id"), str) and dispatch.get("task_id") else None
        dispatch_id = dispatch.get("dispatch_id") if isinstance(dispatch.get("dispatch_id"), str) and dispatch.get("dispatch_id") else None
        identity = task_id or dispatch_id or f"index-{index}"
        try:
            validate_dispatch_schema(dispatch)
            validate_dispatch_selection(dispatch, configured, resolved_deployment)
        except (TypeError, ValueError) as exc:
            contradictions.add(f"INVALID_DISPATCH:{identity}:{exc}")
    for task in tasks:
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            contradictions.add("INVALID_QUEUE_TASK_ID")
            continue
        if task_id in seen:
            contradictions.add(f"DUPLICATE_QUEUE_TASK:{task_id}")
        seen.add(task_id)
        state = task_states.get(task_id)
        if state is not None and state.get("revision") != task.get("revision"):
            contradictions.add(f"TASK_STATE_MISMATCH:{task_id}")
        dispatch = dispatches.get(task_id)
        for field in EXECUTION_IDENTITY_FIELDS:
            values = [record.get(field) for record in (task, state, dispatch) if record is not None]
            if values and any(value != values[0] for value in values[1:]):
                contradictions.add(f"IDENTITY_MISMATCH:{task_id}:{field}")
        queue_state = str(task.get("queue_state", task.get("status", ""))).upper()
        if queue_state in {"DISPATCHED", "RUNNING"} and task_id not in dispatches:
            contradictions.add(f"MISSING_DISPATCH:{task_id}")
        for dependency in task_dependencies(task):
            if dependency not in accepted:
                contradictions.add(f"UNACCEPTED_DEPENDENCY:{task_id}:{dependency}")
        scopes = task_write_scopes(task)
        if scopes and any(lock.get("key") in scopes and lock.get("task_id") != task_id for lock in locks):
            contradictions.add(f"SCOPE_LOCK_CONFLICT:{task_id}")
    return {
        "queue_id": queue.get("queue_id"),
        "revision": queue.get("revision"),
        "checked_task_ids": sorted(seen),
        "contradictions": sorted(contradictions),
        "valid": not contradictions,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--deployment")
    args = parser.parse_args()
    try:
        config = load_config()
        deployment = load_deployment_config(args.deployment, config)
        print(json.dumps(reconcile_queue(read_object(args.input), config, deployment), indent=2))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"QUEUE_RECONCILIATION_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
