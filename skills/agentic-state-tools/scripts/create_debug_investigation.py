"""Validate and persist a task-bound debugging investigation artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from append_event import append_event_for_root
from capture_workspace import capture_workspace
from render_checklist import render_checklist_for_root
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    apply_event,
    empty_state,
    iter_events,
    next_revision,
    next_event_id,
    parse_timestamp,
    read_object,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
    validate_event,
    validate_event_preconditions,
)
from validate_payload import validate
from write_artifact import write_validated


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/debug-investigation.schema.json"


class InvestigationBindingBlockedError(ValueError):
    """Raised when runtime state cannot provide the required task binding."""


def _workspace_evidence_hash(root: Path) -> str:
    snapshot = capture_workspace(root.parent)
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _timestamp_max(first: str, second: str) -> str:
    return first if parse_timestamp(first) >= parse_timestamp(second) else second


def _validate_domain(record: dict[str, Any], current_revision: int) -> None:
    hypotheses = record.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ValueError("debug investigation hypotheses must be an array")
    hypothesis_ids: list[str] = []
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, dict) or not isinstance(hypothesis.get("hypothesis_id"), str):
            raise ValueError("every hypothesis must have a string hypothesis_id")
        hypothesis_id = hypothesis["hypothesis_id"]
        if hypothesis_id in hypothesis_ids:
            raise ValueError(f"duplicate hypothesis_id: {hypothesis_id}")
        hypothesis_ids.append(hypothesis_id)

    current_hypothesis = record.get("current_hypothesis")
    if current_hypothesis is not None and current_hypothesis not in hypothesis_ids:
        raise ValueError("current_hypothesis must name an existing hypothesis")

    status = record.get("status")
    confirmed = any(item.get("outcome") == "CONFIRMED" for item in hypotheses if isinstance(item, dict))
    root_cause = record.get("root_cause")
    has_root_cause = isinstance(root_cause, str) and bool(root_cause.strip())
    if status in {"ROOT_CAUSE_CONFIRMED", "COMPLETED"} and (not has_root_cause or not confirmed):
        raise ValueError(f"{status} requires a non-empty root_cause and a confirmed hypothesis")

    regression = record.get("regression_check")
    if not isinstance(regression, dict):
        raise ValueError("regression_check must be an object")
    if status == "COMPLETED" and (regression.get("status") != "PASS" or regression.get("exit_code") != 0):
        raise ValueError("COMPLETED requires a passing regression_check with exit_code 0")
    if status in {"BLOCKED", "ESCALATED"} and not has_root_cause and regression.get("status") == "PASS" and regression.get("exit_code") == 0:
        raise ValueError(f"{status} cannot carry a successful regression_check without a root cause")

    fix_attempt_count = record.get("fix_attempt_count")
    if isinstance(fix_attempt_count, bool) or not isinstance(fix_attempt_count, int) or fix_attempt_count > 3:
        raise ValueError("fix_attempt_count must not exceed 3")

    if record.get("revision") != current_revision + 1:
        raise ValueError("investigation revision must advance exactly one revision")
    created_at = parse_timestamp(record["created_at"])
    updated_at = parse_timestamp(record["updated_at"])
    if updated_at < created_at:
        raise ValueError("updated_at cannot be earlier than created_at")


def _prepare_record(
    payload: dict[str, Any],
    task: dict[str, Any],
    existing: dict[str, Any] | None,
    root: Path,
) -> dict[str, Any]:
    current_task_revision = task.get("revision")
    if isinstance(current_task_revision, bool) or not isinstance(current_task_revision, int) or current_task_revision < 1:
        raise InvestigationBindingBlockedError("task state has no valid revision binding")
    task_status = str(task.get("status", "")).upper()
    if existing is None and task_status != "REPAIR_REQUIRED":
        raise ValueError("debug investigation requires a REPAIR_REQUIRED task")
    expected_task_revision = current_task_revision + 1 if task_status == "REPAIR_REQUIRED" else current_task_revision
    if existing is not None:
        existing_task_revision = existing.get("task_revision")
        if isinstance(existing_task_revision, bool) or not isinstance(existing_task_revision, int) or existing_task_revision < 1:
            raise ValueError("existing investigation task_revision is invalid")
        if existing_task_revision > expected_task_revision:
            raise ValueError("existing investigation task_revision is newer than the current task")
        if task_status == "REPAIR_REQUIRED" and existing_task_revision != expected_task_revision:
            raise ValueError("existing investigation task_revision does not match the planned dispatch revision")
    supplied_task_revision = payload.get("task_revision", expected_task_revision)
    if supplied_task_revision != expected_task_revision:
        raise ValueError("investigation.task_revision does not match the current task binding")
    payload["task_revision"] = expected_task_revision

    for field in ("run_id", "attempt_id"):
        current_value = task.get(field)
        if not isinstance(current_value, str) or not current_value.strip():
            raise InvestigationBindingBlockedError(f"task state is missing {field}")
        supplied_value = payload.get(field, current_value)
        if supplied_value != current_value:
            raise ValueError(f"investigation.{field} does not match task state")
        payload[field] = current_value

    previous_revision = existing.get("revision", 0) if existing is not None else 0
    if isinstance(previous_revision, bool) or not isinstance(previous_revision, int) or previous_revision < 0:
        raise ValueError("existing investigation revision is invalid")
    supplied_revision = payload.get("revision")
    if supplied_revision is not None and supplied_revision != previous_revision + 1:
        raise ValueError("investigation revision is stale or mismatched")
    expected_revision = payload.pop("expected_revision", previous_revision)
    if expected_revision != previous_revision:
        raise ValueError(f"stale revision: expected {expected_revision}, current {previous_revision}")

    if existing is not None:
        for field in ("investigation_id", "task_id", "run_id", "attempt_id"):
            if field in payload and payload[field] != existing.get(field):
                raise ValueError(f"investigation {field} cannot change across revisions")
        payload["investigation_id"] = existing["investigation_id"]
        payload["created_at"] = existing["created_at"]
    else:
        investigation_id = payload.get("investigation_id") or f"DBG-{task['task_id']}-{uuid.uuid4().hex[:12].upper()}"
        payload["investigation_id"] = investigation_id
        payload.setdefault("created_at", utc_now())

    created_at = payload.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        raise ValueError("investigation.created_at must be a non-empty timestamp")
    parse_timestamp(created_at)
    requested_updated_at = payload.get("updated_at")
    if requested_updated_at is not None:
        parse_timestamp(requested_updated_at)
    now = utc_now()
    payload["updated_at"] = _timestamp_max(requested_updated_at or now, created_at)
    payload["revision"] = next_revision(payload, previous_revision)
    payload["previous_revision"] = previous_revision if previous_revision else None
    regression = payload.get("regression_check")
    if isinstance(regression, dict) and regression.get("status") == "PASS" and regression.get("exit_code") == 0:
        regression["workspace_hash"] = _workspace_evidence_hash(root)
    _validate_domain(payload, previous_revision)
    errors = validate(payload, read_object(SCHEMA), base_path=SCHEMA.resolve().parent)
    if errors:
        raise ValueError("debug investigation schema validation failed: " + "; ".join(errors))
    return payload


def _prepare_event(root: Path, record: dict[str, Any], actor: str) -> dict[str, Any]:
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor must be a non-empty string")
    events = iter_events(root / "runtime" / "events.jsonl")
    event = {
        "event_id": next_event_id(events),
        "timestamp": utc_now(),
        "type": "DEBUG_INVESTIGATION_CREATED",
        "actor": actor.strip(),
        "task_id": record["task_id"],
        "run_id": record["run_id"],
        "data": {"investigation_id": record["investigation_id"], "revision": record["revision"]},
    }
    validate_event(event)
    validate_event_preconditions(root, event)
    replayed = empty_state()
    for existing in events:
        replayed = apply_event(replayed, existing)
    apply_event(replayed, event)
    return event


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="executor")
    args = parser.parse_args()
    try:
        validate_identifier(args.task_id, "task_id")
        payload = read_payload(args.input)
        if not isinstance(payload, dict):
            raise ValueError("debug investigation must be an object")
        payload = dict(payload)
        supplied_task_id = payload.get("task_id")
        if supplied_task_id is not None and supplied_task_id != args.task_id:
            raise ValueError("investigation.task_id does not match the CLI task_id")
        payload["task_id"] = args.task_id
        payload.setdefault("schema_version", 1)
        with runtime_lock(args.project_root) as root:
            task_path = root / "work" / args.task_id / "task-state.json"
            if not task_path.is_file():
                raise InvestigationBindingBlockedError(f"task state does not exist for {args.task_id}")
            task = read_object(task_path)
            existing_path = root / "work" / args.task_id / "debug-investigation.json"
            existing = read_object(existing_path) if existing_path.is_file() else None
            record = _prepare_record(payload, task, existing, root)
            event = _prepare_event(root, record, args.actor)
            target = write_validated(str(args.project_root), f"work/{args.task_id}/debug-investigation.json", record, SCHEMA)
            append_event_for_root(root, event)
            render_checklist_for_root(root)
    except (RuntimeNotInitializedError, InvestigationBindingBlockedError) as exc:
        print(f"DEBUG_INVESTIGATION_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"DEBUG_INVESTIGATION_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"DEBUG_INVESTIGATION_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
