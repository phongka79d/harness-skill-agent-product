"""Apply an approved change as a new immutable versioned plan artifact."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from runtime_utils import read_object, read_payload, utc_now, write_json_atomic
from validate_change_request import validate_change_request, validate_operations


def _pointer_tokens(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise ValueError("JSON Pointer must start with '/'")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def _apply_operation(document: Any, operation: dict[str, Any]) -> Any:
    tokens = _pointer_tokens(operation["path"])
    if not tokens:
        if operation["op"] == "remove":
            raise ValueError("removing the root document is not supported")
        return copy.deepcopy(operation["value"])
    result = document
    for token in tokens[:-1]:
        if isinstance(result, dict) and token in result:
            result = result[token]
        elif isinstance(result, list) and token.isdigit() and int(token) < len(result):
            result = result[int(token)]
        else:
            raise ValueError(f"JSON Pointer parent does not exist: {operation['path']}")
    key = tokens[-1]
    if isinstance(result, dict):
        if operation["op"] == "remove":
            if key not in result:
                raise ValueError(f"JSON Pointer target does not exist: {operation['path']}")
            del result[key]
        elif operation["op"] == "replace" and key not in result:
            raise ValueError(f"JSON Pointer target does not exist: {operation['path']}")
        else:
            result[key] = copy.deepcopy(operation["value"])
        return document
    if isinstance(result, list):
        if operation["op"] == "add" and key == "-":
            result.append(copy.deepcopy(operation["value"]))
            return document
        if not key.isdigit() or int(key) >= len(result):
            raise ValueError(f"JSON Pointer list index is invalid: {operation['path']}")
        index = int(key)
        if operation["op"] == "remove":
            result.pop(index)
        elif operation["op"] == "replace":
            result[index] = copy.deepcopy(operation["value"])
        else:
            result.insert(index, copy.deepcopy(operation["value"]))
        return document
    raise ValueError(f"JSON Pointer parent is not traversable: {operation['path']}")


def apply_operations(target: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    result: Any = copy.deepcopy(target)
    for operation in operations:
        result = _apply_operation(result, operation)
    if not isinstance(result, dict):
        raise ValueError("change request must leave a plan artifact object")
    return result


def artifact_hash(value: dict[str, Any]) -> str:
    canonical = dict(value)
    canonical.pop("artifact_hash", None)
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        request = read_payload(args.request)
        approval = read_object(args.approval)
        record = validate_change_request(request, approval, applying=True)
        target_path = Path(args.target).resolve()
        output_path = Path(args.output).resolve()
        if target_path == output_path:
            raise ValueError("historical target and new plan output must be different files")
        target = read_object(target_path)
        if target.get("plan_id") != record["target_id"] or str(target.get("version")) != record["target_version"]:
            raise ValueError("target plan does not match change request target and version")
        operations = validate_operations(record["requested_changes"], applying=True)
        new_plan = apply_operations(target, operations)
        new_plan["version"] = record["new_version"]
        new_plan["supersedes_id"] = record["supersedes_id"]
        new_plan["change_request_id"] = record["change_request_id"]
        new_plan["change_status"] = "APPLIED"
        new_plan["applied_at"] = utc_now()
        new_plan["requested_changes"] = operations
        if isinstance(new_plan.get("revision"), int) and not isinstance(new_plan["revision"], bool):
            new_plan["revision"] += 1
        else:
            new_plan["revision"] = 1
        if isinstance(new_plan.get("master_plan"), dict):
            new_plan["master_plan"]["revision"] = new_plan["revision"]
        for stale_field in ("approval_id", "review_id", "review_verdict", "accepted", "approval_references"):
            new_plan.pop(stale_field, None)
        new_plan["invalidated_artifacts"] = ["approvals", "reviews", "batch_contracts", "dispatches"]
        new_plan["artifact_hash"] = artifact_hash(new_plan)
        write_json_atomic(output_path, new_plan)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"CHANGE_APPLY_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(new_plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
