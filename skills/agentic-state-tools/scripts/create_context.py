"""Validate and persist one bounded task context package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from append_event import append_event_for_root
from render_checklist import render_checklist_for_root
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    read_object,
    read_payload,
    runtime_lock,
    next_revision,
    utc_now,
    validate_identifier,
    write_text_atomic,
)
from write_artifact import write_validated
from redaction import redaction_mode, sanitize_for_persistence
from secret_scanner import context_security_errors, is_sensitive_path


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/context.schema.json"
CONFIG_SKILL = Path(__file__).resolve().parents[2] / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))

from load_config import load_config, validate_config  # noqa: E402


BUDGET_FIELDS = ("max_files", "max_reference_documents", "max_examples", "max_review_history_items", "max_bytes")
MISSING = object()
PRIVATE_CONTEXT_KEYS = {
    "chain_of_thought",
    "private_reasoning",
    "private_chain_of_thought",
    "confidence",
    "confidence_statement",
    "internal_reasoning",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _source_hash(item: Any) -> str:
    """Return a stable identity hash without persisting source contents."""

    if isinstance(item, dict):
        supplied = item.get("sha256") or item.get("hash")
        if isinstance(supplied, str) and supplied:
            return supplied.lower()
    return hashlib.sha256(_canonical_json(item).encode("utf-8")).hexdigest()


def _validate_new_context_fields(payload: dict[str, Any]) -> None:
    for field in ("context_revision",):
        if field in payload and (isinstance(payload[field], bool) or not isinstance(payload[field], int) or payload[field] < 1):
            raise ValueError(f"context.{field} must be a positive integer")
    for field in ("context_purpose", "recipient_role", "run_id", "attempt_id", "dispatch_id", "model_ref"):
        if field in payload and (not isinstance(payload[field], str) or not payload[field].strip()):
            raise ValueError(f"context.{field} must be a non-empty string")
    identity_present = [field for field in ("run_id", "attempt_id", "dispatch_id") if field in payload]
    if identity_present and len(identity_present) != 3:
        raise ValueError("context run_id, attempt_id, and dispatch_id must be supplied together")
    role = str(payload.get("recipient_role", "")).upper()
    if role == "REVIEWER":
        def contains_private_key(value: Any) -> bool:
            if isinstance(value, dict):
                return any(
                    (isinstance(key, str) and key.casefold().replace("-", "_").replace(" ", "_") in PRIVATE_CONTEXT_KEYS)
                    or contains_private_key(item)
                    for key, item in value.items()
                )
            if isinstance(value, list):
                return any(contains_private_key(item) for item in value)
            return False
        if contains_private_key(payload):
            raise ValueError("reviewer context must not contain private reasoning or confidence statements")
    for field in ("source_items", "source_hashes", "inclusion_reasons", "excluded_sensitive_items"):
        if field in payload and not isinstance(payload[field], list):
            raise ValueError(f"context.{field} must be an array")
    if "source_hashes" in payload:
        for index, value in enumerate(payload["source_hashes"]):
            if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
                raise ValueError(f"context.source_hashes[{index}] must be a SHA-256 hex digest")
    source_items = payload.get("source_items", [])
    for index, item in enumerate(source_items):
        candidates: list[Any] = [item] if isinstance(item, str) else []
        if isinstance(item, dict):
            candidates.extend(item.get(key) for key in ("path", "file", "file_path", "source_path"))
        if any(is_sensitive_path(candidate) for candidate in candidates):
            raise ValueError(f"context.source_items[{index}] contains a sensitive path")
    if "inclusion_reasons" in payload and any(not isinstance(value, str) or not value.strip() for value in payload["inclusion_reasons"]):
        raise ValueError("context.inclusion_reasons must contain non-empty strings")
    if "excluded_sensitive_items" in payload and any(not isinstance(value, str) or not value.strip() for value in payload["excluded_sensitive_items"]):
        raise ValueError("context.excluded_sensitive_items must contain non-empty strings")
    if "forbidden_scope" in payload and (not isinstance(payload["forbidden_scope"], list) or any(not isinstance(value, str) or not value.strip() for value in payload["forbidden_scope"])):
        raise ValueError("context.forbidden_scope must contain non-empty strings")
    previous = payload.get("previous_context_id")
    if previous is not None and (not isinstance(previous, str) or not previous.strip()):
        raise ValueError("context.previous_context_id must be a non-empty string or null")
    delta = payload.get("context_delta")
    if delta is not None and (not isinstance(delta, dict) or not delta):
        raise ValueError("context.context_delta must be a non-empty object or null")


def canonical_budget(payload_budget: Any, config: dict[str, Any]) -> dict[str, int]:
    configured = config["context_budget"]
    if payload_budget is not MISSING and not isinstance(payload_budget, dict):
        raise ValueError("context.budget must be an object when provided")

    budget: dict[str, int] = {}
    for name in BUDGET_FIELDS:
        configured_limit = configured[name]
        requested_limit = payload_budget.get(name, configured_limit) if isinstance(payload_budget, dict) else configured_limit
        if isinstance(requested_limit, bool) or not isinstance(requested_limit, int) or requested_limit < 0 or (name == "max_files" and requested_limit == 0):
            raise ValueError(f"context.budget.{name} must be a valid non-negative integer")
        if requested_limit > configured_limit:
            raise ValueError(f"context.budget.{name} exceeds configured maximum")
        budget[name] = requested_limit
    return budget


def normalize(
    payload: Any,
    config: dict[str, Any] | None = None,
    *,
    redaction_policy: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("context must be an object")
    config = load_config() if config is None else validate_config(config)
    configured_policy = redaction_policy or config.get("security", {}).get("redaction_mode", "REJECT")
    payload, _ = sanitize_for_persistence(payload, mode=redaction_mode(configured_policy))
    task = payload.get("task")
    if not isinstance(task, dict):
        raise ValueError("context.task must be an object")
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("context.task.task_id must be a non-empty string")
    validate_identifier(task_id, "task.task_id")
    if not isinstance(task.get("objective"), str) or not task["objective"].strip():
        raise ValueError("context.task.objective must be a non-empty string")
    required_documents = payload.get("required_documents")
    code_context = payload.get("code_context")
    review_history = payload.get("review_history")
    examples = payload.get("examples", [])
    if not isinstance(required_documents, list) or not isinstance(code_context, dict) or not isinstance(review_history, list) or not isinstance(examples, list):
        raise ValueError("context budget inputs must have the documented object and array shapes")
    _validate_new_context_fields(payload)
    files_to_read = code_context.get("files_to_read")
    if not isinstance(files_to_read, list):
        raise ValueError("context.code_context.files_to_read must be an array")
    budget = canonical_budget(payload.get("budget", MISSING), config)
    if config["security"].get("forbid_secret_storage_in_context", True):
        security_errors = context_security_errors(payload, max_bytes=budget["max_bytes"])
        if security_errors:
            raise ValueError("context contains sensitive or unsafe content: " + "; ".join(security_errors))
    limits = budget
    if len(files_to_read) > limits["max_files"]:
        raise ValueError("context exceeds budget.max_files")
    if len(required_documents) > limits["max_reference_documents"]:
        raise ValueError("context exceeds budget.max_reference_documents")
    if len(review_history) > limits["max_review_history_items"]:
        raise ValueError("context exceeds budget.max_review_history_items")
    if len(examples) > limits["max_examples"]:
        raise ValueError("context exceeds budget.max_examples")
    result = dict(payload)
    result.setdefault("context_revision", 1)
    result.setdefault("context_purpose", "REVIEW" if str(result.get("recipient_role", "")).upper() == "REVIEWER" else "IMPLEMENTATION")
    result.setdefault("recipient_role", "IMPLEMENTER")
    result.setdefault("source_items", [])
    computed_source_hashes = [_source_hash(item) for item in result["source_items"]]
    if "source_hashes" in result and result["source_hashes"] != computed_source_hashes:
        raise ValueError("context.source_hashes do not match source_items")
    result.setdefault("source_hashes", computed_source_hashes)
    if len(result["source_hashes"]) != len(result["source_items"]):
        raise ValueError("context.source_hashes must contain one hash for each source item")
    result.setdefault("inclusion_reasons", ["required by the active task contract"] * len(result["source_items"]))
    if len(result["inclusion_reasons"]) != len(result["source_items"]):
        raise ValueError("context.inclusion_reasons must contain one reason for each source item")
    result.setdefault("excluded_sensitive_items", [])
    result.setdefault("forbidden_scope", [])
    result.setdefault("previous_context_id", None)
    result.setdefault("context_delta", None)
    result["budget"] = budget
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="context-builder")
    parser.add_argument("--redaction-mode", choices=("REJECT", "REDACT"))
    args = parser.parse_args()
    try:
        config = load_config()
        payload = normalize(read_payload(args.input), config, redaction_policy=args.redaction_mode)
        task_id = payload["task"]["task_id"]
        with runtime_lock(args.project_root) as root:
            existing_path = root / "work" / task_id / "context.json"
            existing = read_object(existing_path) if existing_path.is_file() else None
            existing_revision = int(existing.get("revision", 0)) if existing else 0
            if existing:
                identity_fields = ("run_id", "attempt_id", "dispatch_id")
                if any(field not in payload for field in identity_fields):
                    raise ValueError("context must be freshly generated with a new run_id, attempt_id, and dispatch_id")
                existing_attempt = existing.get("attempt_id")
                new_attempt = payload.get("attempt_id")
                if existing_attempt and existing_attempt == new_attempt:
                    raise ValueError("context must be freshly generated for a new attempt")
                if payload.get("context_id") is not None:
                    raise ValueError("context_id must be generated for a new context lineage entry")
                if payload.get("previous_context_id") not in (None, existing.get("context_id")):
                    raise ValueError("context.previous_context_id does not match the current context")
                payload["previous_context_id"] = existing.get("context_id")
                payload["context_revision"] = int(existing.get("context_revision", existing_revision)) + 1
            task_state_path = root / "work" / task_id / "task-state.json"
            if task_state_path.is_file():
                task_state = read_object(task_state_path)
                task_identity_fields = [field for field in ("run_id", "attempt_id", "dispatch_id") if field in task_state]
                if task_identity_fields and len(task_identity_fields) != 3:
                    raise ValueError("active task identity is incomplete")
                if task_identity_fields and any(field not in payload for field in task_identity_fields):
                    raise ValueError("context must include the active task run_id, attempt_id, and dispatch_id")
                for field in ("run_id", "attempt_id", "dispatch_id"):
                    if field in payload and field in task_state and payload[field] != task_state[field]:
                        raise ValueError(f"context.{field} does not match the active task identity")
            elif not existing and payload.get("previous_context_id") is not None:
                raise ValueError("context.previous_context_id requires an existing context")
            record = dict(payload)
            record["context_id"] = record.get("context_id") or f"CTX-{task_id}-{payload.get('attempt_id', existing_revision + 1)}"
            validate_identifier(record["context_id"], "context.context_id")
            record["created_at"] = utc_now()
            record["revision"] = next_revision(record, existing_revision)
            policy = args.redaction_mode or config.get("security", {}).get("redaction_mode")
            record, _ = sanitize_for_persistence(record, mode=redaction_mode(policy))
            target_path = root / "work" / task_id / "context.json"
            history_path = root / "work" / task_id / "contexts" / f"{record['context_id']}.json"
            snapshots = {
                target_path: target_path.read_bytes() if target_path.is_file() else None,
                history_path: history_path.read_bytes() if history_path.is_file() else None,
            }
            try:
                target = write_validated(args.project_root, f"work/{task_id}/context.json", record, SCHEMA)
                write_validated(args.project_root, f"work/{task_id}/contexts/{record['context_id']}.json", record, SCHEMA)
            except Exception:
                for path, content in snapshots.items():
                    if content is None:
                        try:
                            path.unlink()
                        except FileNotFoundError:
                            pass
                    else:
                        write_text_atomic(path, content.decode("utf-8"))
                raise
            append_event_for_root(
                root,
                {
                    "type": "CONTEXT_CREATED",
                    "actor": args.actor,
                    "task_id": task_id,
                    "data": {"context_id": record["context_id"], "revision": record["revision"], "context_revision": record["context_revision"], "recipient_role": record["recipient_role"]},
                },
            )
            render_checklist_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"CONTEXT_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"CONTEXT_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"CONTEXT_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
