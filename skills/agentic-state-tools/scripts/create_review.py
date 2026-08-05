"""Persist an evidence-based task review and apply the reviewer-only state outcome."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from calculate_rubric_score import calculate, validate_rubric_identity
from authorization import authorize, require_persisted_approval
from rebuild_state import rebuild_state_for_root
from render_checklist import render_checklist
from review_contract import (
    canonical_artifact_hash,
    required_review_stages,
    validate_artifact_identity,
    validate_rubric_against_contract,
    validate_stage_chain,
)
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
from validate_transition import is_allowed_transition, validate_transition
from verification_contract import is_strict_profile, workspace_hash
from verify_completion_claim import validate_claim
from runtime_transaction import RuntimeTransaction, TransactionError
from validate_payload import normalize_artifact_version, preserve_projection_links


class CleanupRecoveryError(RuntimeError):
    """A terminal cleanup event could not be durably published."""

    def __init__(self, evidence: dict) -> None:
        self.evidence = evidence
        super().__init__(evidence.get("error", "terminal cleanup recovery is pending"))


def _implementation_artifact_identity(project_root: str | Path, task_state: dict, task_revision: int) -> dict:
    """Build the immutable identity of the implementation snapshot being reviewed."""

    relevant_files = task_state.get("write_scope", [])
    if not isinstance(relevant_files, list):
        relevant_files = []
    identity = {
        "task_id": task_state.get("task_id"),
        "task_revision": task_revision,
        "run_id": task_state.get("run_id"),
        "attempt_id": task_state.get("attempt_id"),
        "dispatch_id": task_state.get("dispatch_id"),
        "workspace_hash": workspace_hash(project_root, relevant_files),
    }
    identity["artifact_hash"] = canonical_artifact_hash(identity)
    return identity


def _authorize_review_override(
    root: Path,
    approval_id: str,
    *,
    expected_target_type: str | None = None,
    expected_target_id: str | None = None,
    expected_target_revision: int | None = None,
    expected_target_hash: str | None = None,
) -> dict:
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise ValueError("resolved rubric override approval_id is required")
    approvals_root = root / "approvals"
    matches: list[dict] = []
    for approval_path in sorted(approvals_root.glob("*.json")):
        if approval_path.is_symlink():
            raise ValueError(f"review override approval scan encountered symlink: {approval_path}")
        try:
            approval = read_object(approval_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(approval, dict) and approval.get("approval_id") == approval_id:
            matches.append(approval)
    if len(matches) != 1:
        raise ValueError("resolved rubric override requires one exact persisted approval artifact")
    approval = matches[0]
    required_fields = (
        "target_type", "target_id", "target_revision", "target_hash", "policy_version",
        "issued_at", "expires_at", "evidence", "actor_type", "actor_id",
    )
    for field in required_fields:
        value = approval.get(field)
        if field == "target_revision":
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("review override approval.target_revision is required")
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(f"review override approval.{field} is required")
    if str(approval.get("decision", "")).upper() != "APPROVED":
        raise ValueError("resolved rubric override requires an APPROVED approval artifact")
    if approval.get("action") != "REVIEW_OVERRIDE":
        raise ValueError("review override approval action must be REVIEW_OVERRIDE")
    if expected_target_type is not None and approval["target_type"] != expected_target_type:
        raise ValueError("review override approval target type does not match")
    if expected_target_id is not None and approval["target_id"] != expected_target_id:
        raise ValueError("review override approval target id does not match")
    if expected_target_revision is not None and approval["target_revision"] != expected_target_revision:
        raise ValueError("review override approval target revision does not match")
    if expected_target_hash is not None and approval["target_hash"] != expected_target_hash:
        raise ValueError("review override approval target hash does not match")
    target_type = approval["target_type"]
    target_id = approval["target_id"]
    require_persisted_approval(root, approval, target_type=target_type, target_id=target_id)
    authorize(
        "REVIEW_OVERRIDE",
        {
            "target_type": target_type,
            "target_id": target_id,
            "revision": approval["target_revision"],
            "target_hash": approval["target_hash"],
        },
        approval,
        actor={"actor_type": approval["actor_type"], "actor_id": approval["actor_id"]},
    )
    return approval


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
        supplied_schema_version = payload.get("schema_version")
        explicitly_legacy = payload.get("legacy_migration") is True
        payload, version_info = normalize_artifact_version(payload, "review")
        resolved_rubric = payload.get("resolved_rubric")
        # Existing callers historically omitted schema_version while supplying
        # a resolved rubric. Treat that shape as a new writer request for
        # compatibility; an explicitly lower version or legacy marker remains
        # migration-only and cannot satisfy a strict PASS gate.
        unversioned_new_review = (
            supplied_schema_version is None
            and not explicitly_legacy
            and isinstance(resolved_rubric, dict)
        )
        if unversioned_new_review:
            for field in ("legacy_migration", "legacy_classification", "legacy_source_version"):
                payload.pop(field, None)
        if not isinstance(resolved_rubric, dict) and not explicitly_legacy:
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
            existing_review = read_object(existing_review_path) if existing_review_path.is_file() else None
            existing_revision = int(existing_review.get("revision", 0)) if isinstance(existing_review, dict) else 0
            if isinstance(existing_review, dict):
                previous_id = existing_review.get("review_id")
                if previous_id != payload.get("review_id"):
                    payload = preserve_projection_links(
                        payload,
                        previous_id=previous_id,
                        previous_revision=existing_revision,
                        previous_field="previous_review_id",
                    )
                else:
                    for field in ("supersedes_id", "previous_revision", "previous_review_id"):
                        if field in existing_review:
                            payload.setdefault(field, existing_review[field])
            current_task_revision = int(task_state.get("revision", 0))
            lease_path = root / "work" / task_id / "lease.json"
            queue_path = root / "runtime" / "queue.json"
            lease = read_object(lease_path) if lease_path.is_file() else None
            queue = read_object(queue_path) if queue_path.is_file() else None

            profile_id = payload.get("profile_id")
            if profile_id is None and isinstance(resolved_rubric, dict):
                profile_id = resolved_rubric.get("profile_id") or resolved_rubric.get("project_profile")
            if profile_id is not None:
                payload["profile_id"] = profile_id
            legacy_input = bool(
                not unversioned_new_review
                and (version_info["is_legacy"] or explicitly_legacy)
            )
            if is_strict_profile(profile_id) and legacy_input and payload.get("verdict") == "PASS":
                raise ValueError("strict review cannot accept a legacy migration as passing evidence")
            completion_claim = payload.get("completion_claim")
            if is_strict_profile(profile_id) and payload.get("legacy_migration") is not True:
                if not isinstance(completion_claim, dict):
                    raise ValueError("strict review PASS requires a current completion_claim")
            if completion_claim is not None:
                if not isinstance(completion_claim, dict):
                    raise ValueError("review completion_claim must be an object")
                verified_claim = validate_claim(completion_claim, project_root=args.project_root, root=root)
                payload["verification_status"] = verified_claim["verification_status"]
                payload["completion_claim_id"] = verified_claim["claim_id"]

            allow_approved_override = (
                isinstance(resolved_rubric, dict)
                and resolved_rubric.get("override_approval_id") is not None
            )
            if isinstance(resolved_rubric, dict):
                approval_id = resolved_rubric.get("override_approval_id")
                if allow_approved_override:
                    # Mutable rubric policy fields require prior approval bound to this task snapshot and hash.
                    _authorize_review_override(
                        root,
                        approval_id,
                        expected_target_type="RUBRIC_OVERRIDE",
                        expected_target_id=task_id,
                        expected_target_revision=current_task_revision,
                        expected_target_hash=resolved_rubric.get("rubric_hash"),
                    )
                if payload.get("legacy_migration") is not True:
                    task_contract = task_state.get("review_contract")
                    if not isinstance(task_contract, dict):
                        raise ValueError("new reviews require a pinned task review_contract")
                    validate_rubric_against_contract(
                        resolved_rubric,
                        task_contract,
                        review_type="task",
                        allow_approved_override=allow_approved_override,
                    )
                    payload["review_contract"] = task_contract
                validate_rubric_identity(resolved_rubric, allow_approved_override=allow_approved_override)

            payload.setdefault("review_id", f"REV-{task_id}-{existing_revision + 1}")
            payload["revision"] = next_revision(payload, existing_revision)
            payload["created_at"] = utc_now()
            payload["reviewer"] = args.actor
            payload.update(calculate(payload, allow_approved_override=allow_approved_override))
            guard_evidence = {
                "task_state": task_state,
                "review": payload,
                "lease": lease,
                "queue": queue,
            }
            if payload.get("legacy_migration") is not True:
                for identity_field in ("run_id", "attempt_id", "dispatch_id"):
                    expected = task_state.get(identity_field)
                    supplied = payload.get(identity_field)
                    if not isinstance(expected, str) or not expected.strip():
                        raise ValueError(f"review transition identity is missing task_state.{identity_field}")
                    if supplied is not None and supplied != expected:
                        raise ValueError(f"review {identity_field} does not match task identity")
                    payload[identity_field] = expected
                guard_evidence["review"] = payload

            staged_review = payload.get("stage") is not None
            if (
                not staged_review
                and payload.get("legacy_migration") is not True
                and isinstance(profile_id, str)
                and profile_id not in {"personal", "quick_change", "prototype"}
            ):
                raise ValueError("standard and strict profiles require staged task reviews")
            if staged_review:
                if payload.get("schema_version") is None:
                    payload["schema_version"] = 2
                stage = payload.get("stage")
                if stage not in {"SPEC_COMPLIANCE", "CODE_QUALITY"}:
                    raise ValueError("review.stage must be SPEC_COMPLIANCE or CODE_QUALITY")
                if payload.get("artifact_identity") is None:
                    raise ValueError("staged reviews require artifact_identity")
                if current_status == "COMPLETED":
                    if stage != "SPEC_COMPLIANCE":
                        raise ValueError("CODE_QUALITY cannot be the first review stage")
                    expected_identity = _implementation_artifact_identity(
                        args.project_root, task_state, current_task_revision
                    )
                elif current_status == "REVIEWING":
                    if stage != "CODE_QUALITY":
                        raise ValueError("REVIEWING requires the CODE_QUALITY stage")
                    if not isinstance(existing_review, dict):
                        raise ValueError("CODE_QUALITY requires a prior SPEC_COMPLIANCE review")
                    expected_identity = validate_artifact_identity(existing_review.get("artifact_identity"))
                    payload["previous_review_id"] = existing_review.get("review_id")
                    payload["previous_stage"] = existing_review.get("stage")
                    payload["previous_artifact_identity"] = expected_identity
                    validate_stage_chain(payload, existing_review, profile_id=profile_id)
                else:
                    raise ValueError("staged review requires task status COMPLETED or REVIEWING")
                validate_artifact_identity(payload.get("artifact_identity"), expected=expected_identity)
                payload["artifact_identity"] = expected_identity
                if expected_identity.get("task_id") != task_id:
                    raise ValueError("review.artifact_identity.task_id does not match task_id")

            if staged_review and payload.get("stage") == "SPEC_COMPLIANCE":
                spec_compliance = payload.get("spec_compliance")
                if isinstance(spec_compliance, dict) and spec_compliance.get("status") != "PASS":
                    payload["verdict"] = "REPAIR_REQUIRED"
            if staged_review and payload.get("stage") == "CODE_QUALITY":
                if not isinstance(existing_review, dict) or existing_review.get("verdict") != "PASS":
                    raise ValueError("CODE_QUALITY requires a passing SPEC_COMPLIANCE review")

            verdict = payload["verdict"]
            next_status = "ACCEPTED" if verdict == "PASS" else "BLOCKED" if verdict == "BLOCKED" else "REPAIR_REQUIRED"
            if (
                staged_review
                and verdict == "PASS"
                and payload.get("stage") == "SPEC_COMPLIANCE"
                and "CODE_QUALITY" in required_review_stages(profile_id)
            ):
                next_status = "REVIEWING"
            review_status = current_status
            if current_status == "COMPLETED":
                if payload.get("legacy_migration") is True:
                    allowed = is_allowed_transition(current_status, "REVIEWING", actor="reviewer")
                else:
                    validate_transition(current_status, "REVIEWING", actor="reviewer", evidence=guard_evidence)
                    allowed = True
                if not allowed:
                    raise ValueError(f"invalid reviewer transition: {current_status} -> REVIEWING")
                review_status = "REVIEWING"
            if staged_review and current_status == "COMPLETED" and next_status == "REVIEWING":
                allowed = True
            elif payload.get("legacy_migration") is True:
                allowed = is_allowed_transition(review_status, next_status, actor="reviewer")
            else:
                validate_transition(review_status, next_status, actor="reviewer", evidence=guard_evidence)
                allowed = True
            if not allowed:
                raise ValueError(f"invalid reviewer transition: {review_status} -> {next_status}")
            if next_status in {"ACCEPTED", "CANCELLED", "SUPERSEDED"}:
                assert_terminal_cleanup_safe(root, task_id)

            next_task_state = dict(task_state)
            next_task_state, _ = normalize_artifact_version(next_task_state, "task-state")
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
            prior_events = []
            if current_status == "COMPLETED":
                _, _, _, reviewing_event = prepare_event_log(
                    root,
                    {
                        "type": STATUS_TO_EVENT_TYPE["REVIEWING"],
                        "actor": args.actor,
                        "task_id": task_id,
                        "data": {"review_id": payload["review_id"]},
                    },
                    artifact_overrides=event_overrides,
                )
                prior_events.append(reviewing_event)
            review_event_relative, event_revision, event_content, review_event = prepare_event_log(
                root,
                {
                    "type": "REVIEW_CREATED",
                    "actor": args.actor,
                    "task_id": task_id,
                    "data": {"review_id": payload["review_id"]},
                },
                artifact_overrides=event_overrides,
                prior_events=prior_events,
            )
            prior_events.append(review_event)
            if not (staged_review and current_status == "COMPLETED" and next_status == "REVIEWING"):
                _, event_revision, event_content, _ = prepare_event_log(
                    root,
                    {
                        "type": STATUS_TO_EVENT_TYPE[next_status],
                        "actor": args.actor,
                        "task_id": task_id,
                        "data": {"review_id": payload["review_id"]},
                    },
                    artifact_overrides=event_overrides,
                    prior_events=prior_events,
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
