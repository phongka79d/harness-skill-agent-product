"""Validate task-state transitions for executor and reviewer actions."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from state_machine import transition_map, transition_records_map


IDENTITY_FIELDS = ("run_id", "attempt_id", "dispatch_id")


def transition_metadata(current: str, next_state: str, *, actor: str = "executor") -> dict[str, Any] | None:
    """Return the canonical registry record for one actor transition."""

    current = str(current).upper()
    next_state = str(next_state).upper()
    return transition_records_map().get((current, next_state))


def _queue_dispatch(evidence: dict[str, Any], task_state: dict[str, Any]) -> dict[str, Any] | None:
    direct = evidence.get("dispatch")
    if isinstance(direct, dict):
        return direct
    queue = evidence.get("queue")
    if not isinstance(queue, dict):
        return None
    if all(field in queue for field in IDENTITY_FIELDS):
        return queue
    dispatches = queue.get("dispatches")
    if not isinstance(dispatches, list):
        return None
    task_id = task_state.get("task_id")
    dispatch_id = task_state.get("dispatch_id")
    matches = [
        item for item in dispatches
        if isinstance(item, dict)
        and item.get("task_id") == task_id
        and (dispatch_id is None or item.get("dispatch_id") == dispatch_id)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _guard_sources(evidence: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(evidence, dict):
        raise ValueError("same_run/same_attempt guard evidence is required")
    task_state = evidence.get("task_state", evidence.get("task"))
    review = evidence.get("review")
    lease = evidence.get("lease")
    if not isinstance(task_state, dict):
        raise ValueError("same_run/same_attempt guard evidence is missing task_state")
    if not isinstance(review, dict):
        raise ValueError("same_run/same_attempt guard evidence is missing review")
    if not isinstance(lease, dict):
        raise ValueError("same_run/same_attempt guard evidence is missing lease")
    dispatch = _queue_dispatch(evidence, task_state)
    if not isinstance(dispatch, dict):
        raise ValueError("same_run/same_attempt guard evidence is missing queue/dispatch identity")
    return [("task_state", task_state), ("review", review), ("lease", lease), ("dispatch", dispatch)]


def _validate_guard_evidence(record: dict[str, Any], evidence: Any) -> None:
    sources = _guard_sources(evidence)
    expected_task_id = sources[0][1].get("task_id")
    if not isinstance(expected_task_id, str) or not expected_task_id.strip():
        raise ValueError("same_run/same_attempt guard evidence is missing task_id")
    for source_name, source in sources:
        if source.get("task_id") != expected_task_id:
            raise ValueError(f"task identity mismatch across task_state and {source_name}")
    for guard in record.get("required_guards", ()):
        field = {"same_run": "run_id", "same_attempt": "attempt_id"}.get(guard)
        if field is None:
            continue
        values: list[tuple[str, str]] = []
        for source_name, source in sources:
            value = source.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{guard} guard evidence is missing {source_name}.{field}")
            values.append((source_name, value))
        expected = values[0][1]
        mismatches = [source_name for source_name, value in values if value != expected]
        if mismatches:
            raise ValueError(f"{guard} guard mismatch across {', '.join(name for name, _ in values)}")

    expected_dispatch = sources[0][1].get("dispatch_id")
    if not isinstance(expected_dispatch, str) or not expected_dispatch.strip():
        raise ValueError("transition guard evidence is missing task_state.dispatch_id")
    for source_name, source in sources:
        value = source.get("dispatch_id")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"dispatch identity evidence is missing {source_name}.dispatch_id")
        if value != expected_dispatch:
            raise ValueError(f"dispatch identity mismatch across task_state and {source_name}")


def validate_transition(
    current: str,
    next_state: str,
    *,
    actor: str = "executor",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a transition and enforce every guard declared by the registry."""

    current = str(current).upper()
    next_state = str(next_state).upper()
    actor = str(actor).lower()
    if not is_allowed_transition(current, next_state, actor=actor):
        raise ValueError(f"invalid transition: {current} -> {next_state} for {actor}")
    record = transition_metadata(current, next_state, actor=actor)
    if record is None:
        raise ValueError(f"transition metadata is missing for {current} -> {next_state}")
    if record.get("required_guards"):
        _validate_guard_evidence(record, evidence)
    return record


def is_allowed_transition(current: str, next_state: str, *, actor: str = "executor") -> bool:
    current = current.upper()
    next_state = next_state.upper()
    return next_state in transition_map(actor).get(current, set())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True)
    parser.add_argument("--next", required=True)
    parser.add_argument("--actor", choices=("executor", "reviewer", "cleanup"), default="executor")
    args = parser.parse_args()
    current = args.current.upper()
    next_state = args.next.upper()
    if not is_allowed_transition(current, next_state, actor=args.actor):
        print(f"INVALID_TRANSITION: {current} -> {next_state} for {args.actor}", file=sys.stderr)
        return 1
    print(f"VALID_TRANSITION: {current} -> {next_state} for {args.actor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
