"""Calculate an evidence-based weighted rubric verdict deterministically."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any

from runtime_utils import read_object, write_json_atomic


VALID_APPLICABILITY = {"APPLICABLE", "NOT_APPLICABLE", "INSUFFICIENT_CONTEXT"}
VALID_SEVERITIES = {"CRITICAL", "MAJOR", "MINOR", "SUGGESTION"}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_rubric_identity(rubric: Any) -> None:
    if not isinstance(rubric, dict):
        raise ValueError("resolved_rubric must be an object")
    for field in ("rubric_id", "rubric_version", "rubric_hash", "criteria", "applicability", "resolved_weights", "pass_threshold_percent"):
        if field not in rubric:
            raise ValueError(f"resolved_rubric.{field} is required")
    if not isinstance(rubric["rubric_hash"], str) or not isinstance(rubric["criteria"], list):
        raise ValueError("resolved_rubric.rubric_hash and criteria have invalid types")
    if not isinstance(rubric["applicability"], dict) or not isinstance(rubric["resolved_weights"], dict):
        raise ValueError("resolved_rubric applicability and resolved_weights must be objects")
    without_hash = dict(rubric)
    supplied_hash = without_hash.pop("rubric_hash", None)
    calculated_hash = hashlib.sha256(canonical(without_hash).encode("utf-8")).hexdigest()
    if supplied_hash != calculated_hash:
        raise ValueError("resolved_rubric.rubric_hash does not match its contents")


def validate_resolved_rubric(review: dict[str, Any]) -> None:
    rubric = review.get("resolved_rubric")
    if rubric is None:
        return
    validate_rubric_identity(rubric)
    if any(not isinstance(item, dict) for item in rubric["criteria"]):
        raise ValueError("resolved_rubric.criteria must contain objects")
    definitions = {item.get("id"): item for item in rubric["criteria"]}
    if len(definitions) != len(rubric["criteria"]) or any(not isinstance(identifier, str) or not identifier for identifier in definitions):
        raise ValueError("resolved_rubric.criteria must contain unique object IDs")
    weights = rubric["resolved_weights"]
    if not isinstance(weights, dict):
        raise ValueError("resolved_rubric.resolved_weights must be an object")
    review_ids = {criterion.get("id") for criterion in review.get("criteria", []) if isinstance(criterion, dict)}
    missing = sorted(set(weights) - review_ids)
    if missing:
        raise ValueError(f"review is missing resolved rubric criteria: {', '.join(missing)}")
    for criterion in review.get("criteria", []):
        criterion_id = criterion.get("id") if isinstance(criterion, dict) else None
        if criterion_id not in definitions:
            raise ValueError(f"review criterion is not present in resolved rubric: {criterion_id}")
        definition = definitions[criterion_id]
        if str(criterion.get("applicability", "APPLICABLE")).upper() != str(definition.get("applicability", "APPLICABLE")).upper():
            raise ValueError(f"criterion applicability does not match resolved rubric: {criterion_id}")
        if definition.get("applicability", "APPLICABLE") == "APPLICABLE":
            if criterion.get("weight") != weights.get(criterion_id):
                raise ValueError(f"criterion weight does not match resolved rubric: {criterion_id}")


def number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    return float(value)


def text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def validate_findings(findings: Any) -> bool:
    if not isinstance(findings, list):
        raise ValueError("findings must be an array")
    unresolved_severe = False
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise ValueError(f"findings[{index}] must be an object")
        severity = str(finding.get("severity", "")).upper()
        if severity not in VALID_SEVERITIES:
            raise ValueError(f"findings[{index}].severity is invalid")
        text(finding.get("evidence"), f"findings[{index}].evidence")
        text(finding.get("required_change"), f"findings[{index}].required_change")
        resolved = finding.get("resolved", False)
        if not isinstance(resolved, bool):
            raise ValueError(f"findings[{index}].resolved must be boolean")
        if severity in {"CRITICAL", "MAJOR"} and not resolved:
            unresolved_severe = True
    return unresolved_severe


def calculate(review: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(review, dict):
        raise ValueError("review must be a JSON object")
    validate_resolved_rubric(review)
    criteria = review.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("review requires at least one criterion")

    applicable: list[dict[str, Any]] = []
    insufficient_context = False
    for index, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            raise ValueError(f"criteria[{index}] must be an object")
        text(criterion.get("id"), f"criteria[{index}].id")
        applicability = str(criterion.get("applicability", "APPLICABLE")).upper()
        if applicability not in VALID_APPLICABILITY:
            raise ValueError(f"criteria[{index}].applicability is invalid")
        if applicability == "INSUFFICIENT_CONTEXT":
            insufficient_context = True
            continue
        if applicability == "NOT_APPLICABLE":
            if not criterion.get("reason") and not criterion.get("evidence"):
                raise ValueError(f"criteria[{index}] needs reason or evidence for NOT_APPLICABLE")
            if criterion.get("reason") is not None:
                text(criterion["reason"], f"criteria[{index}].reason")
            if criterion.get("evidence") is not None:
                text(criterion["evidence"], f"criteria[{index}].evidence")
            continue

        score = number(criterion.get("score"), f"criteria[{index}].score")
        weight = number(criterion.get("weight"), f"criteria[{index}].weight")
        if not 0 <= score <= 4:
            raise ValueError(f"criteria[{index}].score must be between 0 and 4")
        if weight <= 0:
            raise ValueError(f"criteria[{index}].weight must be greater than zero")
        text(criterion.get("evidence"), f"criteria[{index}].evidence")
        if "mandatory" in criterion and not isinstance(criterion["mandatory"], bool):
            raise ValueError(f"criteria[{index}].mandatory must be boolean")
        if "minimum_score" in criterion:
            minimum_score = number(criterion["minimum_score"], f"criteria[{index}].minimum_score")
            if not 0 <= minimum_score <= 4:
                raise ValueError(f"criteria[{index}].minimum_score must be between 0 and 4")
        applicable.append(criterion)

    denominator = sum(number(item["weight"], "weight") for item in applicable)
    numerator = sum(
        (number(item["score"], "score") / 4.0) * number(item["weight"], "weight")
        for item in applicable
    )
    score = round((numerator / denominator) * 100, 2) if denominator else 0.0
    threshold = number(review.get("pass_threshold_percent", 85), "pass_threshold_percent")
    if not 0 <= threshold <= 100:
        raise ValueError("pass_threshold_percent must be between 0 and 100")
    hard_fail = review.get("hard_fail", False)
    if not isinstance(hard_fail, bool):
        raise ValueError("hard_fail must be boolean")
    findings = review.get("findings", [])
    unresolved_severe = validate_findings(findings)
    mandatory_failure = any(
        bool(item.get("mandatory", False))
        and number(item.get("score"), "score") < number(item.get("minimum_score", 3), "minimum_score")
        for item in applicable
    )

    if insufficient_context or not applicable:
        verdict = "BLOCKED"
    elif score >= threshold and not hard_fail and not unresolved_severe and not mandatory_failure:
        verdict = "PASS"
    else:
        verdict = "REPAIR_REQUIRED"

    return {
        "score_percent": score,
        "threshold_percent": threshold,
        "denominator_weight": denominator,
        "hard_fail": hard_fail,
        "insufficient_context": insufficient_context,
        "unresolved_severe_findings": unresolved_severe,
        "mandatory_failure": mandatory_failure,
        "verdict": verdict,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        result = calculate(read_object(args.input))
        if args.output:
            write_json_atomic(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        print(f"SCORE_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
