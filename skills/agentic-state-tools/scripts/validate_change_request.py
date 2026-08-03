"""Validate an approved, versioned change request and its approval evidence."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from runtime_utils import read_object, read_payload


PLAN_TARGETS = {"MASTER_PLAN", "SUB_PLAN", "BATCH", "TASK", "DECISION", "RISK", "RUBRIC", "PROFILE"}


def validate_change_request(value: object, approval: dict[str, Any] | None = None, *, applying: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("change request must be an object")
    record = dict(value)
    target_type = str(record.get("target_type", "")).upper()
    if target_type not in PLAN_TARGETS:
        raise ValueError("change_request.target_type is invalid")
    for field in ("change_request_id", "target_id", "target_version", "new_version", "reason", "requested_by", "supersedes_id"):
        if not isinstance(record.get(field), str) or not str(record[field]).strip():
            raise ValueError(f"change_request.{field} is required")
    requested_changes = record.get("requested_changes")
    if not isinstance(requested_changes, list) or not requested_changes or any(not isinstance(item, str) or not item.strip() for item in requested_changes):
        raise ValueError("change_request.requested_changes must be a non-empty array of strings")
    if not isinstance(record.get("impact"), dict):
        raise ValueError("change_request.impact must be an object")
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
