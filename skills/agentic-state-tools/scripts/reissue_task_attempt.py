"""Atomically issue a new execution identity for a recoverable task."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from append_event import append_event_for_root
from dispatch_transaction import _append_operation
from render_checklist import render_checklist_for_root
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    read_object,
    read_payload,
    lease_expiry,
    runtime_lock,
    utc_now,
    write_json_atomic,
    write_text_atomic,
)
from task_state_contract import validate_execution_identity
from validate_payload import validate
from write_artifact import write_validated
from redaction import redaction_mode, sanitize_for_persistence
from secret_scanner import context_security_errors


ROOT = Path(__file__).resolve().parents[1]
CONFIG_SKILL = ROOT.parent / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))
from load_config import load_config, load_deployment_config  # noqa: E402


SCHEMA = ROOT / "schemas/attempt-reissue.schema.json"
TASK_SCHEMA = ROOT / "schemas/task-state.schema.json"
LEASE_SCHEMA = ROOT / "schemas/lease.schema.json"
ALLOWED_STATUSES = {"REPAIR_REQUIRED", "STALE", "RECOVERY_PENDING"}
CONTEXT_SCHEMA = ROOT / "schemas/context.schema.json"
PRIVATE_CONTEXT_KEYS = {
    "chain_of_thought",
    "private_reasoning",
    "private_chain_of_thought",
    "confidence",
    "confidence_statement",
    "internal_reasoning",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _meaningful_context_delta(delta: Any) -> bool:
    if not isinstance(delta, dict) or not delta:
        return False
    recognized = {"corrected_contract", "added_context", "removed_context", "decomposition", "model_escalation", "approved_decision", "debugging_evidence", "summary"}
    return any(key in recognized and value not in (None, "", [], {}, False) for key, value in delta.items())


def _contains_private_context_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.casefold().replace("-", "_").replace(" ", "_") if isinstance(key, str) else ""
            if normalized in PRIVATE_CONTEXT_KEYS or _contains_private_context_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_private_context_key(item) for item in value)
    return False


def _sanitize_context_delta(delta: Any, config: dict[str, Any]) -> dict[str, Any]:
    if not _meaningful_context_delta(delta):
        raise ValueError("reissue requires a meaningful context_delta")
    if _contains_private_context_key(delta):
        raise ValueError("context_delta must not contain private reasoning or confidence statements")
    policy = config.get("security", {}).get("redaction_mode", "REJECT")
    sanitized, _ = sanitize_for_persistence(delta, mode=redaction_mode(policy))
    errors = context_security_errors(sanitized, max_bytes=config["context_budget"]["max_bytes"])
    if errors:
        raise ValueError("context_delta contains sensitive or unsafe content: " + "; ".join(errors))
    if not isinstance(sanitized, dict) or not sanitized:
        raise ValueError("context_delta must remain a non-empty object")
    return sanitized


def _resolve_model_dispatch(model_ref: str, current_dispatch: dict[str, Any], config: dict[str, Any], deployment_path: str | None) -> str:
    allowed = set(config["model_policy"]["allowed_model_refs"])
    forbidden = set(config["model_policy"]["forbidden_model_refs"])
    if model_ref not in allowed or model_ref in forbidden:
        raise ValueError("model_ref is not allowed by the active model policy")
    deployment = load_deployment_config(deployment_path, config)
    model_ids = deployment.get("model_ids", {})
    provider_model = model_ids.get(model_ref) if isinstance(model_ids, dict) else None
    if not isinstance(provider_model, str) or not provider_model.strip():
        raise ValueError("model_ref is not resolved by the deployment overlay")
    agent_role = current_dispatch.get("agent_role")
    if not isinstance(agent_role, str) or not agent_role.strip():
        raise ValueError("model_ref requires a role-bound current dispatch")
    agent = config.get("agents", {}).get(agent_role)
    if not isinstance(agent, dict) or agent.get("model_ref") != model_ref:
        raise ValueError("model_ref does not match the configured dispatch role")
    return provider_model


def _context_identity(context: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(context.get(field) for field in ("run_id", "attempt_id", "dispatch_id"))


def _context_history_snapshot(root: Path, task_id: str) -> dict[Path, bytes | None]:
    context_path = root / "work" / task_id / "context.json"
    return {context_path: context_path.read_bytes() if context_path.is_file() else None}


def _restore_context_snapshot(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def _validate_payload(payload: object, cli_expected_revision: int | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("attempt reissue must be an object")
    normalized = dict(payload)
    if cli_expected_revision is not None:
        payload_expected_revision = normalized.get("expected_revision")
        if payload_expected_revision is not None and payload_expected_revision != cli_expected_revision:
            raise ValueError("--expected-revision does not match payload.expected_revision")
        normalized["expected_revision"] = cli_expected_revision
    errors = validate(normalized, read_object(SCHEMA))
    if errors:
        raise ValueError("invalid attempt reissue: " + "; ".join(errors))
    return normalized


def _replace_identity(record: dict[str, Any], task_id: str, identity: dict[str, str]) -> None:
    if record.get("task_id") == task_id:
        record.update(identity)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--deployment")
    parser.add_argument("--actor", default="agentic-state-tools")
    args = parser.parse_args()
    target = None
    try:
        config = load_config()
        payload = _validate_payload(read_payload(args.input), args.expected_revision)
        task_id = payload["task_id"]
        expected_revision = payload["expected_revision"]
        with runtime_lock(args.project_root) as root:
            task_path = root / "work" / task_id / "task-state.json"
            queue_path = root / "runtime" / "queue.json"
            lease_path = root / "work" / task_id / "lease.json"
            if not task_path.is_file() or not queue_path.is_file():
                raise ValueError("reissue requires current task and queue artifacts")
            current = read_object(task_path)
            current_revision = current.get("revision", 0)
            if expected_revision is not None and expected_revision != current_revision:
                raise ValueError(f"stale revision: expected {expected_revision}, current {current_revision}")
            status = str(current.get("status", "")).upper()
            if status not in ALLOWED_STATUSES:
                raise ValueError(f"task status is not reissuable: {status}")
            context_path = root / "work" / task_id / "context.json"
            current_context = read_object(context_path) if context_path.is_file() else None
            context_delta = payload.get("context_delta")
            if current_context is None:
                raise ValueError("reissue requires an existing context package; create a fresh context before reissue")
            context_delta = _sanitize_context_delta(context_delta, config)
            if current_context is not None:
                previous_delta = current_context.get("context_delta")
                current_model = current_context.get("model_ref")
                requested_model = payload.get("model_ref", current_model)
                if _canonical(context_delta) == _canonical(previous_delta) and requested_model == current_model:
                    raise ValueError("reissue repeats the same context payload for the same model")
            for field in ("run_id", "attempt_id", "dispatch_id"):
                if not isinstance(current.get(field), str) or not current[field].strip():
                    raise ValueError(f"current task is missing {field}")

            queue = read_object(queue_path)
            identity = {
                "run_id": payload["new_run_id"],
                "attempt_id": payload["new_attempt_id"],
                "dispatch_id": payload["new_dispatch_id"],
            }
            task_records = [record for record in queue.get("tasks", []) if isinstance(record, dict) and record.get("task_id") == task_id]
            state_records = [record for record in queue.get("task_states", []) if isinstance(record, dict) and record.get("task_id") == task_id]
            dispatch_records = [record for record in queue.get("dispatches", []) if isinstance(record, dict) and record.get("task_id") == task_id]
            if not task_records or not state_records or not dispatch_records:
                raise ValueError("reissue requires task, task-state, and dispatch queue bindings")
            current_dispatch_records = [record for record in dispatch_records if record.get("dispatch_id") == current["dispatch_id"]]
            if len(current_dispatch_records) != 1:
                raise ValueError("reissue requires exactly one current dispatch queue binding")
            current_dispatch = current_dispatch_records[0]
            selected_model = None
            if payload.get("model_ref"):
                selected_model = _resolve_model_dispatch(payload["model_ref"], current_dispatch, config, args.deployment)
            for field, value in identity.items():
                if any(record.get(field) == value for record in dispatch_records):
                    raise ValueError(f"reissue {field} already exists in task dispatch history")

            old_queue = json.loads(json.dumps(queue))
            old_task = json.loads(json.dumps(current))
            old_context = _context_history_snapshot(root, task_id)
            if current_context is not None:
                next_context_id = f"CTX-{task_id}-{identity['attempt_id']}"
                history_path = root / "work" / task_id / "contexts" / f"{next_context_id}.json"
                old_context[history_path] = history_path.read_bytes() if history_path.is_file() else None
            old_lease = read_object(lease_path) if lease_path.is_file() else None
            event_path = root / "runtime/events.jsonl"
            state_path = root / "runtime/state.json"
            checklist_path = root / "checklist.md"
            old_events = event_path.read_text(encoding="utf-8")
            old_state = state_path.read_text(encoding="utf-8")
            old_checklist = checklist_path.read_text(encoding="utf-8") if checklist_path.is_file() else None
            operation_id = f"OP-{task_id}-REISSUE-{uuid.uuid4().hex[:12].upper()}"
            idempotency_key = f"{task_id}:reissue:r{current_revision + 1}"
            operation = {
                "operation_id": operation_id,
                "task_id": task_id,
                "run_id": identity["run_id"],
                "type": "OTHER",
                "status": "STARTED",
                "command": "REISSUE_TASK_ATTEMPT",
                "actor": args.actor,
                "result_summary": payload["reason"],
            }
            _append_operation(root, task_id, operation)
            try:
                next_task = dict(current)
                next_task.update({"status": "QUEUED_SYNC", "previous_revision": current_revision, "revision": current_revision + 1, "updated_at": utc_now(), **identity})
                next_dispatch = json.loads(json.dumps(current_dispatch))
                next_dispatch.update({**identity, "task_revision": next_task["revision"], "idempotency_key": idempotency_key, "operation_id": operation_id})
                if selected_model is not None:
                    next_dispatch["selected_model"] = selected_model
                write_validated(str(args.project_root), f"work/{task_id}/task-state.json", next_task, TASK_SCHEMA)
                for collection in (queue["tasks"], queue["task_states"]):
                    for record in collection:
                        if isinstance(record, dict) and record.get("task_id") == task_id:
                            _replace_identity(record, task_id, identity)
                            record["revision"] = next_task["revision"]
                            if record in queue["tasks"]:
                                record["queue_state"] = "DISPATCHED"
                            if record in queue["task_states"]:
                                record["status"] = "QUEUED_SYNC"
                queue["dispatches"].append(next_dispatch)
                queue["revision"] = int(queue.get("revision", 0)) + 1
                write_json_atomic(queue_path, queue)

                lease = dict(old_lease or {})
                lease_seconds = int(lease.get("lease_seconds", 300))
                lease.update({"task_id": task_id, "owner": lease.get("owner", "executor"), "run_id": identity["run_id"], "attempt_id": identity["attempt_id"], "dispatch_id": identity["dispatch_id"], "task_revision": next_task["revision"], "acquired_at": utc_now(), "last_heartbeat": utc_now(), "lease_seconds": lease_seconds, "expires_at": lease_expiry(lease_seconds)})
                write_validated(str(args.project_root), f"work/{task_id}/lease.json", lease, LEASE_SCHEMA)
                if current_context is not None:
                    next_context = copy.deepcopy(current_context)
                    previous_context_id = next_context.get("context_id")
                    next_context.update({
                        "context_id": f"CTX-{task_id}-{identity['attempt_id']}",
                        "created_at": utc_now(),
                        "revision": int(next_context.get("revision", 0)) + 1,
                        "context_revision": int(next_context.get("context_revision", next_context.get("revision", 0))) + 1,
                        "previous_context_id": previous_context_id,
                        "context_delta": context_delta,
                        "run_id": identity["run_id"],
                        "attempt_id": identity["attempt_id"],
                        "dispatch_id": identity["dispatch_id"],
                    })
                    if payload.get("model_ref"):
                        next_context["model_ref"] = payload["model_ref"]
                    write_validated(str(args.project_root), f"work/{task_id}/context.json", next_context, CONTEXT_SCHEMA)
                    write_validated(str(args.project_root), f"work/{task_id}/contexts/{next_context['context_id']}.json", next_context, CONTEXT_SCHEMA)
                current_queue = dict(queue)
                current_queue["dispatches"] = [next_dispatch]
                validate_execution_identity(next_task, lease, current_queue)
                append_event_for_root(root, {"type": "OPERATION_RECORDED", "actor": args.actor, "task_id": task_id, "run_id": identity["run_id"], "data": {"operation": "REISSUE_TASK_ATTEMPT", "operation_id": operation_id, "attempt_id": identity["attempt_id"], "dispatch_id": identity["dispatch_id"]}})
                append_event_for_root(root, {"type": "TASK_QUEUED_SYNC", "actor": args.actor, "task_id": task_id, "run_id": identity["run_id"], "data": {"operation": "REISSUE_TASK_ATTEMPT", "attempt_id": identity["attempt_id"], "dispatch_id": identity["dispatch_id"], "reason": payload["reason"], "context_delta": context_delta}})
                _append_operation(root, task_id, {**operation, "status": "COMPLETED", "phase": "COMMIT", "commit_marker": operation_id, "result_summary": "task attempt reissued"})
                render_checklist_for_root(root)
                target = task_path
            except Exception:
                write_json_atomic(queue_path, old_queue)
                write_validated(str(args.project_root), f"work/{task_id}/task-state.json", old_task, TASK_SCHEMA)
                _restore_context_snapshot(old_context)
                if old_lease is None:
                    if lease_path.is_file():
                        lease_path.unlink()
                else:
                    write_validated(str(args.project_root), f"work/{task_id}/lease.json", old_lease, LEASE_SCHEMA)
                write_text_atomic(event_path, old_events)
                write_text_atomic(state_path, old_state)
                if old_checklist is not None:
                    write_text_atomic(checklist_path, old_checklist)
                try:
                    _append_operation(root, task_id, {**operation, "status": "FAILED", "phase": "ROLLBACK", "rollback_marker": operation_id, "result_summary": "task attempt reissue failed"})
                except Exception:
                    pass
                raise
    except RuntimeNotInitializedError as exc:
        print(f"TASK_REISSUE_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"TASK_REISSUE_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"TASK_ATTEMPT_REISSUED: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
