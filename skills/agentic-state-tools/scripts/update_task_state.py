"""Create or update one task in the minimal single-active-task runtime."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from render_checklist import render_checklist  # noqa: E402
from runtime_utils import (  # noqa: E402
    append_event,
    ensure_casefold_unique_task_ids,
    normalize_scope_paths,
    read_json,
    require_task_index_consistent,
    runtime_root,
    task_state_path,
    utc_now,
    validate_task_id,
    write_json_atomic,
)

STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"
TASK_SCHEMA = HERE.parents[1] / "schemas" / "task-state.schema.json"
CALLER_FIELDS = {
    "task_id",
    "status",
    "summary",
    "scope",
    "risk_flags",
    "approval_reference",
}
VALID = {"TODO", "IN_PROGRESS", "BLOCKED", "COMPLETED", "ACCEPTED", "CANCELLED"}
OPEN = {"TODO", "IN_PROGRESS", "BLOCKED"}
ALLOWED = {
    None: {"TODO", "IN_PROGRESS", "BLOCKED"},
    "TODO": {"TODO", "IN_PROGRESS", "BLOCKED", "CANCELLED"},
    "IN_PROGRESS": {"IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"},
    "BLOCKED": {"BLOCKED", "IN_PROGRESS", "CANCELLED"},
    "COMPLETED": {"ACCEPTED", "IN_PROGRESS", "BLOCKED"},
    "ACCEPTED": set(),
    "CANCELLED": set(),
}


def _open_task_ids(tasks: dict) -> list[str]:
    return sorted(
        task_id
        for task_id, summary in tasks.items()
        if isinstance(summary, dict) and summary.get("status") in OPEN
    )


def _clean_strings(value: object, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        qualifier = "possibly empty " if allow_empty else "non-empty "
        raise ValueError(f"{field} must be a {qualifier}array of non-empty strings")
    cleaned = [item.strip() for item in value]
    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"{field} values must be unique")
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        payload = read_json(args.input)
        unknown = sorted(set(payload) - CALLER_FIELDS)
        if unknown:
            raise ValueError("unsupported or derived task fields: " + ", ".join(unknown))
        task_id = validate_task_id(payload.get("task_id"))
        status = str(payload.get("status", "")).upper()
        summary = str(payload.get("summary", "")).strip()
        scope = normalize_scope_paths(args.project_root, payload.get("scope"))
        risk_flags = _clean_strings(payload.get("risk_flags", []), "risk_flags", allow_empty=True)
        supplied_approval = payload.get("approval_reference")
        if supplied_approval is not None:
            supplied_approval = str(supplied_approval).strip() or None
        if status not in VALID or not summary:
            raise ValueError("valid status and non-empty summary are required")

        root = runtime_root(args.project_root)
        state = read_json(root / "state.json")
        validate_file(state, STATE_SCHEMA, "state")
        require_task_index_consistent(root, state)
        existing_collision = next(
            (
                existing_id
                for existing_id in state.get("tasks", {})
                if existing_id != task_id and existing_id.casefold() == task_id.casefold()
            ),
            None,
        )
        if existing_collision is not None:
            raise ValueError(
                f"task_id collides case-insensitively with existing task: {existing_collision}"
            )
        task_path = task_state_path(root, task_id)
        previous = read_json(task_path) if task_path.exists() else None
        if previous:
            validate_file(previous, TASK_SCHEMA, f"task {task_id}")
            if previous["task_id"] != task_id:
                raise ValueError(
                    f"task file ID mismatch: requested {task_id}, found {previous['task_id']}"
                )
        current_status = previous.get("status") if previous else None
        if status not in ALLOWED.get(current_status, set()):
            raise ValueError(f"transition is not allowed: {current_status or 'NEW'} -> {status}")

        work_changed = previous is None or any(
            (
                summary != previous["summary"],
                scope != previous["scope"],
                risk_flags != previous["risk_flags"],
            )
        )
        if previous and status == current_status and not work_changed:
            raise ValueError(f"task is already {status} with unchanged work metadata")
        if previous and status == current_status and status not in OPEN:
            raise ValueError("terminal task metadata cannot be changed")

        if status in OPEN or work_changed or previous is None:
            expected_risks = sorted(state["request_contract"]["risk_flags"])
            if sorted(risk_flags) != expected_risks:
                raise ValueError(
                    "task risk_flags differ from the workflow decision; resolve a new decision"
                )

        if previous:
            same_decision = previous["workflow_decision_hash"] == state["workflow_decision_hash"]
            if (status in OPEN or work_changed) and not same_decision:
                raise ValueError(
                    "task is bound to another workflow decision and cannot be reopened or changed"
                )

        other_open = [item for item in _open_task_ids(state.get("tasks", {})) if item != task_id]
        if status in OPEN and other_open:
            raise ValueError(
                "single-active-task runtime already has an open task: " + ", ".join(other_open)
            )

        approval_reference = (
            supplied_approval
            if supplied_approval is not None
            else (previous.get("approval_reference") if previous else None)
        )
        if status == "IN_PROGRESS" and state["approval"]["required"] and not approval_reference:
            raise ValueError(
                "approval_reference is required before an approval-gated task becomes IN_PROGRESS"
            )

        if previous:
            binding = {
                "workflow_decision_hash": previous["workflow_decision_hash"],
                "profile_id": previous["profile_id"],
                "profile_hash": previous["profile_hash"],
                "task_route": previous["task_route"],
                "execution_depth": previous["execution_depth"],
            }
            status_revision = int(previous["status_revision"]) + 1
            work_revision = int(previous["work_revision"]) + (1 if work_changed else 0)
        else:
            binding = {
                "workflow_decision_hash": state["workflow_decision_hash"],
                "profile_id": state["profile_id"],
                "profile_hash": state["profile_hash"],
                "task_route": state["task_route"],
                "execution_depth": state["execution_depth"],
            }
            status_revision = 1
            work_revision = 1

        task = {
            "schema_version": 3,
            "task_id": task_id,
            "status_revision": status_revision,
            "work_revision": work_revision,
            **binding,
            "approval_reference": approval_reference,
            "status": status,
            "summary": summary,
            "scope": scope,
            "risk_flags": risk_flags,
            "updated_at": utc_now(),
        }
        if previous and previous.get("worktree_identity") is not None:
            task["worktree_identity"] = previous["worktree_identity"]
        validate_file(task, TASK_SCHEMA, f"task {task_id}")
        write_json_atomic(task_path, task)

        state["revision"] = int(state["revision"]) + 1
        state.setdefault("tasks", {})[task_id] = {
            "status": status,
            "status_revision": task["status_revision"],
            "work_revision": task["work_revision"],
            "summary": summary,
        }
        open_ids = _open_task_ids(state["tasks"])
        if len(open_ids) > 1:
            raise ValueError("state contains more than one open task")
        state["active_task_id"] = open_ids[0] if open_ids else None
        state["status"] = "ACTIVE" if open_ids else "IDLE"
        state["updated_at"] = utc_now()
        validate_file(state, STATE_SCHEMA, "state")
        ensure_casefold_unique_task_ids(list(state["tasks"]), "state task IDs")
        require_task_index_consistent(root, state)
        write_json_atomic(root / "state.json", state)
        append_event(
            args.project_root,
            "TASK_UPDATED",
            {
                "task_id": task_id,
                "status": status,
                "status_revision": task["status_revision"],
                "work_revision": task["work_revision"],
                "workflow_decision_hash": task["workflow_decision_hash"],
            },
        )
        try:
            render_checklist(args.project_root, task_id=task_id)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            print(f"CHECKLIST_WARNING: {exc}", file=sys.stderr)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"TASK_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
