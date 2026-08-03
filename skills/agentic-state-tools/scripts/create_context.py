"""Validate and persist one bounded task context package."""

from __future__ import annotations

import argparse
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
)
from write_artifact import write_validated
from secret_scanner import context_security_errors


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/context.schema.json"
CONFIG_SKILL = Path(__file__).resolve().parents[2] / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))

from load_config import load_config, validate_config  # noqa: E402


BUDGET_FIELDS = ("max_files", "max_reference_documents", "max_examples", "max_review_history_items", "max_bytes")
MISSING = object()


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


def normalize(payload: Any, config: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("context must be an object")
    config = load_config() if config is None else validate_config(config)
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
    result["budget"] = budget
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="context-builder")
    args = parser.parse_args()
    try:
        payload = normalize(read_payload(args.input), load_config())
        task_id = payload["task"]["task_id"]
        with runtime_lock(args.project_root) as root:
            existing_path = root / "work" / task_id / "context.json"
            existing_revision = int(read_object(existing_path).get("revision", 0)) if existing_path.is_file() else 0
            record = dict(payload)
            record["context_id"] = record.get("context_id") or f"CTX-{task_id}-{existing_revision + 1}"
            record["created_at"] = utc_now()
            record["revision"] = next_revision(record, existing_revision)
            target = write_validated(args.project_root, f"work/{task_id}/context.json", record, SCHEMA)
            append_event_for_root(
                root,
                {
                    "type": "CONTEXT_CREATED",
                    "actor": args.actor,
                    "task_id": task_id,
                    "data": {"context_id": record["context_id"], "revision": record["revision"]},
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
