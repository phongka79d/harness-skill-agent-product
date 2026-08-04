"""Apply an approved change as a new immutable versioned plan artifact."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from runtime_utils import read_object, read_payload, utc_now
from runtime_transaction import RuntimeTransaction
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


def _initialized_project_for(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".agent" / "runtime" / "state.json").is_file():
            return candidate
    return None


def _initialize_project_runtime(project_root: Path) -> Path:
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("init_runtime.py")), "--project-root", str(project_root)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown initialization failure"
        raise ValueError(f"runtime initialization failed: {detail}")
    return project_root.resolve()


def _write_plan_transactionally(
    output_path: Path,
    new_plan: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> None:
    output_path = Path(output_path).expanduser()
    try:
        resolved_output = output_path.resolve(strict=False)
    except OSError as exc:
        raise ValueError("output must be inside an initialized project .agent root") from exc
    project_root = project_root.resolve() if project_root is not None else _initialized_project_for(resolved_output.parent)
    if project_root is None:
        raise ValueError("output must be inside an initialized project .agent root")
    resolved_project = project_root.resolve()
    agent_root = (resolved_project / ".agent").resolve()
    try:
        agent_root.relative_to(resolved_project)
    except ValueError as exc:
        raise ValueError("initialized project .agent root escapes the project root") from exc
    try:
        relative_path = resolved_output.relative_to(agent_root)
        target_relative = relative_path.as_posix()
    except ValueError as exc:
        try:
            relative_path = resolved_output.relative_to(resolved_project)
        except ValueError:
            raise ValueError("output must remain inside the project root") from exc
        if not relative_path.parts or relative_path.parts[0] == ".agent":
            raise ValueError("output must be inside an initialized project .agent root") from exc
        target_relative = f"project/{relative_path.as_posix()}"
    if not relative_path.parts:
        raise ValueError("output must identify a file inside the project root")
    current_revision = 0
    current: dict[str, Any] = {}
    if resolved_output.is_file():
        try:
            current = read_object(resolved_output)
        except (OSError, ValueError, json.JSONDecodeError):
            current = {}
    if isinstance(current.get("revision"), int) and not isinstance(current.get("revision"), bool):
        current_revision = current["revision"]
    content_hash = artifact_hash(new_plan)
    transaction = RuntimeTransaction(
        project_root,
        operation_type="PLAN_CHANGE",
        idempotency_key=f"plan-change:{new_plan['change_request_id']}:{new_plan['version']}:{content_hash}",
        expected_revisions={target_relative: current_revision},
    )
    transaction.prepare([target_relative])
    transaction.stage_text(target_relative, json.dumps(new_plan, ensure_ascii=False, indent=2) + "\n")
    transaction.commit()


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
        project_root = _initialized_project_for(output_path.parent) or _initialized_project_for(target_path.parent)
        if project_root is None:
            project_root = target_path.parent
            try:
                output_path.relative_to(project_root)
            except ValueError as exc:
                raise ValueError("target and output must remain inside one project root") from exc
            project_root = _initialize_project_runtime(project_root)
        _write_plan_transactionally(output_path, new_plan, project_root=project_root)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"CHANGE_APPLY_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(new_plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
