"""Plan explicit compensation and record provider-confirmed rollback outcomes."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from validate_payload import validate
from authorization import authorize


SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
ACTION_SCHEMA = SCHEMA_ROOT / "compensation-action.schema.json"
PLAN_SCHEMA = SCHEMA_ROOT / "rollback-plan.schema.json"
LEDGER_SCHEMA = SCHEMA_ROOT / "rollback-ledger.schema.json"
EVIDENCE_SCHEMA = SCHEMA_ROOT / "rollback-evidence.schema.json"


class RollbackRequestError(ValueError):
    pass


class ApprovalRequired(RollbackRequestError):
    pass


class FencingConflict(RollbackRequestError):
    pass


def _timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise RollbackRequestError("timestamp must include a timezone")
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(value: dict[str, Any], path: Path, label: str) -> None:
    errors = validate(value, _schema(path))
    if errors:
        raise RollbackRequestError(f"{label} is invalid: {'; '.join(errors)}")


def _topological(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {action["action_id"]: action for action in actions}
    pending = set(by_id)
    ordered: list[dict[str, Any]] = []
    while pending:
        ready = sorted(action_id for action_id in pending if all(dep not in pending for dep in by_id[action_id]["depends_on"]))
        if not ready:
            raise RollbackRequestError("compensation actions contain a dependency cycle")
        for action_id in ready:
            ordered.append(by_id[action_id])
            pending.remove(action_id)
    return ordered


def build_rollback_plan(request: dict[str, Any], operations: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("rollback_requested") is not True:
        raise RollbackRequestError("rollback requires an explicit rollback_requested=true request")
    task_id = request.get("task_id")
    plan_id = request.get("plan_id")
    requested_by = request.get("requested_by")
    reason = request.get("reason")
    actions = request.get("actions")
    if not all(isinstance(value, str) and value.strip() for value in (task_id, plan_id, requested_by, reason)):
        raise RollbackRequestError("plan_id, task_id, requested_by, and reason are required")
    if not isinstance(actions, list) or not actions:
        raise RollbackRequestError("an explicit rollback request must contain actions")
    known = {operation.get("operation_id"): operation for operation in operations if isinstance(operation, dict)}
    normalized: list[dict[str, Any]] = []
    action_ids: set[str] = set()
    for raw in actions:
        if not isinstance(raw, dict):
            raise RollbackRequestError("compensation action must be an object")
        action = dict(raw)
        action_id = action.get("action_id")
        operation_id = action.get("operation_id")
        if not isinstance(action_id, str) or not action_id.strip() or action_id in action_ids:
            raise RollbackRequestError("compensation action IDs must be unique and non-empty")
        if operation_id not in known or known[operation_id].get("task_id") != task_id:
            raise RollbackRequestError(f"compensation action references an unknown task operation: {operation_id}")
        action_ids.add(action_id)
        action["depends_on"] = action.get("depends_on", [])
        if not isinstance(action["depends_on"], list) or any(not isinstance(item, str) for item in action["depends_on"]):
            raise RollbackRequestError(f"dependencies are invalid for {action_id}")
        _validate(action, ACTION_SCHEMA, f"compensation action {action_id}")
        normalized.append(action)
    for action in normalized:
        unknown = sorted(set(action["depends_on"]) - action_ids)
        if unknown:
            raise RollbackRequestError(f"compensation action {action['action_id']} has unknown dependencies: {', '.join(unknown)}")
    ordered = _topological(normalized)
    plan = {
        "schema_version": 1,
        "plan_id": plan_id,
        "task_id": task_id,
        "revision": 1,
        "status": "DRY_RUN",
        "classification": "ROLLBACK_PLANNED",
        "dry_run": True,
        "requested_by": requested_by,
        "reason": reason,
        "operation_ids": [action["operation_id"] for action in ordered],
        "actions": ordered,
        "requires_approval": True,
        "approval_id": None,
        "created_at": _timestamp(now),
    }
    plan["plan_hash"] = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    _validate(plan, PLAN_SCHEMA, "rollback plan")
    return plan


def _validate_approval(
    plan: dict[str, Any],
    approval: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    actor_id: str | None = None,
    actor_type: str = "primary_agent",
) -> str:
    try:
        return authorize(
            "ROLLBACK",
            {
                "target_type": "ROLLBACK",
                "target_id": str(plan["plan_id"]),
                "revision": int(plan["revision"]),
                "target_hash": str(plan["plan_hash"]),
            },
            approval,
            actor={"actor_type": actor_type, "actor_id": actor_id or "primary-agent"},
            now=now,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ApprovalRequired(str(exc)) from exc


def execute_rollback(
    plan: dict[str, Any],
    approval: dict[str, Any] | None,
    outcomes: dict[str, dict[str, Any]],
    *,
    fencing_validator: Callable[[dict[str, Any]], None] | None = None,
    now: datetime | None = None,
    actor_id: str | None = None,
    actor_type: str = "primary_agent",
) -> dict[str, Any]:
    _validate(plan, PLAN_SCHEMA, "rollback plan")
    if plan.get("status") != "DRY_RUN" or plan.get("dry_run") is not True:
        raise RollbackRequestError("executor accepts only an unexecuted DRY_RUN plan")
    approval_id = _validate_approval(plan, approval, now=now, actor_id=actor_id, actor_type=actor_type)
    if not isinstance(outcomes, dict):
        raise RollbackRequestError("provider outcomes must be an object keyed by action ID")
    entries: list[dict[str, Any]] = []
    completed_count = 0
    stopped = False
    for action in plan["actions"]:
        action_id = action["action_id"]
        operation_id = action["operation_id"]
        if stopped:
            entries.append({"action_id": action_id, "operation_id": operation_id, "status": "BLOCKED", "retry_allowed": False, "evidence": "not executed after an earlier uncertain or failed action"})
            continue
        try:
            if action.get("fencing") is not None and fencing_validator is not None:
                fencing_validator(action)
        except FencingConflict:
            entries.append({"action_id": action_id, "operation_id": operation_id, "status": "STALE_OWNER", "retry_allowed": False, "evidence": "current fencing token rejected"})
            stopped = True
            continue
        outcome = outcomes.get(action_id)
        if not isinstance(outcome, dict):
            status = "UNKNOWN"
            evidence = "provider outcome is missing"
        else:
            status = str(outcome.get("status", "UNKNOWN")).upper()
            evidence = str(outcome.get("evidence") or "provider did not supply evidence")
        if status not in {"COMPLETED", "FAILED", "UNKNOWN"}:
            raise RollbackRequestError(f"unsupported provider outcome for {action_id}: {status}")
        entries.append({"action_id": action_id, "operation_id": operation_id, "status": status, "retry_allowed": False, "evidence": evidence})
        if status == "COMPLETED":
            completed_count += 1
        else:
            stopped = True
    failed_or_uncertain = any(entry["status"] in {"FAILED", "UNKNOWN", "STALE_OWNER"} for entry in entries)
    if failed_or_uncertain:
        classification = "PARTIAL_ROLLBACK" if completed_count else "ESCALATED"
        status = "ESCALATED"
        next_action = "ESCALATE"
    else:
        classification = "ROLLED_BACK"
        status = "ROLLED_BACK"
        next_action = "none"
    ledger = {
        "schema_version": 1,
        "ledger_id": f"LEDGER-{plan['plan_id']}",
        "plan_id": plan["plan_id"],
        "task_id": plan["task_id"],
        "approval_id": approval_id,
        "status": status,
        "classification": classification,
        "entries": entries,
        "next_action": next_action,
        "created_at": _timestamp(now),
    }
    _validate(ledger, LEDGER_SCHEMA, "rollback ledger")
    return ledger


def rollback_evidence(ledger: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    reasons = [entry["evidence"] for entry in ledger["entries"] if entry["status"] != "COMPLETED"]
    if not reasons:
        reasons = ["all compensation actions completed with provider evidence"]
    record = {
        "schema_version": 1,
        "evidence_id": f"EVIDENCE-{ledger['ledger_id']}",
        "plan_id": ledger["plan_id"],
        "ledger_id": ledger["ledger_id"],
        "classification": ledger["classification"],
        "reasons": reasons,
        "created_at": _timestamp(now),
    }
    record["evidence_hash"] = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    _validate(record, EVIDENCE_SCHEMA, "rollback evidence")
    return record
