"""Select runnable tasks from a dependency-aware queue snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from resolve_execution_mode import resolve_execution_mode
from validate_planning import normalize_scope, scopes_overlap
from runtime_utils import read_object, task_dependencies, task_write_scopes


RUNNABLE_STATUSES = {"READY", "QUEUED", "QUEUED_ASYNC", "QUEUED_SYNC"}


def resolve_tasks(queue: dict[str, Any]) -> dict[str, Any]:
    tasks = queue.get("tasks")
    if not isinstance(tasks, list) or any(not isinstance(task, dict) for task in tasks):
        raise ValueError("tasks must be an array of objects")
    active_scopes = [normalize_scope(scope) for scope in queue.get("active_write_scopes", []) if isinstance(scope, str) and scope.strip()]
    accepted = {task.get("task_id") for task in tasks if str(task.get("status", "")).upper() == "ACCEPTED"}
    accepted.update(item for item in queue.get("accepted_task_ids", []) if isinstance(item, str))
    runnable: list[dict[str, Any]] = []
    blocked: dict[str, str] = {}
    conflicted: dict[str, str] = {}
    for task in tasks:
        task_id = task.get("task_id")
        status = str(task.get("status", task.get("queue_state", ""))).upper()
        if not isinstance(task_id, str) or status not in RUNNABLE_STATUSES:
            continue
        missing = [dependency for dependency in task_dependencies(task) if dependency not in accepted]
        if missing:
            blocked[task_id] = f"DEPENDENCY_NOT_ACCEPTED:{','.join(missing)}"
            continue
        task_scopes = [normalize_scope(scope) for scope in task_write_scopes(task) if scope.strip()]
        conflicts = [scope for scope in task_scopes for active in active_scopes if scopes_overlap(scope, active)]
        if conflicts:
            conflicted[task_id] = f"SCOPE_CONFLICT:{','.join(sorted(set(conflicts)))}"
            continue
        runnable.append({
            "task_id": task_id,
            "execution_mode": resolve_execution_mode(task),
            "status": status,
            "depends_on": task_dependencies(task),
        })
    runnable.sort(key=lambda item: item["task_id"])
    return {
        "runnable": runnable,
        "blocked_task_ids": sorted(blocked),
        "conflicted_task_ids": sorted(conflicted),
        "reasons": {**{key: value for key, value in blocked.items()}, **{key: value for key, value in conflicted.items()}},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        result = resolve_tasks(read_object(args.input))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"RUNNABLE_TASKS_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
