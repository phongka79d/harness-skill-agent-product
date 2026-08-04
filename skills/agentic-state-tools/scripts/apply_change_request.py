"""Apply an approved change as a new immutable versioned plan artifact."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterator

from authorization import authorize, require_persisted_approval
from runtime_utils import iter_events, next_event_id, prepare_event_log, read_object, read_payload, utc_now
from runtime_transaction import RuntimeTransaction
from validate_change_request import TARGET_ID_FIELDS, validate_change_request, validate_operations


JSON_PATCH_OPERATIONS = frozenset({"add", "replace", "remove", "move", "copy", "test"})
MAX_INVALIDATION_ARTIFACTS = 1024
MAX_INVALIDATION_DEPTH = 16


def _pointer_tokens(path: str) -> list[str]:
    if not isinstance(path, str):
        raise ValueError("JSON Pointer must be a string")
    if path == "":
        return []
    if not path.startswith("/"):
        raise ValueError("JSON Pointer must start with '/'")
    tokens: list[str] = []
    for part in path[1:].split("/"):
        value: list[str] = []
        index = 0
        while index < len(part):
            if part[index] != "~":
                value.append(part[index])
                index += 1
                continue
            if index + 1 >= len(part) or part[index + 1] not in {"0", "1"}:
                raise ValueError(f"invalid JSON Pointer escape: {path}")
            value.append("~" if part[index + 1] == "0" else "/")
            index += 2
        tokens.append("".join(value))
    return tokens


def _list_index(token: str, length: int, *, allow_end: bool = False) -> int:
    if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
        raise ValueError("JSON Pointer list index is invalid")
    index = int(token)
    upper_bound = length if allow_end else length - 1
    if index > upper_bound:
        raise ValueError("JSON Pointer list index is invalid")
    return index


def _resolve_pointer(document: Any, path: str, *, allow_append: bool = False) -> Any:
    tokens = _pointer_tokens(path)
    current = document
    for index, token in enumerate(tokens):
        if isinstance(current, dict):
            if token not in current:
                raise ValueError(f"JSON Pointer target does not exist: {path}")
            current = current[token]
        elif isinstance(current, list):
            if token == "-" and allow_append and index == len(tokens) - 1:
                return current
            try:
                index = _list_index(token, len(current))
            except ValueError as exc:
                raise ValueError(f"JSON Pointer list index is invalid: {path}")
            current = current[index]
        else:
            raise ValueError(f"JSON Pointer target is not traversable: {path}")
    return current


def _validate_patch_operation(operation: Any) -> dict[str, Any]:
    if not isinstance(operation, dict):
        raise ValueError("JSON Patch operation must be an object")
    op = operation.get("op")
    if not isinstance(op, str) or op not in JSON_PATCH_OPERATIONS:
        raise ValueError(f"unknown JSON Patch operation: {op!r}")
    expected_fields = {
        "add": frozenset({"op", "path", "value"}),
        "replace": frozenset({"op", "path", "value"}),
        "test": frozenset({"op", "path", "value"}),
        "remove": frozenset({"op", "path"}),
        "move": frozenset({"op", "path", "from"}),
        "copy": frozenset({"op", "path", "from"}),
    }[op]
    actual_fields = frozenset(operation)
    if actual_fields != expected_fields:
        missing = sorted(expected_fields - actual_fields)
        extra = sorted(actual_fields - expected_fields)
        if missing == ["value"] and not extra:
            raise ValueError(f"JSON Patch operation {op} requires value")
        if missing == ["from"] and not extra:
            raise ValueError(f"JSON Patch operation {op} requires from")
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise ValueError(f"JSON Patch operation {op} has invalid fields: " + "; ".join(details))
    _pointer_tokens(operation.get("path"))
    if op in {"move", "copy"}:
        _pointer_tokens(operation["from"])
    return operation


def _apply_operation_in_place(document: Any, operation: dict[str, Any]) -> Any:
    op = operation["op"]
    if op == "test":
        actual = _resolve_pointer(document, operation["path"])
        if actual != operation["value"]:
            raise ValueError(f"JSON Patch test failed at {operation['path']}")
        return document
    if op in {"copy", "move"}:
        source = copy.deepcopy(_resolve_pointer(document, operation["from"]))
        if op == "move":
            _apply_operation_in_place(document, {"op": "remove", "path": operation["from"]})
        return _apply_operation_in_place(document, {"op": "add", "path": operation["path"], "value": source})
    tokens = _pointer_tokens(operation["path"])
    if not tokens:
        if op == "remove":
            raise ValueError("removing the root document is not supported")
        return copy.deepcopy(operation.get("value"))
    result = document
    for token in tokens[:-1]:
        if isinstance(result, dict) and token in result:
            result = result[token]
        elif isinstance(result, list):
            try:
                result = result[_list_index(token, len(result))]
            except ValueError as exc:
                raise ValueError(f"JSON Pointer parent does not exist: {operation['path']}") from exc
        else:
            raise ValueError(f"JSON Pointer parent does not exist: {operation['path']}")
    key = tokens[-1]
    if isinstance(result, dict):
        if op == "remove":
            if key not in result:
                raise ValueError(f"JSON Pointer target does not exist: {operation['path']}")
            del result[key]
        elif op == "replace" and key not in result:
            raise ValueError(f"JSON Pointer target does not exist: {operation['path']}")
        else:
            result[key] = copy.deepcopy(operation.get("value"))
        return document
    if isinstance(result, list):
        if op == "add" and key == "-":
            result.append(copy.deepcopy(operation.get("value")))
            return document
        try:
            index = _list_index(key, len(result), allow_end=op == "add")
        except ValueError as exc:
            raise ValueError(f"JSON Pointer list index is invalid: {operation['path']}") from exc
        if op == "add" and index == len(result):
            result.append(copy.deepcopy(operation.get("value")))
            return document
        if op == "remove":
            result.pop(index)
        elif op == "replace":
            result[index] = copy.deepcopy(operation.get("value"))
        else:
            result.insert(index, copy.deepcopy(operation.get("value")))
        return document
    raise ValueError(f"JSON Pointer parent is not traversable: {operation['path']}")


def _apply_operation(document: Any, operation: dict[str, Any]) -> Any:
    _validate_patch_operation(operation)
    working = copy.deepcopy(document)
    return _apply_operation_in_place(working, operation)


def apply_operations(target: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(target, dict):
        raise ValueError("change request target must be a plan artifact object")
    if not isinstance(operations, list):
        raise ValueError("JSON Patch operations must be a list")
    for operation in operations:
        _validate_patch_operation(operation)
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


def _artifact_revision(value: dict[str, Any]) -> int:
    revision = value.get("revision")
    if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 1:
        return revision
    nested = value.get("master_plan")
    if isinstance(nested, dict) and isinstance(nested.get("revision"), int) and not isinstance(nested.get("revision"), bool):
        return nested["revision"]
    raise ValueError("target artifact must have a positive revision")


def _artifact_target_hash(value: dict[str, Any]) -> str:
    computed = artifact_hash(value)
    supplied = value.get("artifact_hash") or value.get("target_hash")
    if supplied is not None and supplied != computed:
        raise ValueError("target artifact hash does not match its content")
    return computed


def _relative_target_path(project_root: Path, path: Path) -> str:
    resolved = path.resolve(strict=False)
    agent_root = (project_root / ".agent").resolve()
    try:
        return resolved.relative_to(agent_root).as_posix()
    except ValueError:
        relative = resolved.relative_to(project_root).as_posix()
        if relative == ".agent" or relative.startswith(".agent/"):
            raise ValueError("target must not escape the project .agent boundary")
        return f"project/{relative}"


def _contains_old_binding(value: Any, old_revision: int, old_hash: str) -> bool:
    if isinstance(value, dict):
        revision_bound = any(
            key in {"revision", "target_revision", "plan_revision", "task_revision", "batch_contract_revision", "review_revision"}
            and item == old_revision
            for key, item in value.items()
        )
        hash_bound = any(
            key in {"target_hash", "plan_hash", "task_hash", "artifact_hash", "contract_hash", "review_hash"}
            and item == old_hash
            for key, item in value.items()
        )
        input_hash_bound = isinstance(value.get("input_artifact_hashes"), dict) and old_hash in value["input_artifact_hashes"].values()
        if revision_bound and (hash_bound or input_hash_bound):
            return True
        for item in value.values():
            if _contains_old_binding(item, old_revision, old_hash):
                return True
    elif isinstance(value, list):
        return any(_contains_old_binding(item, old_revision, old_hash) for item in value)
    return False


def _artifact_category(path: Path, agent_root: Path) -> str:
    relative = path.relative_to(agent_root).as_posix()
    name = path.name.lower()
    if relative.startswith("approvals/"):
        return "approvals"
    if name == "review.json":
        return "reviews"
    if name.startswith("review-contract") and name.endswith(".json"):
        return "review_contracts"
    if name.startswith("batch-contract") and name.endswith(".json"):
        return "batch_contracts"
    if name.startswith("dispatch") and name.endswith(".json"):
        return "dispatches"
    if name == "queue.json":
        return "dispatches"
    return path.parent.name


def _checked_invalidation_path(path: Path, agent_root: Path) -> Path:
    try:
        if path.is_symlink():
            raise ValueError(f"invalidation scan encountered symlink: {path}")
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise ValueError(f"invalidation scan cannot resolve path: {path}") from exc
    try:
        relative = resolved.relative_to(agent_root)
    except ValueError as exc:
        raise ValueError(f"invalidation scan path escapes .agent: {path}") from exc
    if len(relative.parts) > MAX_INVALIDATION_DEPTH:
        raise ValueError("invalidation scan relative depth limit exceeded")
    return resolved


def _sorted_entries(directory: Path, agent_root: Path) -> list[Path]:
    checked = _checked_invalidation_path(directory, agent_root)
    if not checked.exists():
        return []
    if not checked.is_dir():
        raise ValueError(f"invalidation scan root is not a directory: {directory}")
    try:
        entries = sorted(checked.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise ValueError(f"invalidation scan cannot read directory: {directory}") from exc
    return [_checked_invalidation_path(entry, agent_root) for entry in entries]


def _work_json_paths(directory: Path, agent_root: Path) -> Iterator[Path]:
    for entry in _sorted_entries(directory, agent_root):
        if entry.is_dir():
            if entry.name.lower() == "recovery":
                continue
            yield from _work_json_paths(entry, agent_root)
        elif entry.is_file() and entry.suffix == ".json":
            name = entry.name.lower()
            if (
                name == "review.json"
                or (name.startswith("review-contract") and name.endswith(".json"))
                or (name.startswith("batch-contract") and name.endswith(".json"))
                or (name.startswith("dispatch") and name.endswith(".json"))
            ):
                yield entry


def _invalidation_candidates(root: Path) -> Iterator[Path]:
    for entry in _sorted_entries(root / "approvals", root):
        if entry.is_file() and entry.suffix == ".json":
            yield entry
    yield from _work_json_paths(root / "work", root)
    for entry in _sorted_entries(root / "runtime", root):
        if entry.name == "queue.json" and entry.is_file():
            yield entry


def _find_invalidations(
    project_root: Path,
    *,
    old_revision: int,
    old_hash: str,
    change_request_id: str,
) -> list[tuple[Path, dict[str, Any], str]]:
    agent_path = project_root / ".agent"
    if agent_path.is_symlink():
        raise ValueError("invalidation scan encountered symlink at .agent root")
    root = agent_path.resolve(strict=False)
    _checked_invalidation_path(root, root)
    invalidations: list[tuple[Path, dict[str, Any], str]] = []
    candidate_count = 0
    for path in _invalidation_candidates(root):
        candidate_count += 1
        if candidate_count > MAX_INVALIDATION_ARTIFACTS:
            raise ValueError("invalidation scan artifact count limit exceeded")
        try:
            value = read_object(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalidation candidate unreadable: {path}") from exc
        if not _contains_old_binding(value, old_revision, old_hash):
            continue
        updated = copy.deepcopy(value)
        updated["invalidated"] = True
        updated["invalidated_at"] = utc_now()
        updated["invalidation_change_request_id"] = change_request_id
        updated["invalidation_target_revision"] = old_revision
        updated["invalidation_target_hash"] = old_hash
        invalidations.append((path, updated, _artifact_category(path, root)))
    return invalidations


def _prepare_invalidation_events(
    project_root: Path,
    invalidations: list[tuple[Path, dict[str, Any], str]],
    *,
    change_request_id: str,
    old_revision: int,
    old_hash: str,
    actor_id: str,
) -> tuple[str | None, int]:
    if not invalidations:
        return None, len(iter_events(project_root / ".agent" / "runtime" / "events.jsonl"))
    root = (project_root / ".agent").resolve()
    existing = iter_events(root / "runtime" / "events.jsonl")
    staged: list[dict[str, Any]] = []
    for path, _, artifact_type in invalidations:
        event = {
            "event_id": next_event_id([*existing, *staged]),
            "timestamp": utc_now(),
            "type": "ARTIFACT_INVALIDATED",
            "actor": actor_id,
            "data": {
                "artifact_path": path.relative_to(root).as_posix(),
                "artifact_category": artifact_type,
                "artifact_type": artifact_type,
                "change_request_id": change_request_id,
                "old_revision": old_revision,
                "old_hash": old_hash,
                "target_revision": old_revision,
                "target_hash": old_hash,
            },
        }
        staged.append(event)
    _, revision, content, _ = prepare_event_log(root, staged[-1], prior_events=staged[:-1])
    return content, revision


def _initialized_project_for(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        runtime = candidate / ".agent" / "runtime"
        if (runtime / "state.json").is_file() and (runtime / "events.jsonl").is_file():
            return candidate
    return None


def _write_plan_transactionally(
    output_path: Path,
    new_plan: dict[str, Any],
    *,
    historical_path: Path | None = None,
    historical_value: dict[str, Any] | None = None,
    invalidations: list[tuple[Path, dict[str, Any], str]] | None = None,
    event_content: str | None = None,
    event_revision: int | None = None,
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
    invalidations = invalidations or []
    target_values: dict[str, tuple[Path, dict[str, Any]]] = {
        _relative_target_path(resolved_project, resolved_output): (resolved_output, new_plan),
    }
    if historical_path is not None:
        if historical_value is None:
            raise ValueError("historical_value is required with historical_path")
        resolved_historical = historical_path.resolve(strict=False)
        target_values[_relative_target_path(resolved_project, resolved_historical)] = (resolved_historical, historical_value)
    for path, value, _ in invalidations:
        target_values[_relative_target_path(resolved_project, path)] = (path.resolve(strict=False), value)
    expected_revisions: dict[str, int] = {}
    for relative, (path, _) in target_values.items():
        current_revision = 0
        if path.is_file():
            try:
                current = read_object(path)
                revision = current.get("revision")
                if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 1:
                    current_revision = revision
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        expected_revisions[relative] = current_revision
    event_relative = "runtime/events.jsonl"
    if event_content is not None:
        if event_revision is None:
            raise ValueError("event_revision is required with event_content")
        expected_revisions[event_relative] = event_revision
    content_hash = artifact_hash(new_plan)
    transaction = RuntimeTransaction(
        project_root,
        operation_type="PLAN_CHANGE",
        idempotency_key=f"plan-change:{new_plan['change_request_id']}:{new_plan['version']}:{content_hash}",
        expected_revisions=expected_revisions,
    )
    target_files = sorted([*target_values, *([event_relative] if event_content is not None else [])])
    transaction.prepare(target_files)
    output_relative = _relative_target_path(resolved_project, resolved_output)
    transaction.stage_text(output_relative, json.dumps(new_plan, ensure_ascii=False, indent=2) + "\n")
    if historical_path is not None:
        historical_relative = _relative_target_path(resolved_project, historical_path)
        transaction.stage_text(historical_relative, json.dumps(historical_value, ensure_ascii=False, indent=2) + "\n")
    for path, value, _ in invalidations:
        transaction.stage_text(_relative_target_path(resolved_project, path), json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    if event_content is not None:
        transaction.stage_text(event_relative, event_content)
    transaction.commit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--actor", default="primary-agent")
    parser.add_argument("--actor-type", choices=("user", "primary_agent", "agent", "service"), default="primary_agent")
    args = parser.parse_args()
    try:
        request = read_payload(args.request)
        approval = read_object(args.approval)
        target_path = Path(args.target).resolve()
        output_path = Path(args.output).resolve()
        if target_path == output_path:
            raise ValueError("historical target and new plan output must be different files")
        target = read_object(target_path)
        record = validate_change_request(request, approval, applying=True, target=target)
        project_root = _initialized_project_for(output_path.parent) or _initialized_project_for(target_path.parent)
        if project_root is None:
            raise ValueError("runtime is not initialized; run init_runtime.py first")
        try:
            target_path.relative_to(project_root)
            output_path.relative_to(project_root)
        except ValueError as exc:
            raise ValueError("target and output must remain inside one project root") from exc
        target_id_field = TARGET_ID_FIELDS[record["target_type"]]
        if target.get(target_id_field) != record["target_id"] or str(target.get("version")) != record["target_version"]:
            raise ValueError("target plan does not match change request target and version")
        old_revision = _artifact_revision(target)
        old_hash = _artifact_target_hash(target)
        target_snapshot = {
            "target_type": record["target_type"],
            "target_id": record["target_id"],
            "revision": old_revision,
            "target_hash": old_hash,
        }
        require_persisted_approval(
            project_root / ".agent",
            approval,
            target_type=record["target_type"],
            target_id=record["target_id"],
        )
        authorize(
            "CHANGE_REQUEST",
            target_snapshot,
            approval,
            actor={"actor_type": args.actor_type, "actor_id": args.actor},
        )
        operations = validate_operations(record["requested_changes"], applying=True)
        new_plan = apply_operations(copy.deepcopy(target), copy.deepcopy(operations))
        new_plan["version"] = record["new_version"]
        new_plan["supersedes_id"] = record["supersedes_id"]
        new_plan["change_request_id"] = record["change_request_id"]
        new_plan["change_status"] = "APPLIED"
        new_plan["applied_at"] = utc_now()
        new_plan["requested_changes"] = operations
        if isinstance(old_revision, int) and not isinstance(old_revision, bool) and old_revision >= 1:
            new_plan["revision"] = old_revision + 1
        else:
            new_plan["revision"] = 1
        if isinstance(new_plan.get("master_plan"), dict):
            new_plan["master_plan"]["revision"] = new_plan["revision"]
        for stale_field in ("approval_id", "review_id", "review_verdict", "accepted", "approval_references"):
            new_plan.pop(stale_field, None)
        new_plan["invalidated_artifacts"] = ["approvals", "reviews", "batch_contracts", "dispatches"]
        new_plan["artifact_hash"] = artifact_hash(new_plan)
        historical_value = copy.deepcopy(target)
        invalidations = _find_invalidations(
            project_root,
            old_revision=old_revision,
            old_hash=old_hash,
            change_request_id=record["change_request_id"],
        )
        invalidations = [
            item for item in invalidations if item[0].resolve() != target_path.resolve()
        ]
        if record["target_type"] == "TASK":
            invalidated_at = utc_now()
            historical_value.update({
                "status": "SUPERSEDED",
                "superseded_by_revision": new_plan["revision"],
                "superseded_by_hash": new_plan["artifact_hash"],
                "invalidated": True,
                "invalidated_at": invalidated_at,
                "invalidation_change_request_id": record["change_request_id"],
                "invalidation_target_revision": old_revision,
                "invalidation_target_hash": old_hash,
                "invalidated_artifacts": ["approvals", "reviews", "batch_contracts", "dispatches"],
            })
        event_content, event_revision = _prepare_invalidation_events(
            project_root,
            invalidations,
            change_request_id=record["change_request_id"],
            old_revision=old_revision,
            old_hash=old_hash,
            actor_id=args.actor,
        )
        _write_plan_transactionally(
            output_path,
            new_plan,
            historical_path=target_path,
            historical_value=historical_value,
            invalidations=invalidations,
            event_content=event_content,
            event_revision=event_revision,
            project_root=project_root,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"CHANGE_APPLY_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(new_plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
