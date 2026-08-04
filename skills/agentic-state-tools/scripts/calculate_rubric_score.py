"""Calculate an evidence-based weighted rubric verdict deterministically."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any

from runtime_utils import read_object, write_json_atomic
from resolve_rubric import resolve_rubric


VALID_APPLICABILITY = {"APPLICABLE", "NOT_APPLICABLE", "INSUFFICIENT_CONTEXT"}
VALID_SEVERITIES = {"CRITICAL", "MAJOR", "MINOR", "SUGGESTION"}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


IMMUTABLE_RUBRIC_FIELDS = (
    "rubric_id",
    "rubric_version",
    "review_type",
    "task_type",
    "profile_id",
    "profile_version",
    "profile_hash",
    "risk_flags",
    "review_policy_version",
    "hard_fail_rules",
    "extension_ids",
    "extension_versions",
)
MUTABLE_OVERRIDE_FIELDS = (
    "pass_threshold_percent",
    "criteria",
    "applicability",
    "resolved_weights",
)


def validate_rubric_identity(rubric: Any, allow_approved_override: bool = False) -> None:
    if not isinstance(rubric, dict):
        raise ValueError("resolved_rubric must be an object")
    for field in (
        "rubric_id",
        "rubric_version",
        "review_type",
        "task_type",
        "profile_id",
        "profile_version",
        "profile_hash",
        "risk_flags",
        "review_policy_version",
        "rubric_hash",
        "hard_fail_rules",
        "criteria",
        "applicability",
        "resolved_weights",
        "pass_threshold_percent",
    ):
        if field not in rubric:
            raise ValueError(f"resolved_rubric.{field} is required")
    if not isinstance(rubric["rubric_hash"], str) or not isinstance(rubric["criteria"], list) or not isinstance(rubric["hard_fail_rules"], list):
        raise ValueError("resolved_rubric identity fields have invalid types")
    if not isinstance(rubric["applicability"], dict) or not isinstance(rubric["resolved_weights"], dict):
        raise ValueError("resolved_rubric applicability and resolved_weights must be objects")
    without_hash = dict(rubric)
    supplied_hash = without_hash.pop("rubric_hash", None)
    calculated_hash = hashlib.sha256(canonical(without_hash).encode("utf-8")).hexdigest()
    if supplied_hash != calculated_hash:
        raise ValueError("resolved_rubric.rubric_hash does not match its contents")
    override_approval_id = rubric.get("override_approval_id")
    if override_approval_id is not None and (not isinstance(override_approval_id, str) or not override_approval_id.strip()):
        raise ValueError("resolved_rubric.override_approval_id must be a non-empty string")
    if override_approval_id is not None and not allow_approved_override:
        raise ValueError("rubric overrides require a separately approved canonical contract")
    try:
        canonical_rubric = resolve_rubric(
            rubric["profile_id"],
            rubric["task_type"],
            rubric["risk_flags"],
            review_type=rubric["review_type"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"resolved_rubric cannot be resolved from the canonical rubric source: {exc}") from exc
    for field in IMMUTABLE_RUBRIC_FIELDS:
        if rubric.get(field) != canonical_rubric.get(field):
            raise ValueError(f"resolved_rubric.{field} does not match the canonical rubric source")
    if override_approval_id is None or not allow_approved_override:
        for field in MUTABLE_OVERRIDE_FIELDS:
            if rubric.get(field) != canonical_rubric.get(field):
                raise ValueError(f"resolved_rubric.{field} does not match the canonical rubric source")


def validate_resolved_rubric(review: dict[str, Any], allow_approved_override: bool = False) -> None:
    rubric = review.get("resolved_rubric")
    if rubric is None:
        return
    validate_rubric_identity(rubric, allow_approved_override=allow_approved_override)
    if any(not isinstance(item, dict) for item in rubric["criteria"]):
        raise ValueError("resolved_rubric.criteria must contain objects")
    definitions = {item.get("id"): item for item in rubric["criteria"]}
    if len(definitions) != len(rubric["criteria"]) or any(not isinstance(identifier, str) or not identifier for identifier in definitions):
        raise ValueError("resolved_rubric.criteria must contain unique object IDs")
    weights = rubric["resolved_weights"]
    if not isinstance(weights, dict):
        raise ValueError("resolved_rubric.resolved_weights must be an object")
    applicable_ids = {
        criterion_id
        for criterion_id, definition in definitions.items()
        if str(definition.get("applicability", "APPLICABLE")).upper() == "APPLICABLE"
    }
    if set(weights) != applicable_ids:
        raise ValueError("resolved rubric weights do not match applicable canonical criteria")
    for criterion_id, weight in weights.items():
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
            raise ValueError(f"resolved rubric weight is invalid: {criterion_id}")
        if definitions[criterion_id].get("weight") != weight:
            raise ValueError(f"resolved rubric weight does not match criterion definition: {criterion_id}")
    submitted = review.get("criteria", [])
    if not isinstance(submitted, list):
        raise ValueError("review.criteria must be an array")
    if any(not isinstance(item, dict) for item in submitted):
        raise ValueError("review criteria must contain objects")
    submitted_ids = [item.get("id") for item in submitted]
    if any(not isinstance(identifier, str) or not identifier for identifier in submitted_ids):
        raise ValueError("review criteria must contain non-empty IDs")
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ValueError("duplicate review criterion IDs are not allowed")
    if set(submitted_ids) != set(weights):
        missing = sorted(set(weights) - set(submitted_ids))
        extra = sorted(set(submitted_ids) - set(weights))
        raise ValueError(f"review criterion set does not match canonical rubric; missing={missing}, extra={extra}")
    canonical_fields = {
        "rubric_id": rubric["rubric_id"],
        "rubric_version": rubric["rubric_version"],
        "rubric_hash": rubric["rubric_hash"],
        "pass_threshold_percent": rubric["pass_threshold_percent"],
        "hard_fail_rules": rubric["hard_fail_rules"],
    }
    for field, expected in canonical_fields.items():
        if field in review and review[field] != expected:
            raise ValueError(f"review.{field} must match canonical rubric")
    if "hard_fail" in review:
        raise ValueError("review.hard_fail is reviewer-controlled policy and is not accepted with a canonical rubric")
    for criterion in submitted:
        criterion_id = criterion.get("id") if isinstance(criterion, dict) else None
        if criterion_id not in definitions:
            raise ValueError(f"review criterion is not present in resolved rubric: {criterion_id}")
        definition = definitions[criterion_id]
        if str(criterion.get("applicability", "APPLICABLE")).upper() != str(definition.get("applicability", "APPLICABLE")).upper():
            raise ValueError(f"criterion applicability does not match resolved rubric: {criterion_id}")
        if definition.get("applicability", "APPLICABLE") == "APPLICABLE":
            for field in ("weight", "mandatory", "minimum_score"):
                if field in criterion and criterion[field] != definition.get(field):
                    raise ValueError(f"criterion {field} does not match canonical rubric: {criterion_id}")


def unresolved_hard_fail_rules(findings: Any, rules: list[Any]) -> bool:
    canonical_rules = {str(rule) for rule in rules if isinstance(rule, str) and rule.strip()}
    if not canonical_rules:
        return False
    for finding in findings:
        if isinstance(finding, dict) and finding.get("resolved", False) is False and finding.get("rule") in canonical_rules:
            return True
    return False


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


def validate_hard_fail_checks(checks: Any, rules: list[Any]) -> bool:
    """Require evidence for every canonical hard-fail rule and derive its trigger state."""

    if not isinstance(checks, list):
        raise ValueError("review.hard_fail_checks is required for a canonical rubric")
    canonical_rules = [rule for rule in rules if isinstance(rule, str) and rule.strip()]
    if len(canonical_rules) != len(rules) or len(set(canonical_rules)) != len(canonical_rules):
        raise ValueError("resolved_rubric.hard_fail_rules must contain unique non-empty strings")
    submitted: dict[str, dict[str, Any]] = {}
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ValueError(f"review.hard_fail_checks[{index}] must be an object")
        rule = check.get("rule")
        if not isinstance(rule, str) or not rule.strip():
            raise ValueError(f"review.hard_fail_checks[{index}].rule must be a non-empty string")
        if rule not in canonical_rules:
            raise ValueError(f"review.hard_fail_checks contains a non-canonical rule: {rule}")
        if rule in submitted:
            raise ValueError(f"duplicate hard-fail check: {rule}")
        triggered = check.get("triggered")
        if not isinstance(triggered, bool):
            raise ValueError(f"review.hard_fail_checks[{index}].triggered must be boolean")
        text(check.get("evidence"), f"review.hard_fail_checks[{index}].evidence")
        submitted[rule] = check
    missing = sorted(set(canonical_rules) - set(submitted))
    if missing:
        raise ValueError("review.hard_fail_checks is missing canonical rules: " + ", ".join(missing))
    return any(check["triggered"] for check in submitted.values())


def calculate(review: dict[str, Any], *, allow_approved_override: bool = False) -> dict[str, Any]:
    if not isinstance(review, dict):
        raise ValueError("review must be a JSON object")
    validate_resolved_rubric(review, allow_approved_override=allow_approved_override)
    criteria = review.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("review requires at least one criterion")

    rubric = review.get("resolved_rubric")
    canonical_definitions = {}
    if isinstance(rubric, dict):
        canonical_definitions = {item["id"]: item for item in rubric["criteria"]}
    canonical_hard_fail = False
    if isinstance(rubric, dict):
        canonical_hard_fail = validate_hard_fail_checks(review.get("hard_fail_checks"), rubric["hard_fail_rules"])
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
        definition = canonical_definitions.get(criterion["id"])
        weight_value = definition.get("weight") if definition is not None else criterion.get("weight")
        weight = number(weight_value, f"criteria[{index}].weight")
        if not 0 <= score <= 4:
            raise ValueError(f"criteria[{index}].score must be between 0 and 4")
        if weight <= 0:
            raise ValueError(f"criteria[{index}].weight must be greater than zero")
        text(criterion.get("evidence"), f"criteria[{index}].evidence")
        if "mandatory" in criterion and not isinstance(criterion["mandatory"], bool):
            raise ValueError(f"criteria[{index}].mandatory must be boolean")
        minimum_value = definition.get("minimum_score") if definition is not None else criterion.get("minimum_score", 3)
        minimum_score = number(minimum_value, f"criteria[{index}].minimum_score")
        if not 0 <= minimum_score <= 4:
            raise ValueError(f"criteria[{index}].minimum_score must be between 0 and 4")
        applicable.append({**criterion, "weight": weight, "mandatory": definition.get("mandatory") if definition is not None else criterion.get("mandatory", False), "minimum_score": minimum_score})

    denominator = sum(number(item["weight"], "weight") for item in applicable)
    numerator = sum(
        (number(item["score"], "score") / 4.0) * number(item["weight"], "weight")
        for item in applicable
    )
    score = round((numerator / denominator) * 100, 2) if denominator else 0.0
    threshold_source = rubric.get("pass_threshold_percent") if isinstance(rubric, dict) else review.get("pass_threshold_percent", 85)
    threshold = number(threshold_source, "pass_threshold_percent")
    if not 0 <= threshold <= 100:
        raise ValueError("pass_threshold_percent must be between 0 and 100")
    hard_fail = review.get("hard_fail", False) if not isinstance(rubric, dict) else canonical_hard_fail
    if not isinstance(hard_fail, bool):
        raise ValueError("hard_fail must be boolean")
    findings = review.get("findings", [])
    unresolved_severe = validate_findings(findings)
    if isinstance(rubric, dict) and unresolved_hard_fail_rules(findings, rubric["hard_fail_rules"]):
        hard_fail = True
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
