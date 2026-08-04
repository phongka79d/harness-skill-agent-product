"""Validate and persist an evidence-based integrated batch review."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from authorization import require_persisted_approval, validate_approval
from calculate_rubric_score import calculate, validate_findings, validate_rubric_identity
from rebuild_state import rebuild_state_for_root
from render_checklist import render_checklist_for_root
from review_contract import validate_contract, validate_rubric_against_contract
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    next_revision,
    prepare_event_log,
    read_object,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
)
from validate_payload import validate
from runtime_transaction import RuntimeTransaction, TransactionError


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/batch-review.schema.json"
CONTRACT_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/batch-contract.schema.json"
TASK_STATE_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/task-state.schema.json"
REVIEW_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/review.schema.json"
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


def index_task_reviews(root: Path, batch_id: str, *, strict: bool = False) -> dict[str, tuple[dict[str, Any], Path]]:
    indexed: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in sorted((root / "work").glob("*/review.json")):
        if path.parent.name == batch_id:
            continue
        try:
            review = read_object(path)
        except (OSError, ValueError):
            continue
        if review.get("task_id") != path.parent.name:
            continue
        if strict:
            errors = validate(review, read_object(REVIEW_SCHEMA), base_path=REVIEW_SCHEMA.parent)
            if errors:
                continue
        review_id = review.get("review_id")
        if isinstance(review_id, str) and review_id:
            indexed[review_id] = (review, path)
    return indexed


def load_batch_contract(root: Path, batch_id: str, *, strict: bool = True) -> dict[str, Any] | None:
    validate_identifier(batch_id, "batch_id")
    path = root / "work" / batch_id / "batch-contract.json"
    if not path.is_file():
        return None
    contract = read_object(path)
    if contract.get("batch_id") != batch_id:
        raise ValueError("canonical batch contract ID does not match review batch_id")
    expected = contract.get("tasks")
    if not strict:
        if not isinstance(expected, list) or not expected:
            raise ValueError("legacy batch contract tasks must be a non-empty array")
        if all(isinstance(item, str) and item.strip() for item in expected):
            if len(expected) != len(set(expected)):
                raise ValueError("legacy batch contract contains duplicate task IDs")
            return contract
        if all(isinstance(item, dict) and isinstance(item.get("task_id"), str) and item["task_id"].strip() for item in expected):
            task_ids = [item["task_id"] for item in expected]
            if len(task_ids) != len(set(task_ids)):
                raise ValueError("legacy batch contract contains duplicate task IDs")
            return contract
        raise ValueError("legacy batch contract tasks must contain task IDs")
    errors = validate(contract, read_object(CONTRACT_SCHEMA), base_path=CONTRACT_SCHEMA.parent)
    if errors:
        raise ValueError("canonical batch contract is invalid: " + "; ".join(errors))
    task_ids = [item["task_id"] for item in expected]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("canonical batch contract contains duplicate task IDs")
    expected_hash = dict(contract)
    actual_hash = expected_hash.pop("contract_hash")
    if hashlib.sha256(json.dumps(expected_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest() != actual_hash:
        raise ValueError("canonical batch contract hash does not match content")
    plan_id = contract["plan_id"]
    approval_path = root / "approvals" / f"MASTER_PLAN-{plan_id}.json"
    approval = read_object(approval_path)
    require_persisted_approval(root, approval, target_type="MASTER_PLAN", target_id=plan_id)
    if approval.get("approval_id") != contract["plan_approval_id"] or approval.get("action") not in {"MASTER_PLAN", "MASTER_PLAN_APPROVE", "PLAN_APPROVE"}:
        raise ValueError("canonical batch contract plan approval is not current")
    if approval.get("actor_type") != "primary_agent" or approval.get("actor_id") != "primary-agent":
        raise ValueError("canonical batch contract approval is not primary-agent bound")
    validate_approval(approval, action=approval["action"], target_type="MASTER_PLAN", target_id=plan_id, target_revision=contract["plan_revision"], target_hash=contract["plan_hash"])
    validate_contract(contract["review_contract"], review_type="batch")
    if any(contract[field] != contract["review_contract"][field] for field in ("rubric_id", "rubric_version", "rubric_hash")):
        raise ValueError("canonical batch contract rubric pins do not match review_contract")
    for pin in expected:
        task_id = pin["task_id"]
        task_path = root / "work" / task_id / "task-state.json"
        if not task_path.is_file():
            raise ValueError(f"canonical batch task state is missing: {task_id}")
        task_state = read_object(task_path)
        state_errors = validate(task_state, read_object(TASK_STATE_SCHEMA), base_path=TASK_STATE_SCHEMA.parent)
        if state_errors:
            raise ValueError(f"canonical batch task state is invalid: {task_id}: " + "; ".join(state_errors))
        if task_state.get("task_id") != task_id or task_state.get("batch_id") != contract["batch_id"]:
            raise ValueError(f"canonical batch task state identity does not match contract: {task_id}")
        if task_state.get("plan_revision") is not None and task_state["plan_revision"] != contract["plan_revision"]:
            raise ValueError(f"canonical batch task plan_revision does not match contract: {task_id}")
        if task_state.get("revision") != pin["task_revision"]:
            raise ValueError(f"canonical batch task revision is stale: {task_id}")
        task_contract = task_state.get("review_contract")
        if not isinstance(task_contract, dict):
            raise ValueError(f"canonical batch task review_contract is missing: {task_id}")
        validate_contract(task_contract, review_type="task")
        task_contract_hash = hashlib.sha256(json.dumps(task_contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if task_contract_hash != pin["review_contract_hash"] or any(task_contract[field] != pin[contract_field] for field, contract_field in (("rubric_id", "rubric_id"), ("rubric_version", "rubric_version"), ("rubric_hash", "rubric_hash"))):
            raise ValueError(f"canonical batch task review pins are stale: {task_id}")
    return contract


def derive_verdict(root: Path, record: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if record.get("rubric_verdict") not in {None, "PASS"}:
        reasons.append(f"batch rubric verdict is not passing: {record['rubric_verdict']}")
    if not record["scope_valid"]:
        reasons.append("batch scope is invalid")
    reviews = index_task_reviews(root, record["batch_id"], strict=record.get("legacy_migration") is not True)
    try:
        contract = load_batch_contract(root, record["batch_id"], strict=record.get("legacy_migration") is not True)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        contract = None
        reasons.append(f"canonical batch contract is invalid: {exc}")
    if record.get("legacy_migration") is not True and contract is None:
        reasons.append("canonical batch contract is missing")
    expected_task_ids = None
    if contract is not None:
        expected_task_ids = {
            item if isinstance(item, str) else item["task_id"]
            for item in contract["tasks"]
        }
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
        if contract is not None and any(isinstance(item, dict) for item in contract["tasks"]):
            pin = next((item for item in contract["tasks"] if isinstance(item, dict) and item["task_id"] == task_id), None)
            if pin is not None and task_state.get("revision") != pin["task_revision"]:
                reasons.append(f"task revision is stale for review: {review_id}")
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
                record["batch_contract_revision"] = batch_contract["revision"]
                record["batch_contract_hash"] = batch_contract["contract_hash"]
            record["verdict"], record["blocking_reasons"] = derive_verdict(root, record)
            record["artifact_hash"] = artifact_hash(record)
            target = root / "work" / record["batch_id"] / "review.json"
            relative = f"work/{record['batch_id']}/review.json"
            event_relative, event_revision, event_content, _ = prepare_event_log(
                root,
                {
                    "type": "BATCH_REVIEW_CREATED",
                    "actor": args.actor,
                    "data": {
                        "batch_id": record["batch_id"],
                        "review_id": record["review_id"],
                        "verdict": record["verdict"],
                    },
                },
                artifact_overrides={relative: record},
            )
            transaction = RuntimeTransaction(
                args.project_root,
                operation_type="BATCH_REVIEW",
                idempotency_key=f"batch-review:{record['batch_id']}:{record['review_id']}:{record['revision']}",
                expected_revisions={relative: existing_revision, event_relative: event_revision},
            )
            transaction.prepare([relative, event_relative])
            transaction.stage_json(relative, record, SCHEMA)
            transaction.stage_text(event_relative, event_content)
            transaction.commit()
            rebuild_state_for_root(root)
            render_checklist_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"BATCH_REVIEW_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, TransactionError, OSError, ValueError, TypeError) as exc:
        print(f"BATCH_REVIEW_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"BATCH_REVIEW_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
