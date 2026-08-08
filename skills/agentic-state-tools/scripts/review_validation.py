"""Shared semantic validation for review outcomes and canonical rubrics."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BLOCKING_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM"}
CRITERION_STATUSES = {"PASS", "FAIL", "NOT_APPLICABLE"}
RUBRIC_MODES = ("plan", "task", "integration")
RUBRIC_FIELDS = {"id", "version", "criteria"}
CRITERION_FIELDS = {"id", "description"}
RESULT_FIELDS = {"id", "status", "evidence"}
RUBRIC_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "agentic-independent-reviewer"
    / "references"
    / "review-rubrics.json"
)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def load_review_rubrics() -> dict[str, Any]:
    """Load and validate the single canonical review-rubric source."""
    try:
        source = json.loads(RUBRIC_SOURCE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to load canonical review rubrics: {exc}") from exc
    if not isinstance(source, dict):
        raise ValueError("canonical review rubrics must be an object")
    if set(source) != {"schema_version", "rubrics"}:
        raise ValueError("canonical review rubrics have unexpected top-level fields")
    if source.get("schema_version") != 1:
        raise ValueError("canonical review rubrics must use schema version 1")
    rubrics = source.get("rubrics")
    if not isinstance(rubrics, dict) or set(rubrics) != set(RUBRIC_MODES):
        raise ValueError("canonical review rubrics must contain exactly plan, task, and integration")
    for mode in RUBRIC_MODES:
        rubric = rubrics[mode]
        if not isinstance(rubric, dict) or set(rubric) != RUBRIC_FIELDS:
            raise ValueError(f"canonical {mode} rubric has invalid fields")
        if not isinstance(rubric.get("id"), str) or not rubric["id"].strip():
            raise ValueError(f"canonical {mode} rubric id must be non-empty")
        if not _is_integer(rubric.get("version")) or rubric["version"] < 1:
            raise ValueError(f"canonical {mode} rubric version must be a positive integer")
        criteria = rubric.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            raise ValueError(f"canonical {mode} rubric criteria must be non-empty")
        criterion_ids: set[str] = set()
        for criterion in criteria:
            if not isinstance(criterion, dict) or set(criterion) != CRITERION_FIELDS:
                raise ValueError(f"canonical {mode} rubric criterion has invalid fields")
            criterion_id = criterion.get("id")
            description = criterion.get("description")
            if not isinstance(criterion_id, str) or not criterion_id.strip():
                raise ValueError(f"canonical {mode} rubric criterion id must be non-empty")
            if criterion_id in criterion_ids:
                raise ValueError(f"canonical {mode} rubric has duplicate criterion: {criterion_id}")
            if not isinstance(description, str) or not description.strip():
                raise ValueError(f"canonical {mode} rubric criterion description must be non-empty")
            criterion_ids.add(criterion_id)
    return rubrics


def get_review_rubric(mode: object) -> dict[str, Any]:
    if not isinstance(mode, str) or mode not in RUBRIC_MODES:
        raise ValueError(f"unknown review mode: {mode!r}")
    return load_review_rubrics()[mode]


def validate_rubric_reference(
    mode: object, rubric_id: object, rubric_version: object
) -> dict[str, Any]:
    rubric = get_review_rubric(mode)
    if not isinstance(rubric_id, str) or not rubric_id.strip():
        raise ValueError(f"{mode} review_rubric_id is required")
    if rubric_id != rubric["id"]:
        raise ValueError(f"unknown {mode} review rubric id: {rubric_id!r}")
    if not _is_integer(rubric_version) or rubric_version < 1:
        raise ValueError(f"{mode} review_rubric_version must be a positive integer")
    if rubric_version != rubric["version"]:
        raise ValueError(
            f"unsupported {mode} review rubric version: {rubric_version!r}"
        )
    return rubric


def validate_criterion_results(
    mode: object,
    rubric_id: object,
    rubric_version: object,
    criteria: object,
    *,
    outcome: str | None = None,
) -> None:
    """Require exactly one evidence-backed gate result for each canonical criterion."""
    rubric = validate_rubric_reference(mode, rubric_id, rubric_version)
    if not isinstance(criteria, list):
        raise ValueError("review criteria must be an array")
    expected = [criterion["id"] for criterion in rubric["criteria"]]
    expected_set = set(expected)
    seen: set[str] = set()
    failures: list[str] = []
    for index, result in enumerate(criteria):
        if not isinstance(result, dict):
            raise ValueError(f"review criterion result {index} must be an object")
        missing_fields = sorted(RESULT_FIELDS - set(result))
        unknown_fields = sorted(set(result) - RESULT_FIELDS)
        if missing_fields:
            raise ValueError(
                f"review criterion result {index} is missing: {', '.join(missing_fields)}"
            )
        if unknown_fields:
            raise ValueError(
                f"review criterion result {index} has unknown fields: {', '.join(unknown_fields)}"
            )
        criterion_id = result["id"]
        if not isinstance(criterion_id, str) or not criterion_id.strip():
            raise ValueError(f"review criterion result {index} id must be non-empty")
        if criterion_id in seen:
            raise ValueError(f"duplicate review criterion result: {criterion_id}")
        if criterion_id not in expected_set:
            raise ValueError(f"unknown review criterion: {criterion_id}")
        status = result["status"]
        if not isinstance(status, str) or status not in CRITERION_STATUSES:
            raise ValueError(f"invalid status for review criterion {criterion_id}: {status!r}")
        evidence = result["evidence"]
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"review criterion evidence must be non-empty: {criterion_id}")
        if status == "NOT_APPLICABLE" and evidence.strip().upper() in {
            "N/A",
            "NA",
            "NOT APPLICABLE",
        }:
            raise ValueError(
                f"NOT_APPLICABLE review criterion requires a reason in evidence: {criterion_id}"
            )
        seen.add(criterion_id)
        if status == "FAIL":
            failures.append(criterion_id)
    missing_criteria = [criterion_id for criterion_id in expected if criterion_id not in seen]
    if missing_criteria:
        raise ValueError(
            "review criteria are incomplete; missing: " + ", ".join(missing_criteria)
        )
    if outcome == "PASS" and failures:
        raise ValueError(
            "PASS cannot contain failed review criteria: " + ", ".join(failures)
        )


def validate_review_contract(review: dict[str, Any], expected_mode: str) -> None:
    if review.get("review_mode") != expected_mode:
        raise ValueError(
            f"review_mode must be {expected_mode!r} for this artifact"
        )
    validate_criterion_results(
        review.get("review_mode"),
        review.get("review_rubric_id"),
        review.get("review_rubric_version"),
        review.get("criteria"),
        outcome=review.get("outcome"),
    )


def validate_review_outcome(outcome: str, findings: Any) -> None:
    if not isinstance(findings, list):
        raise ValueError("review findings must be an array")
    severities = {
        str(item.get("severity", "")).upper()
        for item in findings
        if isinstance(item, dict)
    }
    blocking = severities & BLOCKING_SEVERITIES
    if outcome == "PASS" and blocking:
        raise ValueError(
            "PASS cannot contain blocking findings: " + ", ".join(sorted(blocking))
        )
    if outcome == "REPAIR_REQUIRED" and not blocking:
        raise ValueError("REPAIR_REQUIRED requires at least one blocking finding")
    if outcome == "BLOCKED" and not findings:
        raise ValueError("BLOCKED requires at least one blocker finding")
