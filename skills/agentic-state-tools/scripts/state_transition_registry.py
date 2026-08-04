"""Authoritative task-state transitions and their contract metadata."""

from __future__ import annotations

from typing import Any


STATUS_EVENTS = {
    "PENDING": "TASK_PENDING",
    "READY": "TASK_READY",
    "QUEUED": "TASK_QUEUED",
    "QUEUED_ASYNC": "TASK_QUEUED_ASYNC",
    "QUEUED_SYNC": "TASK_QUEUED_SYNC",
    "WAITING": "TASK_WAITING",
    "WAITING_DEPENDENCY": "TASK_WAITING_DEPENDENCY",
    "WAITING_RESOURCE_LOCK": "TASK_WAITING_RESOURCE_LOCK",
    "RUNNING": "TASK_STARTED",
    "CHECKPOINTED": "TASK_CHECKPOINTED",
    "PAUSED": "TASK_PAUSED",
    "BLOCKED": "TASK_BLOCKED",
    "REPAIR_REQUIRED": "TASK_REPAIR_REQUIRED",
    "COMPLETED": "TASK_COMPLETED",
    "REVIEWING": "TASK_REVIEWING",
    "ACCEPTED": "TASK_ACCEPTED",
    "STALE": "TASK_STALE",
    "RECOVERY_PENDING": "TASK_RECOVERY_PENDING",
    "RESUMING": "TASK_RESUMING",
    "DEFERRED": "TASK_DEFERRED",
    "ESCALATED": "TASK_ESCALATED",
    "ABORTED_UNSAFE": "TASK_ABORTED_UNSAFE",
    "ARCHIVED": "TASK_ARCHIVED",
    "CANCELLED": "TASK_CANCELLED",
    "SUPERSEDED": "TASK_SUPERSEDED",
}

TERMINAL_STATUSES = ("ACCEPTED", "CANCELLED", "SUPERSEDED", "ABORTED_UNSAFE", "ARCHIVED")
NON_STATE_EVENTS = (
    "BATCH_CONTRACT_CREATED",
    "BATCH_REVIEW_CREATED",
    "CHECKPOINT_CREATED",
    "CONTEXT_CREATED",
    "HANDOFF_CREATED",
    "REVIEW_CREATED",
    "LOCK_ACQUIRED",
    "LOCK_RELEASED",
    "LOCK_RECLAIMED",
    "APPROVAL_RECORDED",
    "HEARTBEAT_RECORDED",
    "LEASE_RELEASED",
    "OPERATION_RECORDED",
    "RECOVERY_INSPECTED",
    "ROLLBACK_PLANNED",
    "COMPENSATION_RECORDED",
    "ROLLBACK_ESCALATED",
    "ARTIFACT_INVALIDATED",
)


def _transition(
    source: str,
    target: str,
    roles: tuple[str, ...],
    *,
    artifacts: tuple[str, ...] = ("task_state",),
    guards: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "from": source,
        "to": target,
        "event": STATUS_EVENTS[target],
        "allowed_roles": roles,
        "required_artifacts": artifacts,
        "required_guards": guards,
    }


_EXECUTOR = "executor"
_REVIEWER = "reviewer"
_CLEANUP = "cleanup"
KNOWN_ROLES = frozenset({_EXECUTOR, _REVIEWER, _CLEANUP})
KNOWN_REQUIRED_ARTIFACTS = frozenset({
    "task_state",
    "review",
    "review_contract",
    "lease",
    "queue",
    "dispatch",
    "batch_contract",
    "approval",
})
KNOWN_REQUIRED_GUARDS = frozenset({"same_run", "same_attempt", "terminal_cleanup"})
_REVIEW_GUARDS = ("same_run", "same_attempt")
_REVIEW_ARTIFACTS = ("task_state", "review", "review_contract")


TRANSITIONS = tuple(
    [
        *[_transition("PENDING", target, (_EXECUTOR,)) for target in ("READY", "CANCELLED", "DEFERRED")],
        *[_transition("READY", target, (_EXECUTOR,)) for target in ("QUEUED", "QUEUED_ASYNC", "QUEUED_SYNC", "WAITING", "WAITING_DEPENDENCY", "WAITING_RESOURCE_LOCK", "CANCELLED", "DEFERRED")],
        *[_transition("QUEUED", target, (_EXECUTOR,)) for target in ("RUNNING", "QUEUED_ASYNC", "QUEUED_SYNC", "WAITING", "WAITING_DEPENDENCY", "WAITING_RESOURCE_LOCK", "CANCELLED")],
        *[_transition("QUEUED_ASYNC", target, (_EXECUTOR,)) for target in ("RUNNING", "WAITING_DEPENDENCY", "WAITING_RESOURCE_LOCK", "CANCELLED")],
        *[_transition("QUEUED_SYNC", target, (_EXECUTOR,)) for target in ("RUNNING", "WAITING_DEPENDENCY", "WAITING_RESOURCE_LOCK", "CANCELLED")],
        *[_transition("WAITING", target, (_EXECUTOR,)) for target in ("QUEUED", "QUEUED_ASYNC", "QUEUED_SYNC", "RUNNING", "CANCELLED")],
        *[_transition("WAITING_DEPENDENCY", target, (_EXECUTOR,)) for target in ("QUEUED", "QUEUED_ASYNC", "QUEUED_SYNC", "RUNNING", "BLOCKED", "CANCELLED")],
        *[_transition("WAITING_RESOURCE_LOCK", target, (_EXECUTOR,)) for target in ("QUEUED", "QUEUED_ASYNC", "QUEUED_SYNC", "RUNNING", "BLOCKED", "CANCELLED")],
        *[_transition("RUNNING", target, (_EXECUTOR,)) for target in ("CHECKPOINTED", "COMPLETED", "REVIEWING", "BLOCKED", "REPAIR_REQUIRED", "WAITING", "WAITING_DEPENDENCY", "WAITING_RESOURCE_LOCK", "PAUSED", "STALE", "CANCELLED", "ESCALATED")],
        *[_transition("CHECKPOINTED", target, (_EXECUTOR,)) for target in ("RUNNING", "STALE", "BLOCKED", "CANCELLED")],
        *[_transition("PAUSED", target, (_EXECUTOR,)) for target in ("QUEUED", "QUEUED_SYNC", "RUNNING", "CANCELLED")],
        *[_transition("BLOCKED", target, (_EXECUTOR,)) for target in ("QUEUED", "QUEUED_SYNC", "REPAIR_REQUIRED", "CANCELLED", "DEFERRED", "ESCALATED")],
        *[_transition("REPAIR_REQUIRED", target, (_EXECUTOR,)) for target in ("QUEUED", "QUEUED_SYNC", "RUNNING", "CANCELLED")],
        _transition("COMPLETED", "REVIEWING", (_EXECUTOR, _REVIEWER), artifacts=_REVIEW_ARTIFACTS, guards=_REVIEW_GUARDS),
        _transition("COMPLETED", "REPAIR_REQUIRED", (_EXECUTOR,), artifacts=_REVIEW_ARTIFACTS, guards=_REVIEW_GUARDS),
        _transition("REVIEWING", "ACCEPTED", (_REVIEWER,), artifacts=_REVIEW_ARTIFACTS, guards=_REVIEW_GUARDS),
        _transition("REVIEWING", "REPAIR_REQUIRED", (_REVIEWER,), artifacts=_REVIEW_ARTIFACTS, guards=_REVIEW_GUARDS),
        _transition("REVIEWING", "BLOCKED", (_REVIEWER,), artifacts=_REVIEW_ARTIFACTS, guards=_REVIEW_GUARDS),
        *[_transition("STALE", target, (_REVIEWER,)) for target in ("RECOVERY_PENDING", "ABORTED_UNSAFE", "ESCALATED")],
        *[_transition("RECOVERY_PENDING", target, (_REVIEWER,)) for target in ("RESUMING", "BLOCKED", "ESCALATED", "ABORTED_UNSAFE")],
        *[_transition("RESUMING", target, (_EXECUTOR,)) for target in ("RUNNING", "BLOCKED", "ABORTED_UNSAFE")],
        *[_transition("DEFERRED", target, (_EXECUTOR,)) for target in ("READY", "QUEUED_SYNC", "CANCELLED", "SUPERSEDED")],
        *[_transition("ESCALATED", target, (_EXECUTOR,)) for target in ("BLOCKED", "DEFERRED", "CANCELLED", "SUPERSEDED")],
        *[_transition(source, "ARCHIVED", (_CLEANUP,), guards=("terminal_cleanup",)) for source in ("ACCEPTED", "CANCELLED", "SUPERSEDED")],
    ]
)


def validate_transition_records(records: tuple[dict[str, Any], ...] = TRANSITIONS) -> list[str]:
    errors: list[str] = []
    statuses = set(STATUS_EVENTS)
    seen_pairs: dict[tuple[str, str], int] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"transition[{index}] must be an object")
            continue
        for field in ("from", "to", "event", "allowed_roles", "required_artifacts", "required_guards"):
            if field not in record:
                errors.append(f"transition[{index}] missing {field}")
        source = record.get("from")
        target = record.get("to")
        if source not in statuses:
            errors.append(f"transition[{index}] references missing from status {source}")
        if target not in statuses:
            errors.append(f"transition[{index}] references missing to status {target}")
        if isinstance(source, str) and isinstance(target, str):
            pair = (source, target)
            prior_index = seen_pairs.get(pair)
            if prior_index is not None:
                errors.append(
                    f"transition[{index}] duplicate from/to transition {source} -> {target} "
                    f"(already declared at transition[{prior_index}])"
                )
            else:
                seen_pairs[pair] = index
        if target in statuses and record.get("event") != STATUS_EVENTS[target]:
            errors.append(
                f"transition[{index}] event/status mismatch: {record.get('event')} "
                f"does not represent target status {target} ({STATUS_EVENTS[target]})"
            )
        if not isinstance(record.get("allowed_roles"), tuple) or not record.get("allowed_roles"):
            errors.append(f"transition[{index}] allowed_roles must be a non-empty tuple")
        elif any(role not in KNOWN_ROLES for role in record["allowed_roles"]):
            unknown = sorted({str(role) for role in record["allowed_roles"] if role not in KNOWN_ROLES})
            errors.append(f"transition[{index}] unknown role(s): {', '.join(unknown)}")
        if not isinstance(record.get("required_artifacts"), tuple):
            errors.append(f"transition[{index}] required_artifacts must be a tuple")
        else:
            unknown = sorted({str(artifact) for artifact in record["required_artifacts"] if artifact not in KNOWN_REQUIRED_ARTIFACTS})
            if unknown:
                errors.append(f"transition[{index}] unknown required artifact(s): {', '.join(unknown)}")
        if not isinstance(record.get("required_guards"), tuple):
            errors.append(f"transition[{index}] required_guards must be a tuple")
        else:
            unknown = sorted({str(guard) for guard in record["required_guards"] if guard not in KNOWN_REQUIRED_GUARDS})
            if unknown:
                errors.append(f"transition[{index}] unknown required guard(s): {', '.join(unknown)}")
    return errors


def build_state_machine() -> dict[str, Any]:
    errors = validate_transition_records()
    if errors:
        raise ValueError("; ".join(errors))
    statuses: dict[str, dict[str, Any]] = {
        status: {
            "event": event,
            "executor": [],
            "reviewer": [],
            "cleanup": [],
            "required_artifacts": [],
            "required_guards": [],
        }
        for status, event in STATUS_EVENTS.items()
    }
    for record in TRANSITIONS:
        item = statuses[record["from"]]
        for role in record["allowed_roles"]:
            item[role].append(record["to"])
        item["required_artifacts"].extend(record["required_artifacts"])
        item["required_guards"].extend(record["required_guards"])
    for item in statuses.values():
        for field in ("executor", "reviewer", "cleanup", "required_artifacts", "required_guards"):
            item[field] = sorted(set(item[field]))
    return {
        "schema_version": 1,
        "terminal_statuses": list(TERMINAL_STATUSES),
        "statuses": statuses,
        "non_state_events": list(NON_STATE_EVENTS),
    }


def transition_records() -> tuple[dict[str, Any], ...]:
    return TRANSITIONS
