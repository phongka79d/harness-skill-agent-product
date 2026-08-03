"""Shared validation for append-only side-effect operation ledgers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime_utils import parse_timestamp, read_object
from validate_payload import validate


TERMINAL_OPERATION_STATUSES = {"COMPLETED", "FAILED", "UNKNOWN"}


def read_operation_ledger(
    path: Path,
    task_id: str,
    schema_path: Path,
) -> list[dict[str, Any]]:
    """Return the latest record for each operation after semantic validation."""

    if not path.exists():
        return []
    schema = read_object(schema_path)
    latest_by_id: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid operation JSON at line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"operation at line {line_number} must be an object")
            errors = validate(value, schema, base_path=schema_path.resolve().parent)
            if errors:
                raise ValueError(f"invalid operation at line {line_number}: {'; '.join(errors)}")
            if value["task_id"] != task_id:
                raise ValueError(
                    f"operation at line {line_number} belongs to {value['task_id']}, expected {task_id}"
                )
            parse_timestamp(value["recorded_at"])

            operation_id = value["operation_id"]
            previous = latest_by_id.get(operation_id)
            if previous is None:
                if value["revision"] != 1:
                    raise ValueError(f"operation {operation_id} must start at revision 1")
            else:
                for field in ("task_id", "type", "command", "run_id"):
                    if previous.get(field) != value.get(field):
                        raise ValueError(f"operation {operation_id} identity changed for {field}")
                if value["revision"] != previous["revision"] + 1:
                    raise ValueError(f"operation {operation_id} has a non-sequential revision")
                if previous["status"] in TERMINAL_OPERATION_STATUSES:
                    raise ValueError(f"operation {operation_id} changed after terminal status {previous['status']}")
                if previous["status"] == "STARTED" and value["status"] == "STARTED":
                    raise ValueError(f"operation {operation_id} repeated STARTED status")
            latest_by_id[operation_id] = value
    return list(latest_by_id.values())
