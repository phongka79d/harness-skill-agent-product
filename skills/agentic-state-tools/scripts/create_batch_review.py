"""Validate and persist an evidence-based integrated batch review."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from append_event import append_event_for_root
from calculate_rubric_score import calculate, validate_findings, validate_rubric_identity
from render_checklist import render_checklist_for_root
from review_contract import validate_rubric_against_contract
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
VALID_CHECK_KINDS = {"integration", "regression", "scope"}


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
    legacy_migration = payload.get("legacy_migration") is True
    if not isinstance(checks, list) or not checks:
        raise ValueError("batch review requires at least one integration check")
    normalized_checks = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ValueError(f"integration_checks[{index}] must be an object")
        name = check.get("name")
        kind = str(check.get("kind", "")).lower()
        if not kind and legacy_migration:
            kind = "integration"
        evidence = check.get("evidence")
        result = str(check.get("result", "")).upper()
        if kind not in VALID_CHECK_KINDS:
            raise ValueError(f"integration_checks[{index}].kind must be integration, regression, or scope")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"integration_checks[{index}].name must be a non-empty string")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"integration_checks[{index}].evidence must be a non-empty string")
        if result not in VALID_CHECK_RESULTS:
            raise ValueError(f"integration_checks[{index}].result is invalid")
        normalized_checks.append({**check, "kind": kind, "result": result})
    check_kinds = {check["kind"] for check in normalized_checks}
    missing_kinds = VALID_CHECK_KINDS - check_kinds
    if missing_kinds and not legacy_migration:
        raise ValueError("batch review is missing required checks: " + ", ".join(sorted(missing_kinds)))
    findings = payload.get("findings", [])
    validate_findings(findings)
    if not isinstance(payload.get("resolved_rubric"), dict) and payload.get("legacy_migration") is not True:
        raise ValueError("new batch reviews require resolved_rubric; set legacy_migration=true only for existing legacy evidence")
    score: dict[str, Any] | None = None
    if isinstance(payload.get("resolved_rubric"), dict):
        validate_rubric_identity(payload["resolved_rubric"])
        if not isinstance(payload.get("criteria"), list) or not payload["criteria"]:
            raise ValueError("new batch reviews require canonical rubric criteria")
        score = calculate(
            {
                "resolved_rubric": payload["resolved_rubric"],
                "criteria": payload["criteria"],
                "hard_fail_checks": payload.get("hard_fail_checks"),
                "findings": findings,
            }
        )
    scope_valid = payload.get("scope_valid", True)
    if not isinstance(scope_valid, bool):
        raise ValueError("scope_valid must be boolean")
    record = dict(payload)
    record["task_reviews"] = task_reviews
    record["integration_checks"] = normalized_checks
    record["findings"] = findings
    record["scope_valid"] = scope_valid
    if score is not None:
        record.update(
            {
                "criteria": payload["criteria"],
                "score_percent": score["score_percent"],
                "threshold_percent": score["threshold_percent"],
                "rubric_verdict": score["verdict"],
                "rubric_hard_fail": score["hard_fail"],
            }
        )
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


def load_batch_contract(root: Path, batch_id: str) -> dict[str, Any] | None:
    path = root / "work" / batch_id / "batch-contract.json"
    if not path.is_file():
        return None
    contract = read_object(path)
    if contract.get("batch_id") != batch_id:
        raise ValueError("canonical batch contract ID does not match review batch_id")
    expected = contract.get("tasks")
    if not isinstance(expected, list) or not expected or any(not isinstance(item, str) or not item.strip() for item in expected):
        raise ValueError("canonical batch contract tasks must be a non-empty array of IDs")
    if len(expected) != len(set(expected)):
        raise ValueError("canonical batch contract contains duplicate task IDs")
    return contract


def derive_verdict(root: Path, record: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if record.get("rubric_verdict") not in {None, "PASS"}:
        reasons.append(f"batch rubric verdict is not passing: {record['rubric_verdict']}")
    if not record["scope_valid"]:
        reasons.append("batch scope is invalid")
    reviews = index_task_reviews(root, record["batch_id"])
    contract = load_batch_contract(root, record["batch_id"])
    expected_task_ids = set(contract["tasks"]) if contract is not None else None
    submitted_task_ids: list[str] = []
    for review_id in record["task_reviews"]:
        item = reviews.get(review_id)
        if item is None:
            reasons.append(f"task review is missing: {review_id}")
            continue
        review, review_path = item
        task_id = review.get("task_id")
        if isinstance(task_id, str) and task_id:
            submitted_task_ids.append(task_id)
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
        if record.get("legacy_migration") is not True:
            task_contract = task_state.get("review_contract")
            review_contract = review.get("review_contract")
            if not isinstance(task_contract, dict) or not isinstance(review_contract, dict):
                reasons.append(f"task review contract is missing: {review_id}")
            elif review_contract != task_contract:
                reasons.append(f"task review contract does not match task state: {review_id}")
            else:
                try:
                    validate_rubric_against_contract(review.get("resolved_rubric"), task_contract, review_type="task")
                except (TypeError, ValueError) as exc:
                    reasons.append(f"task review rubric is not bound to its contract: {review_id}: {exc}")

    if expected_task_ids is not None:
        submitted_task_set = set(submitted_task_ids)
        missing_tasks = sorted(expected_task_ids - submitted_task_set)
        unexpected_tasks = sorted(submitted_task_set - expected_task_ids)
        if len(submitted_task_ids) != len(submitted_task_set):
            reasons.append("batch submitted duplicate task IDs")
        if missing_tasks:
            reasons.append("canonical batch tasks missing from review: " + ", ".join(missing_tasks))
        if unexpected_tasks:
            reasons.append("review contains tasks outside canonical batch: " + ", ".join(unexpected_tasks))

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


def artifact_hash(record: dict[str, Any]) -> str:
    canonical = dict(record)
    canonical.pop("artifact_hash", None)
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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
            if record.get("legacy_migration") is not True:
                batch_contract = load_batch_contract(root, record["batch_id"])
                if not isinstance(batch_contract, dict) or not isinstance(batch_contract.get("review_contract"), dict):
                    raise ValueError("new batch reviews require a pinned batch review_contract")
                if not isinstance(record.get("resolved_rubric"), dict):
                    raise ValueError("new batch reviews require resolved_rubric")
                validate_rubric_against_contract(record["resolved_rubric"], batch_contract["review_contract"], review_type="batch")
                record["review_contract"] = batch_contract["review_contract"]
            record["verdict"], record["blocking_reasons"] = derive_verdict(root, record)
            record["artifact_hash"] = artifact_hash(record)
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
