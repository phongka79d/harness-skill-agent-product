"""Validate and persist one explicit review-finding resolution."""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Any

from render_checklist import render_checklist_for_root
from runtime_utils import RuntimeLockedError, RuntimeNotInitializedError, next_revision, parse_timestamp, read_object, read_payload, runtime_lock, utc_now, validate_identifier
from validate_payload import validate
from write_artifact import write_validated


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/review-resolution.schema.json"
STATUSES = {"ACCEPTED", "REJECTED_WITH_EVIDENCE", "NEEDS_CLARIFICATION", "SUPERSEDED", "FIXED_PENDING_REREVIEW", "CLOSED"}
REVIEWER_ACTORS = {"task-reviewer", "reviewer", "primary-agent", "primary_agent"}


def _finding_exists(review: dict[str, Any], finding_id: str) -> bool:
    findings = review.get("findings")
    if not isinstance(findings, list):
        return False
    for index, finding in enumerate(findings, start=1):
        if isinstance(finding, dict) and (finding.get("finding_id") or f"finding-{index}") == finding_id:
            return True
    return False


def _validate_status(record: dict[str, Any], existing: dict[str, Any] | None, actor: str) -> None:
    status = record.get("status")
    if status not in STATUSES:
        raise ValueError("resolution.status is invalid")
    if status == "CLOSED" and actor not in REVIEWER_ACTORS:
        raise ValueError("only a reviewer may mark a finding CLOSED")
    if existing is not None and existing.get("status") == "CLOSED":
        raise ValueError("a CLOSED finding resolution is immutable")
    if status == "FIXED_PENDING_REREVIEW":
        correction = record.get("correction")
        verification = record.get("verification")
        if not isinstance(correction, dict) or not correction.get("summary"):
            raise ValueError("FIXED_PENDING_REREVIEW requires correction evidence")
        if not isinstance(verification, dict) or verification.get("status") != "PASS" or verification.get("exit_code") != 0:
            raise ValueError("FIXED_PENDING_REREVIEW requires passing targeted verification")
    if status == "REJECTED_WITH_EVIDENCE" and not isinstance(record.get("evidence"), dict):
        raise ValueError("REJECTED_WITH_EVIDENCE requires concrete evidence")
    if status == "CLOSED":
        re_review = record.get("re_review")
        if not isinstance(re_review, dict) or not re_review.get("review_id") or re_review.get("result") not in {"PASS", "FAIL", "BLOCKED"}:
            raise ValueError("CLOSED requires a reviewer re-review link and result")
        if not isinstance(re_review.get("evidence_ids"), list) or not re_review["evidence_ids"]:
            raise ValueError("CLOSED requires re-review evidence IDs")


def normalize(payload: Any, *, task_id: str, task: dict[str, Any], review: dict[str, Any], existing: dict[str, Any] | None, actor: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("review resolution must be an object")
    record = dict(payload)
    if record.get("task_id", task_id) != task_id:
        raise ValueError("resolution.task_id does not match the CLI task_id")
    review_id = review.get("review_id")
    if not isinstance(review_id, str) or not review_id.strip() or record.get("review_id", review_id) != review_id:
        raise ValueError("resolution.review_id must identify the current review")
    finding_id = record.get("finding_id")
    if not isinstance(finding_id, str) or not finding_id.strip() or not _finding_exists(review, finding_id):
        raise ValueError(f"finding does not exist in current review: {finding_id}")
    for field in ("run_id", "attempt_id"):
        expected = task.get(field)
        if not isinstance(expected, str) or not expected.strip():
            raise ValueError(f"task state is missing {field}")
        if record.get(field, expected) != expected:
            raise ValueError(f"resolution.{field} does not match task state")
        record[field] = expected
    task_revision = task.get("revision")
    if isinstance(task_revision, bool) or not isinstance(task_revision, int) or task_revision < 1 or record.get("task_revision", task_revision) != task_revision:
        raise ValueError("resolution.task_revision does not match task state")
    record["task_revision"] = task_revision
    previous_revision = existing.get("revision", 0) if isinstance(existing, dict) else 0
    expected_revision = record.pop("expected_revision", previous_revision)
    if expected_revision != previous_revision:
        raise ValueError("resolution revision is stale")
    if existing is not None:
        for field in ("task_id", "review_id", "finding_id", "run_id", "attempt_id", "task_revision"):
            if record.get(field, existing.get(field)) != existing.get(field):
                raise ValueError(f"resolution {field} cannot change across revisions")
        record["resolution_id"] = existing["resolution_id"]
        record["created_at"] = existing["created_at"]
        record["previous_resolution_id"] = existing["resolution_id"]
        record["previous_status"] = existing.get("status")
    else:
        record["resolution_id"] = record.get("resolution_id") or f"RES-{task_id}-{uuid.uuid4().hex[:12].upper()}"
        record.setdefault("created_at", utc_now())
        record["previous_resolution_id"] = None
        record["previous_status"] = None
    record.update({"task_id": task_id, "review_id": review_id, "finding_id": finding_id, "owner": record.get("owner") or actor, "actor": actor, "schema_version": record.get("schema_version", 1), "revision": next_revision(record, previous_revision), "updated_at": utc_now()})
    if not isinstance(record.get("rationale"), str) or not record["rationale"].strip() or not isinstance(record.get("evidence"), dict) or not record["evidence"].get("summary"):
        raise ValueError("resolution rationale and evidence.summary are required")
    _validate_status(record, existing, actor)
    parse_timestamp(record["created_at"])
    parse_timestamp(record["updated_at"])
    errors = validate(record, read_object(SCHEMA), base_path=SCHEMA.parent)
    if errors:
        raise ValueError("review resolution schema validation failed: " + "; ".join(errors))
    return record


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
            existing_path = root / "work" / args.task_id / "review-resolution.json"
            existing = read_object(existing_path) if existing_path.is_file() else None
            record = normalize(payload, task_id=args.task_id, task=task, review=review, existing=existing, actor=args.actor)
            target = write_validated(args.project_root, f"work/{args.task_id}/review-resolution.json", record, SCHEMA)
            render_checklist_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"REVIEW_RESOLUTION_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"REVIEW_RESOLUTION_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"REVIEW_RESOLUTION_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
