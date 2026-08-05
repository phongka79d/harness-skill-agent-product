"""Validate and atomically persist one review-finding resolution."""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Any

from render_checklist import render_checklist_for_root
from review_contract import validate_artifact_identity
from runtime_transaction import RuntimeTransaction, TransactionError
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    next_revision,
    parse_timestamp,
    read_object,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
)
from validate_payload import validate


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/review-resolution.schema.json"
STATUSES = {
    "ACCEPTED", "REJECTED_WITH_EVIDENCE", "NEEDS_CLARIFICATION",
    "SUPERSEDED", "FIXED_PENDING_REREVIEW", "CLOSED",
}
REVIEWER_ACTORS = {"reviewer", "task-reviewer", "agentic-task-reviewer"}
TARGET = "review-resolution.json"


def _actor_role(actor: str) -> str:
    return "REVIEWER" if actor in REVIEWER_ACTORS else "IMPLEMENTER"


def _finding(review: dict[str, Any], finding_id: str) -> dict[str, Any] | None:
    findings = review.get("findings")
    if not isinstance(findings, list):
        return None
    for index, value in enumerate(findings, start=1):
        if not isinstance(value, dict):
            continue
        candidate = value.get("finding_id") or f"finding-{index}"
        if candidate == finding_id:
            snapshot = {key: value[key] for key in ("severity", "evidence", "required_change") if key in value}
            if isinstance(value.get("location"), str):
                snapshot["location"] = value["location"]
            return snapshot
    return None


def _require_check(record: dict[str, Any], field: str) -> dict[str, Any]:
    value = record.get(field)
    if not isinstance(value, dict) or not isinstance(value.get("evidence"), list) or not value["evidence"]:
        raise ValueError(f"{field} must contain visible evidence")
    return value


def _validate_status(record: dict[str, Any], existing: dict[str, Any] | None, actor: str) -> None:
    status = record.get("status")
    if status not in STATUSES:
        raise ValueError("resolution.status is invalid")
    if not isinstance(record.get("owner"), str) or not record["owner"].strip():
        raise ValueError("every non-closed finding requires a visible owner")
    if existing is not None and existing.get("status") == "CLOSED":
        raise ValueError("a CLOSED finding resolution is immutable")

    contract = _require_check(record, "contract_verification")
    code = _require_check(record, "code_verification")
    usage = _require_check(record, "conflict_usage_check")
    ambiguity = _require_check(record, "ambiguity_resolution")
    if status == "ACCEPTED" and (contract["status"] != "VERIFIED" or code["status"] != "VERIFIED" or usage["status"] != "CLEAR" or ambiguity["status"] == "UNRESOLVED"):
        raise ValueError("ACCEPTED requires current contract/code verification, clear usage, and resolved ambiguity")
    if status == "REJECTED_WITH_EVIDENCE":
        if not record.get("rejection_basis"):
            raise ValueError("REJECTED_WITH_EVIDENCE requires concrete rejection_basis")
        if not any(item["status"] == "CONFLICT" for item in (contract, code, usage)):
            raise ValueError("REJECTED_WITH_EVIDENCE requires a contract, code, or usage conflict")
    if status == "NEEDS_CLARIFICATION" and (ambiguity["status"] != "UNRESOLVED" or not record.get("clarification_question")):
        raise ValueError("NEEDS_CLARIFICATION requires an unresolved ambiguity and question")
    if status == "SUPERSEDED" and not record.get("superseded_by"):
        raise ValueError("SUPERSEDED requires superseded_by")
    if status == "FIXED_PENDING_REREVIEW":
        correction = record.get("correction")
        verification = record.get("targeted_verification")
        if not isinstance(correction, dict) or correction.get("coherent") is not True or not correction.get("summary") or not correction.get("changed_files"):
            raise ValueError("FIXED_PENDING_REREVIEW requires one coherent correction")
        if not isinstance(verification, dict) or verification.get("status") != "PASS" or verification.get("exit_code") != 0:
            raise ValueError("FIXED_PENDING_REREVIEW requires passing targeted verification")
        if contract["status"] != "VERIFIED" or code["status"] != "VERIFIED" or usage["status"] != "CLEAR" or ambiguity["status"] == "UNRESOLVED":
            raise ValueError("FIXED_PENDING_REREVIEW requires resolved contract, code, usage, and ambiguity checks")
    if status == "CLOSED":
        if actor not in REVIEWER_ACTORS or record.get("actor_role") != "REVIEWER":
            raise ValueError("only a reviewer may mark a finding CLOSED")
        if existing is None or existing.get("status") != "FIXED_PENDING_REREVIEW":
            raise ValueError("CLOSED requires an implementer FIXED_PENDING_REREVIEW resolution")
        re_review = record.get("re_review")
        if not isinstance(re_review, dict) or re_review.get("review_id") != record.get("review_id") or re_review.get("result") != "PASS" or not re_review.get("evidence_ids"):
            raise ValueError("CLOSED requires passing re-review evidence linked to the current review")
        if record.get("review_id") == existing.get("review_id"):
            raise ValueError("CLOSED requires a new re-review identity")
        if record.get("correction_reference") != existing.get("resolution_id"):
            raise ValueError("CLOSED must link the correction resolution")


def normalize(
    payload: Any,
    *,
    task_id: str,
    task: dict[str, Any],
    review: dict[str, Any],
    existing: dict[str, Any] | None,
    actor: str,
) -> dict[str, Any]:
    """Normalize and validate a user-provided resolution without writing it."""

    if not isinstance(payload, dict):
        raise ValueError("review resolution must be an object")
    record = dict(payload)
    if record.get("task_id", task_id) != task_id or review.get("task_id") != task_id:
        raise ValueError("resolution.task_id does not match the task and review")
    review_id = review.get("review_id")
    if not isinstance(review_id, str) or not review_id.strip():
        raise ValueError("current review is missing review_id")
    current_identity = validate_artifact_identity(review.get("artifact_identity"))
    supplied_identity = record.get("artifact_identity")
    if supplied_identity != current_identity:
        raise ValueError("resolution artifact identity does not match the current staged review")
    finding_id = record.get("finding_id")
    current_finding = _finding(review, finding_id) if isinstance(finding_id, str) else None
    if current_finding is None:
        if not (existing and record.get("status") == "CLOSED" and existing.get("finding") == record.get("finding")):
            raise ValueError(f"finding does not exist in current review: {finding_id}")
        current_finding = existing["finding"]
    if record.get("finding") != current_finding:
        raise ValueError("resolution.finding must exactly reproduce the complete current finding")

    for field in ("run_id", "attempt_id"):
        expected = task.get(field)
        if not isinstance(expected, str) or not expected.strip() or record.get(field, expected) != expected:
            raise ValueError(f"resolution.{field} does not match task state")
        record[field] = expected
    task_revision = task.get("revision")
    if isinstance(task_revision, bool) or not isinstance(task_revision, int) or task_revision < 1 or record.get("task_revision", task_revision) != task_revision:
        raise ValueError("resolution.task_revision does not match task state")
    record["task_revision"] = task_revision

    previous_revision = int(existing.get("revision", 0)) if isinstance(existing, dict) else 0
    expected_revision = record.pop("expected_revision", previous_revision)
    if expected_revision != previous_revision:
        raise ValueError("resolution revision is stale")
    status = record.get("status")
    if existing is not None:
        if existing.get("finding_id") != finding_id or existing.get("task_id") != task_id:
            raise ValueError("resolution lineage identity cannot change")
        if existing.get("status") != "FIXED_PENDING_REREVIEW" or status != "CLOSED":
            for field in ("review_id", "artifact_identity", "run_id", "attempt_id", "task_revision"):
                if record.get(field) != existing.get(field):
                    raise ValueError(f"resolution {field} cannot change before re-review")
        record["resolution_id"] = existing["resolution_id"]
        record["created_at"] = existing["created_at"]
        record["original_review_id"] = existing["original_review_id"]
        record["previous_resolution_id"] = existing["resolution_id"]
        record["previous_status"] = existing.get("status")
    else:
        if record.get("review_id", review_id) != review_id:
            raise ValueError("resolution.review_id must identify the current review")
        record["resolution_id"] = record.get("resolution_id") or f"RES-{task_id}-{uuid.uuid4().hex[:12].upper()}"
        record["original_review_id"] = review_id
        record.setdefault("created_at", utc_now())
        record["previous_resolution_id"] = None
        record["previous_status"] = None
    record.update({
        "schema_version": 1,
        "task_id": task_id,
        "review_id": review_id,
        "finding_id": finding_id,
        "artifact_identity": current_identity,
        "actor": actor,
        "actor_role": _actor_role(actor),
        "revision": next_revision(record, previous_revision),
        "updated_at": utc_now(),
    })
    if not isinstance(record.get("owner"), str) or not record["owner"].strip():
        record["owner"] = actor
    if not isinstance(record.get("rationale"), str) or not record["rationale"].strip():
        raise ValueError("resolution rationale is required")
    evidence = record.get("evidence")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("summary"), str) or not evidence["summary"].strip():
        raise ValueError("resolution evidence.summary is required")
    _validate_status(record, existing, actor)
    parse_timestamp(record["created_at"])
    parse_timestamp(record["updated_at"])
    errors = validate(record, read_object(SCHEMA), base_path=SCHEMA.parent)
    if errors:
        raise ValueError("review resolution schema validation failed: " + "; ".join(errors))
    return record


def persist(project_root: str, task_id: str, record: dict[str, Any], previous_revision: int) -> Path:
    """Publish the resolution through the durable state-tools transaction."""

    relative = f"work/{task_id}/{TARGET}"
    transaction = RuntimeTransaction(
        project_root,
        operation_type="REVIEW_RESOLUTION",
        idempotency_key=f"review-resolution:{task_id}:{record['finding_id']}:{record['revision']}:{record['resolution_id']}",
        expected_revisions={relative: previous_revision},
    )
    transaction.prepare([relative])
    transaction.stage_json(relative, record, SCHEMA)
    transaction.commit()
    return Path(project_root).resolve() / ".agent" / relative


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="agentic-implementer")
    args = parser.parse_args()
    try:
        validate_identifier(args.task_id, "task_id")
        payload = read_payload(args.input)
        with runtime_lock(args.project_root) as root:
            task_path = root / "work" / args.task_id / "task-state.json"
            review_path = root / "work" / args.task_id / "review.json"
            if not task_path.is_file() or not review_path.is_file():
                raise ValueError("review resolution requires current task state and review")
            task = read_object(task_path)
            review = read_object(review_path)
            existing_path = root / "work" / args.task_id / TARGET
            existing = read_object(existing_path) if existing_path.is_file() else None
            previous_revision = int(existing.get("revision", 0)) if isinstance(existing, dict) else 0
            record = normalize(payload, task_id=args.task_id, task=task, review=review, existing=existing, actor=args.actor)
            target = persist(args.project_root, args.task_id, record, previous_revision)
            render_checklist_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"REVIEW_RESOLUTION_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, TransactionError, OSError, ValueError, TypeError) as exc:
        print(f"REVIEW_RESOLUTION_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"REVIEW_RESOLUTION_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
