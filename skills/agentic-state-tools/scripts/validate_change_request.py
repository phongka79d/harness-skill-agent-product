"""Validate an approved, versioned change request and its approval evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runtime_utils import read_object, read_payload
from risk_flags import normalize_risk_flags
from validate_payload import validate


TARGET_ID_FIELDS = {
    "MASTER_PLAN": "plan_id",
    "SUB_PLAN": "sub_plan_id",
    "BATCH": "batch_id",
    "TASK": "task_id",
    "DECISION": "decision_id",
    "RISK": "risk_id",
    "RUBRIC": "rubric_id",
    "PROFILE": "profile_id",
    "CONFIGURATION": "configuration_id",
}
PLAN_TARGETS = set(TARGET_ID_FIELDS)
CHANGE_OPERATIONS = {"add", "replace", "remove", "move", "copy", "test"}
PATCH_FIELDS = {
    "add": frozenset({"op", "path", "value"}),
    "replace": frozenset({"op", "path", "value"}),
    "test": frozenset({"op", "path", "value"}),
    "remove": frozenset({"op", "path"}),
    "move": frozenset({"op", "path", "from"}),
    "copy": frozenset({"op", "path", "from"}),
}
SCHEMA = Path(__file__).resolve().parents[1] / "schemas/change-request.schema.json"


def _normalize_nested_risk_flags(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_nested_risk_flags(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if key == "risk_flags":
            normalized[key] = normalize_risk_flags(item)
        else:
            normalized[key] = _normalize_nested_risk_flags(item)
    return normalized


def _normalize_operation_risk_flags(operation: dict[str, Any]) -> dict[str, Any]:
    if "value" not in operation:
        return operation
    normalized = dict(operation)
    value = operation["value"]
    path = str(operation.get("path", ""))
    pointer_name = path.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
    if pointer_name == "risk_flags":
        value = normalize_risk_flags(value)
    normalized["value"] = _normalize_nested_risk_flags(value)
    return normalized


def _validate_json_pointer(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a JSON Pointer")
    if value and not value.startswith("/"):
        raise ValueError(f"{field} must be a JSON Pointer")
    for token in value[1:].split("/") if value else ():
        index = 0
        while index < len(token):
            if token[index] == "~":
                if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
                    raise ValueError(f"{field} must be a JSON Pointer")
                index += 2
            else:
                index += 1


def validate_operations(value: Any, *, applying: bool) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("change_request.requested_changes must be a non-empty array")
    operations: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"requested_changes[{index}] must be a JSON operation object")
        operation = dict(item)
        op = operation.get("op")
        if not isinstance(op, str) or op not in CHANGE_OPERATIONS:
            raise ValueError(f"requested_changes[{index}].op must be add, replace, remove, move, copy, or test")
        expected_fields = PATCH_FIELDS[op]
        actual_fields = frozenset(operation)
        if actual_fields != expected_fields:
            missing = sorted(expected_fields - actual_fields)
            extra = sorted(actual_fields - expected_fields)
            details = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if extra:
                details.append("extra=" + ",".join(extra))
            raise ValueError(f"requested_changes[{index}] has invalid fields for {op}: " + "; ".join(details))
        _validate_json_pointer(operation["path"], f"requested_changes[{index}].path")
        if op in {"move", "copy"}:
            _validate_json_pointer(operation["from"], f"requested_changes[{index}].from")
        operations.append(_normalize_operation_risk_flags(operation))
    return operations


def validate_change_request(
    value: object,
    approval: dict[str, Any] | None = None,
    *,
    applying: bool = False,
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("change request must be an object")
    record = dict(value)
    target_type = str(record.get("target_type", "")).upper()
    if target_type not in PLAN_TARGETS:
        raise ValueError("change_request.target_type is invalid")
    if target is not None:
        target_id_field = TARGET_ID_FIELDS[target_type]
        if target.get(target_id_field) != record.get("target_id"):
            raise ValueError(f"target {target_type} {target_id_field} does not match target_id")
    for field in ("change_request_id", "target_id", "target_version", "new_version", "reason", "requested_by", "supersedes_id"):
        if not isinstance(record.get(field), str) or not str(record[field]).strip():
            raise ValueError(f"change_request.{field} is required")
    requested_changes = record.get("requested_changes")
    validate_operations(requested_changes, applying=applying)
    if not isinstance(record.get("impact"), dict):
        raise ValueError("change_request.impact must be an object")
    impact = dict(record["impact"])
    try:
        impact["risk_flags"] = normalize_risk_flags(impact.get("risk_flags", {}))
    except ValueError as exc:
        raise ValueError(f"change_request.impact.risk_flags is invalid: {exc}") from exc
    record["impact"] = impact
    schema_errors = validate(record, read_object(SCHEMA), base_path=SCHEMA.parent)
    if schema_errors:
        raise ValueError("change request schema validation failed: " + "; ".join(schema_errors))
    if record["target_version"] == record["new_version"]:
        raise ValueError("change request must create a new version")
    if target_type in PLAN_TARGETS and not record["supersedes_id"].startswith(record["target_id"] + "@"):
        raise ValueError("change_request.supersedes_id must identify the target version")
    if applying and str(record.get("status", "")).upper() != "APPROVED":
        raise ValueError("only an APPROVED change request can be applied")
    if not isinstance(approval, dict):
        raise ValueError("approved change request requires approval evidence")
    if approval.get("approval_id") != record.get("approval_id"):
        raise ValueError("approval ID does not match change request")
    if str(approval.get("decision", "")).upper() != "APPROVED":
        raise ValueError("change request approval is not APPROVED")
    if approval.get("target_id") not in {record["change_request_id"], record["target_id"]} and approval.get("change_request_id") != record["change_request_id"]:
        raise ValueError("approval does not target the change request")
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--approval")
    parser.add_argument("--applying", action="store_true")
    args = parser.parse_args()
    try:
        approval = read_object(args.approval) if args.approval else None
        validate_change_request(read_payload(args.input), approval, applying=args.applying)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"CHANGE_REQUEST_INVALID: {exc}", file=sys.stderr)
        return 1
    print("CHANGE_REQUEST_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
