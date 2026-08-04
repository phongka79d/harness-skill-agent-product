"""Persist an evidence-based task review and apply the reviewer-only state outcome."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from calculate_rubric_score import calculate, validate_rubric_identity
from rebuild_state import rebuild_state_for_root
from render_checklist import render_checklist
from review_contract import validate_rubric_against_contract
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    STATUS_TO_EVENT_TYPE,
    assert_terminal_cleanup_safe,
    cleanup_task_runtime,
    inspect_terminal_cleanup,
    prepare_event_log,
    read_object,
    read_payload,
    runtime_lock,
    next_revision,
    utc_now,
    validate_identifier,
)
from validate_transition import is_allowed_transition
from runtime_transaction import RuntimeTransaction, TransactionError


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
    parser.add_argument("--rubric", help="resolved rubric JSON file")
    parser.add_argument("--actor", default="task-reviewer")
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
        if not isinstance(payload, dict) or not isinstance(payload.get("task_id"), str) or not payload["task_id"]:
            raise ValueError("review requires a non-empty string task_id")
        payload = dict(payload)
        if args.rubric:
            payload["resolved_rubric"] = read_object(args.rubric)
        resolved_rubric = payload.get("resolved_rubric")
        if not isinstance(resolved_rubric, dict) and payload.get("legacy_migration") is not True:
            raise ValueError("new reviews require resolved_rubric; set legacy_migration=true only for existing legacy evidence")
        if isinstance(resolved_rubric, dict):
            for field in ("rubric_id", "rubric_version", "rubric_hash", "resolved_weights", "applicability"):
                if field in resolved_rubric:
                    payload[field] = resolved_rubric[field]
        task_id = payload["task_id"]
        validate_identifier(task_id, "task_id")

        with runtime_lock(args.project_root) as root:
            task_path = root / "work" / task_id / "task-state.json"
            if not task_path.is_file():
                raise ValueError(f"task state does not exist for {task_id}")
            task_state = read_object(task_path)
            current_status = str(task_state.get("status", "")).upper()
            existing_review_path = root / "work" / task_id / "review.json"
            existing_revision = int(read_object(existing_review_path).get("revision", 0)) if existing_review_path.is_file() else 0

            if isinstance(resolved_rubric, dict):
                if payload.get("legacy_migration") is not True:
                    task_contract = task_state.get("review_contract")
                    if not isinstance(task_contract, dict):
                        raise ValueError("new reviews require a pinned task review_contract")
                    validate_rubric_against_contract(resolved_rubric, task_contract, review_type="task")
                    payload["review_contract"] = task_contract
                validate_rubric_identity(resolved_rubric)
                approval_id = resolved_rubric.get("override_approval_id")
                if approval_id:
                    matching: list[dict] = []
                    for approval_path in sorted((root / "approvals").glob("*.json")):
                        try:
                            approval = read_object(approval_path)
                        except (OSError, ValueError):
                            continue
                        if approval.get("approval_id") == approval_id:
                            matching.append(approval)
                    if not matching or str(matching[0].get("decision", "")).upper() != "APPROVED":
                        raise ValueError("resolved rubric override requires an APPROVED approval artifact")

            payload.setdefault("review_id", f"REV-{task_id}-{existing_revision + 1}")
            payload["revision"] = next_revision(payload, existing_revision)
            payload["created_at"] = utc_now()
            payload["reviewer"] = args.actor
            payload.update(calculate(payload))
            verdict = payload["verdict"]
            next_status = "ACCEPTED" if verdict == "PASS" else "BLOCKED" if verdict == "BLOCKED" else "REPAIR_REQUIRED"
            if not is_allowed_transition(current_status, next_status, actor="reviewer"):
                raise ValueError(f"invalid reviewer transition: {current_status} -> {next_status}")
            if next_status in {"ACCEPTED", "CANCELLED", "SUPERSEDED"}:
                assert_terminal_cleanup_safe(root, task_id)

            next_task_state = dict(task_state)
            previous_revision = int(next_task_state.get("revision", 0))
            next_task_state.update(
                {
                    "status": next_status,
                    "previous_revision": previous_revision,
                    "revision": previous_revision + 1,
                    "updated_at": utc_now(),
                    "review_id": payload["review_id"],
                    "review_verdict": verdict,
                }
            )
            if next_status in {"ACCEPTED", "CANCELLED", "SUPERSEDED"}:
                next_task_state["next_action"] = "none"
            elif "next_action" not in task_state:
                next_task_state.pop("next_action", None)
            review_relative = f"work/{task_id}/review.json"
            task_relative = f"work/{task_id}/task-state.json"
            event_overrides = {review_relative: payload, task_relative: next_task_state}
            review_event_relative, event_revision, event_content, review_event = prepare_event_log(
                root,
                {
                    "type": "REVIEW_CREATED",
                    "actor": args.actor,
                    "task_id": task_id,
                    "data": {"review_id": payload["review_id"]},
                },
                artifact_overrides=event_overrides,
            )
            _, event_revision, event_content, _ = prepare_event_log(
                root,
                {
                    "type": STATUS_TO_EVENT_TYPE[next_status],
                    "actor": args.actor,
                    "task_id": task_id,
                    "data": {"review_id": payload["review_id"]},
                },
                artifact_overrides=event_overrides,
                prior_events=[review_event],
            )
            transaction = RuntimeTransaction(
                args.project_root,
                operation_type="REVIEW",
                idempotency_key=f"review:{task_id}:{payload['review_id']}:{payload['revision']}",
                expected_revisions={
                    review_relative: existing_revision,
                    task_relative: previous_revision,
                    review_event_relative: event_revision,
                },
            )
            transaction.prepare([review_relative, task_relative, review_event_relative])
            transaction.stage_json(review_relative, payload, Path(__file__).resolve().parents[1] / "schemas/review.schema.json")
            transaction.stage_json(task_relative, next_task_state, Path(__file__).resolve().parents[1] / "schemas/task-state.schema.json")
            transaction.stage_text(review_event_relative, event_content)
            transaction.commit()
            review_target = root / "work" / task_id / "review.json"
            task_target = root / "work" / task_id / "task-state.json"
            cleanup = cleanup_task_runtime(root, task_id) if next_status in {"ACCEPTED", "CANCELLED", "SUPERSEDED"} else {"leases": [], "locks": []}
            if next_status in {"ACCEPTED", "CANCELLED", "SUPERSEDED"}:
                post_cleanup = inspect_terminal_cleanup(root, task_id)
                if not post_cleanup["valid"]:
                    raise ValueError("terminal cleanup could not be verified: " + "; ".join(post_cleanup["reasons"]))
            append_cleanup_events(root, args.project_root, task_id, cleanup)
            rebuild_state_for_root(root)
            render_checklist(args.project_root, acquire_lock=False)
    except RuntimeNotInitializedError as exc:
        print(f"REVIEW_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except CleanupRecoveryError as exc:
        print(json.dumps(exc.evidence, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    except (RuntimeLockedError, TransactionError, OSError, ValueError, TypeError) as exc:
        print(f"REVIEW_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"REVIEW_WRITTEN: {review_target}; TASK_STATE_WRITTEN: {task_target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
