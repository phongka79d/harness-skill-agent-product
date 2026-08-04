"""Validate and atomically update one executor-owned task-state artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from rebuild_state import rebuild_state_for_root
from render_checklist import render_checklist
from review_contract import validate_contract
from task_state_contract import merge_task_state, validate_execution_identity
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    STATUS_TO_EVENT_TYPE,
    TERMINAL_STATUSES,
    assert_terminal_cleanup_safe,
    cleanup_task_runtime,
    inspect_terminal_cleanup,
    prepare_event_log,
    read_object,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
)
from validate_transition import is_allowed_transition
from runtime_transaction import RuntimeTransaction, TransactionError


INITIAL_STATUSES = {"PENDING", "READY", "QUEUED", "QUEUED_ASYNC", "QUEUED_SYNC"}
QUEUE_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/queue.schema.json"
LEASE_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/lease.schema.json"
QUEUE_STATE_BY_STATUS = {"QUEUED": "DISPATCHED", "QUEUED_ASYNC": "DISPATCHED", "QUEUED_SYNC": "DISPATCHED"}


def synchronize_queue(queue: dict, next_state: dict) -> dict:
    task_id = next_state["task_id"]
    revision = next_state["revision"]
    changed = False
    for collection_name in ("tasks", "task_states"):
        collection = queue.get(collection_name)
        if not isinstance(collection, list):
            continue
        for record in collection:
            if not isinstance(record, dict) or record.get("task_id") != task_id:
                continue
            changed = True
            record["revision"] = revision
            for field in ("run_id", "attempt_id", "dispatch_id"):
                if field in next_state:
                    record[field] = next_state[field]
            if collection_name == "tasks":
                next_queue_state = QUEUE_STATE_BY_STATUS.get(next_state["status"])
                if next_queue_state is None and next_state["status"] in {
                    "READY", "BLOCKED", "CONFLICTED", "DISPATCHED", "RUNNING",
                    "WAITING", "COMPLETED", "STALE",
                }:
                    next_queue_state = next_state["status"]
                if next_queue_state is not None:
                    record["queue_state"] = next_queue_state
            else:
                record["status"] = next_state["status"]
    dispatch_id = next_state.get("dispatch_id")
    dispatches = queue.get("dispatches")
    if dispatch_id is not None and isinstance(dispatches, list):
        for record in dispatches:
            if isinstance(record, dict) and record.get("task_id") == task_id and record.get("dispatch_id") == dispatch_id:
                changed = True
                record["task_revision"] = revision
                for field in ("run_id", "attempt_id", "dispatch_id"):
                    if field in next_state:
                        record[field] = next_state[field]
                break
    if changed:
        queue["revision"] = int(queue.get("revision", 0)) + 1
    return queue


class CleanupRecoveryError(RuntimeError):
    """A terminal cleanup event could not be durably published."""

    def __init__(self, evidence: dict) -> None:
        self.evidence = evidence
        super().__init__(evidence.get("error", "terminal cleanup recovery is pending"))


def append_cleanup_events(root, project_root: str | Path, task_id: str, cleanup: dict) -> None:
    events = [
        {
            "type": "LEASE_RELEASED",
            "actor": "agentic-state-tools",
            "task_id": task_id,
            "run_id": lease.get("run_id"),
            "data": {"reason": "terminal_task"},
        }
        for lease in cleanup["leases"]
    ]
    events.extend(
        {
            "type": "LOCK_RELEASED",
            "actor": "agentic-state-tools",
            "task_id": task_id,
            "run_id": lock.get("run_id"),
            "data": {
                "lock_id": lock.get("lock_id"),
                "kind": lock.get("kind"),
                "key": lock.get("key"),
                "reason": "terminal_task",
            },
        }
        for lock in cleanup["locks"]
    )
    if not events:
        return

    event_relative = "runtime/events.jsonl"
    idempotency_digest = hashlib.sha256(
        json.dumps(
            {"task_id": task_id, "events": events},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    idempotency_key = f"terminal-cleanup:{task_id}:{idempotency_digest}"
    transaction = None
    try:
        prior_events = []
        event_revision = 0
        event_content = ""
        for event in events:
            event_relative, event_revision, event_content, validated_event = prepare_event_log(
                root,
                event,
                prior_events=prior_events,
            )
            prior_events.append(validated_event)
        transaction = RuntimeTransaction(
            project_root,
            operation_type="TERMINAL_CLEANUP",
            idempotency_key=idempotency_key,
            expected_revisions={event_relative: event_revision},
        )
        transaction.prepare([event_relative])
        transaction.stage_text(event_relative, event_content)
        transaction.commit()
    except Exception as exc:
        evidence = {
            "schema_version": 1,
            "classification": "RECOVERY_PENDING",
            "operation_type": "TERMINAL_CLEANUP",
            "operation_id": transaction.operation_id if transaction is not None else None,
            "idempotency_key": idempotency_key,
            "target_paths": [event_relative],
            "expected_revisions": ({event_relative: event_revision} if "event_revision" in locals() else {}),
            "task_id": task_id,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if transaction is not None:
            evidence["manifest_path"] = str(transaction.manifest_path)
        raise CleanupRecoveryError(evidence) from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="executor")
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
        if not isinstance(payload, dict) or not isinstance(payload.get("task_id"), str) or not payload["task_id"]:
            raise ValueError("task-state requires a non-empty string task_id")
        payload = dict(payload)
        task_id = payload["task_id"]
        validate_identifier(task_id, "task_id")
        requested_status = str(payload.get("status", "")).upper()
        if not requested_status:
            raise ValueError("task-state requires status")
        if requested_status not in STATUS_TO_EVENT_TYPE:
            raise ValueError(f"unsupported task status: {requested_status}")
        if requested_status == "ACCEPTED":
            raise ValueError("only create_review.py may mark a task ACCEPTED")
        if "review_status" in payload:
            raise ValueError("review_status is derived from review.json and cannot be submitted by an executor")

        with runtime_lock(args.project_root) as root:
            target = root / "work" / task_id / "task-state.json"
            current = read_object(target) if target.exists() else None
            current_revision = int(current.get("revision", 0)) if current else 0
            expected = int(payload.pop("expected_revision", current_revision))
            if expected != current_revision:
                raise ValueError(f"stale revision: expected {expected}, current {current_revision}")
            if current:
                current_status = str(current.get("status", "")).upper()
                if not is_allowed_transition(current_status, requested_status, actor="executor"):
                    raise ValueError(f"invalid executor transition: {current_status} -> {requested_status}")
            elif requested_status not in INITIAL_STATUSES:
                raise ValueError(f"initial task status must be one of {sorted(INITIAL_STATUSES)}")

            if requested_status in TERMINAL_STATUSES:
                assert_terminal_cleanup_safe(root, task_id)

            submitted_contract = payload.get("review_contract")
            if current is None and submitted_contract is not None:
                validate_contract(submitted_contract, review_type="task")

            next_state = merge_task_state(current, payload)
            next_state["status"] = requested_status
            if requested_status in TERMINAL_STATUSES:
                next_state["next_action"] = "none"
            next_state["previous_revision"] = current_revision if current else None
            next_state["revision"] = current_revision + 1
            next_state["updated_at"] = utc_now()
            lease_path = root / "work" / task_id / "lease.json"
            queue_path = root / "runtime" / "queue.json"
            lease = read_object(lease_path) if lease_path.is_file() else None
            queue = read_object(queue_path) if queue_path.is_file() else None
            queue_revision = int(queue.get("revision", 0)) if queue is not None else 0
            validate_execution_identity(next_state, lease, queue)
            if lease is not None:
                lease["task_revision"] = next_state["revision"]
                validate_execution_identity(next_state, lease, queue)
            if queue is not None:
                queue = synchronize_queue(queue, next_state)
                validate_execution_identity(next_state, lease, queue)
            transaction_targets = [f"work/{task_id}/task-state.json"]
            transaction_revisions = {f"work/{task_id}/task-state.json": current_revision}
            if lease is not None:
                transaction_targets.append(f"work/{task_id}/lease.json")
                transaction_revisions[f"work/{task_id}/lease.json"] = 0
            if queue is not None:
                transaction_targets.append("runtime/queue.json")
                transaction_revisions["runtime/queue.json"] = queue_revision
            event_relative, event_revision, event_content, _ = prepare_event_log(
                root,
                {
                    "type": STATUS_TO_EVENT_TYPE[requested_status],
                    "actor": args.actor,
                    "task_id": task_id,
                    "data": {"task_revision": next_state["revision"]},
                },
            )
            transaction_targets.append(event_relative)
            transaction_revisions[event_relative] = event_revision
            transaction = RuntimeTransaction(
                args.project_root,
                operation_type="TASK_STATE",
                idempotency_key=f"task-state:{task_id}:{next_state['revision']}",
                expected_revisions=transaction_revisions,
            )
            transaction.prepare(transaction_targets)
            transaction.stage_json(
                f"work/{task_id}/task-state.json",
                next_state,
                Path(__file__).resolve().parents[1] / "schemas/task-state.schema.json",
            )
            if lease is not None:
                transaction.stage_json(f"work/{task_id}/lease.json", lease, LEASE_SCHEMA)
            if queue is not None:
                transaction.stage_json("runtime/queue.json", queue, QUEUE_SCHEMA)
            transaction.stage_text(event_relative, event_content)
            target = root / "work" / task_id / "task-state.json"
            transaction.commit()
            try:
                cleanup = cleanup_task_runtime(root, task_id) if requested_status in TERMINAL_STATUSES else {"leases": [], "locks": []}
                if requested_status in TERMINAL_STATUSES:
                    post_cleanup = inspect_terminal_cleanup(root, task_id)
                    if not post_cleanup["valid"]:
                        raise ValueError("terminal cleanup could not be verified: " + "; ".join(post_cleanup["reasons"]))
                post_lease = read_object(lease_path) if lease_path.is_file() else None
                post_queue = read_object(queue_path) if queue_path.is_file() else None
                validate_execution_identity(next_state, post_lease, post_queue)
                append_cleanup_events(root, args.project_root, task_id, cleanup)
                rebuild_state_for_root(root)
                render_checklist(args.project_root, acquire_lock=False)
            except Exception:
                raise
    except RuntimeNotInitializedError as exc:
        print(f"TASK_STATE_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except CleanupRecoveryError as exc:
        print(json.dumps(exc.evidence, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    except (RuntimeLockedError, TransactionError, OSError, ValueError, TypeError) as exc:
        print(f"TASK_STATE_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"TASK_STATE_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
