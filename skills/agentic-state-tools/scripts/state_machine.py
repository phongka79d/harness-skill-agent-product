"""Load the authoritative task state machine definition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from state_transition_registry import build_state_machine, transition_records


SOURCE = Path(__file__).resolve().parents[1] / "schemas/state-machine.json"


def load_state_machine() -> dict[str, Any]:
    canonical = build_state_machine()
    with SOURCE.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or value != canonical:
        raise ValueError("state-machine.json drift")
    return canonical


def status_event_map(definition: dict[str, Any] | None = None) -> dict[str, str]:
    value = definition or build_state_machine()
    return {status: item["event"] for status, item in value["statuses"].items()}


def event_status_map(definition: dict[str, Any] | None = None) -> dict[str, str]:
    return {event: status for status, event in status_event_map(definition).items()}


def transition_map(actor: str, definition: dict[str, Any] | None = None) -> dict[str, set[str]]:
    value = definition or build_state_machine()
    actor_key = actor.lower()
    return {
        status: set(item.get(actor_key, []))
        for status, item in value["statuses"].items()
    }


def transition_records_map() -> dict[tuple[str, str], dict[str, Any]]:
    """Return transition metadata indexed by source and target status."""

    return {(record["from"], record["to"]): record for record in transition_records()}
