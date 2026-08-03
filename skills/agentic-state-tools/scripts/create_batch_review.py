"""Validate and persist an evidence-based integrated batch review."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from append_event import append_event_for_root
from calculate_rubric_score import validate_findings, validate_rubric_identity
from render_checklist import render_checklist_for_root
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    next_revision,
    read_object,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
)
from write_artifact import write_validated


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/batch-review.schema.json"
VALID_CHECK_RESULTS = {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}


def normalize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("batch review must be an object")
    batch_id = payload.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError("batch review requires a non-empty batch_id")
    validate_identifier(batch_id, "batch_id")
    task_reviews = payload.get("task_reviews")
    if not isinstance(task_reviews, list) or not task_reviews:
        raise ValueError("batch review requires at least one task review ID")
    if any(not isinstance(item, str) or not item.strip() for item in task_reviews):
        raise ValueError("task_reviews must contain non-empty strings")
    checks = payload.get("integration_checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("batch review requires at least one integration check")
    normalized_checks = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ValueError(f"integration_checks[{index}] must be an object")
        name = check.get("name")
        evidence = check.get("evidence")
        result = str(check.get("result", "")).upper()
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"integration_checks[{index}].name must be a non-empty string")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"integration_checks[{index}].evidence must be a non-empty string")
        if result not in VALID_CHECK_RESULTS:
            raise ValueError(f"integration_checks[{index}].result is invalid")
        normalized_checks.append({**check, "result": result})
    findings = payload.get("findings", [])
    validate_findings(findings)
    if not isinstance(payload.get("resolved_rubric"), dict) and payload.get("legacy_migration") is not True:
        raise ValueError("new batch reviews require resolved_rubric; set legacy_migration=true only for existing legacy evidence")
    if isinstance(payload.get("resolved_rubric"), dict):
        validate_rubric_identity(payload["resolved_rubric"])
    scope_valid = payload.get("scope_valid", True)
    if not isinstance(scope_valid, bool):
        raise ValueError("scope_valid must be boolean")
    record = dict(payload)
    record["task_reviews"] = task_reviews
    record["integration_checks"] = normalized_checks
    record["findings"] = findings
    record["scope_valid"] = scope_valid
    return record


def index_task_reviews(root: Path, batch_id: str) -> dict[str, tuple[dict[str, Any], Path]]:
    indexed: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in sorted((root / "work").glob("*/review.json")):
        if path.parent.name == batch_id:
            continue
        try:
            review = read_object(path)
        except (OSError, ValueError):
            continue
        review_id = review.get("review_id")
        if isinstance(review_id, str) and review_id:
            indexed[review_id] = (review, path)
    return indexed


def derive_verdict(root: Path, record: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not record["scope_valid"]:
        reasons.append("batch scope is invalid")
    reviews = index_task_reviews(root, record["batch_id"])
    for review_id in record["task_reviews"]:
        item = reviews.get(review_id)
        if item is None:
            reasons.append(f"task review is missing: {review_id}")
            continue
        review, review_path = item
        if str(review.get("verdict", "")).upper() != "PASS":
            reasons.append(f"task review is not passing: {review_id}")
            continue
        task_state_path = review_path.parent / "task-state.json"
        if not task_state_path.is_file():
            reasons.append(f"task state is missing for review: {review_id}")
            continue
        task_state = read_object(task_state_path)
        if str(task_state.get("status", "")).upper() != "ACCEPTED":
            reasons.append(f"task is not accepted for review: {review_id}")

    check_results = {check["result"] for check in record["integration_checks"]}
    if "FAIL" in check_results:
        reasons.append("an integration check failed")
    if "BLOCKED" in check_results or "NOT_RUN" in check_results:
        reasons.append("an integration check is blocked or not run")
    unresolved_severe = validate_findings(record["findings"])
    if unresolved_severe:
        reasons.append("unresolved critical or major batch finding")

    if not record["scope_valid"]:
        verdict = "PLAN_INVALID"
    elif any("missing" in reason or "not accepted" in reason or "not passing" in reason for reason in reasons):
        verdict = "BLOCKED"
    elif "BLOCKED" in check_results or "NOT_RUN" in check_results:
        verdict = "BLOCKED"
    elif reasons:
        verdict = "REPAIR_REQUIRED"
    else:
        verdict = "PASS"
    return verdict, reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="batch-reviewer")
    args = parser.parse_args()
    try:
        record = normalize(read_payload(args.input))
        with runtime_lock(args.project_root) as root:
            existing_path = root / "work" / record["batch_id"] / "review.json"
            existing_revision = int(read_object(existing_path).get("revision", 0)) if existing_path.is_file() else 0
            record["review_id"] = record.get("review_id") or f"BATCH-REV-{record['batch_id']}-{existing_revision + 1}"
            record["revision"] = next_revision(record, existing_revision)
            record["created_at"] = utc_now()
            record["reviewer"] = args.actor
            record["verdict"], record["blocking_reasons"] = derive_verdict(root, record)
            target = write_validated(args.project_root, f"work/{record['batch_id']}/review.json", record, SCHEMA)
            append_event_for_root(
                root,
                {
                    "type": "BATCH_REVIEW_CREATED",
                    "actor": args.actor,
                    "data": {"batch_id": record["batch_id"], "review_id": record["review_id"], "verdict": record["verdict"]},
                },
            )
            render_checklist_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"BATCH_REVIEW_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"BATCH_REVIEW_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"BATCH_REVIEW_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
