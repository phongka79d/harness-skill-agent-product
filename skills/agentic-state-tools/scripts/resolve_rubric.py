"""Resolve a deterministic review rubric from profile, task type, and risk flags."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from resolve_project_profile import load_data, resolve_profile
from risk_flags import normalize_risk_flags


RUBRIC_ROOT = Path(__file__).resolve().parents[1] / "profiles" / "rubrics"
REVIEW_POLICY_VERSION = "1"


CRITERION = {
    "CORRECTNESS": ("Functional correctness", True, 3),
    "REQUIREMENT_ALIGNMENT": ("Requirement alignment", True, 3),
    "SCOPE_COMPLIANCE": ("Scope compliance", True, 3),
    "REUSE": ("Reuse of existing components", False, 2),
    "YAGNI_KISS": ("Simplicity and scope discipline", False, 2),
    "MAINTAINABILITY": ("Maintainability", False, 2),
    "TESTING": ("Test quality and verification", True, 3),
    "SECURITY": ("Application security", False, 3),
    "PERFORMANCE": ("Relevant performance considerations", False, 2),
    "COMPATIBILITY": ("Compatibility and migration safety", True, 3),
    "OBSERVABILITY": ("Observability and diagnostics", False, 2),
    "ROLLBACK": ("Rollback and recovery readiness", True, 3),
    "THREAT_MODELING": ("Threat modeling and auditability", True, 3),
    "API_COMPATIBILITY": ("API compatibility and contract stability", True, 3),
    "DATA_INTEGRITY": ("Data integrity and invariant preservation", True, 3),
    "ACCESSIBILITY": ("Accessibility and inclusive interaction", True, 3),
    "UX_REGRESSION": ("User experience regression control", False, 2),
    "MIGRATION_SAFETY": ("Migration safety and reversibility", True, 3),
    "OPERABILITY": ("Operational readiness and diagnostics", True, 3),
    "DOCUMENTATION_COMPLETENESS": ("Documentation completeness", True, 3),
    "TEST_STRATEGY": ("Test strategy and coverage design", True, 3),
    "INTEGRATION_COVERAGE": ("Integration coverage and contract consistency", True, 3),
    "SCOPE_ALIGNMENT": ("Batch scope alignment", True, 3),
    "RECOVERY_READINESS": ("Recovery readiness", True, 3),
    "REGRESSION_CONTROL": ("Regression control", True, 3),
}

QUALITY_CRITERIA = {
    "lightweight": [
        ("CORRECTNESS", 35),
        ("REQUIREMENT_ALIGNMENT", 20),
        ("SCOPE_COMPLIANCE", 20),
        ("MAINTAINABILITY", 15),
        ("TESTING", 10),
    ],
    "standard": [
        ("CORRECTNESS", 25),
        ("REQUIREMENT_ALIGNMENT", 15),
        ("SCOPE_COMPLIANCE", 15),
        ("REUSE", 10),
        ("YAGNI_KISS", 10),
        ("MAINTAINABILITY", 10),
        ("TESTING", 15),
    ],
    "strict": [
        ("CORRECTNESS", 20),
        ("REQUIREMENT_ALIGNMENT", 15),
        ("SCOPE_COMPLIANCE", 10),
        ("TESTING", 15),
        ("SECURITY", 15),
        ("MAINTAINABILITY", 10),
        ("COMPATIBILITY", 5),
        ("OBSERVABILITY", 5),
        ("PERFORMANCE", 5),
    ],
    "critical": [
        ("CORRECTNESS", 15),
        ("REQUIREMENT_ALIGNMENT", 10),
        ("SCOPE_COMPLIANCE", 10),
        ("TESTING", 15),
        ("SECURITY", 15),
        ("THREAT_MODELING", 10),
        ("MAINTAINABILITY", 10),
        ("COMPATIBILITY", 5),
        ("OBSERVABILITY", 5),
        ("ROLLBACK", 5),
    ],
}

SECURITY_FLAGS = {
    "authentication",
    "authorization",
    "security_sensitive",
    "personal_data",
    "database",
    "destructive_operation",
    "external_api",
    "payments",
}

TASK_TYPE_ALIASES = {"quick_change": "general", "quick-change": "general"}


def load_extension(review_type: str, task_type: str) -> tuple[str, str, list[dict[str, Any]]]:
    directory = "batch" if review_type == "batch" else "task"
    requested = task_type.strip().lower()
    extension_id = TASK_TYPE_ALIASES.get(requested, requested)
    path = RUBRIC_ROOT / directory / f"{extension_id}.yaml"
    if not path.is_file() and review_type == "batch" and requested == "general":
        extension_id = "standard"
        path = RUBRIC_ROOT / directory / "standard.yaml"
    if not path.is_file():
        raise ValueError(f"unknown {review_type} rubric extension: {task_type}")
    raw = load_data(path)
    if raw.get("extension_id") != extension_id:
        raise ValueError(f"rubric extension ID does not match filename: {path.name}")
    version = raw.get("version")
    criteria = raw.get("criteria")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"rubric extension version is invalid: {path.name}")
    if not isinstance(criteria, list) or any(not isinstance(item, dict) for item in criteria):
        raise ValueError(f"rubric extension criteria are invalid: {path.name}")
    return extension_id, version, criteria


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_object(value: str, field: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must be a JSON object")
    return parsed


def resolve_rubric(
    profile_id: str,
    task_type: str,
    risk_flags: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    *,
    review_type: str = "task",
) -> dict[str, Any]:
    risk_flags = normalize_risk_flags(risk_flags)
    profile = resolve_profile(profile_id)
    quality_level = profile["quality_level"]
    if quality_level not in QUALITY_CRITERIA:
        raise ValueError(f"unsupported quality level: {quality_level}")
    if review_type not in {"task", "batch"}:
        raise ValueError("review_type must be task or batch")
    overrides = overrides or {}
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be an object")
    threshold_override = overrides.get("threshold_percent")
    risky_override = (
        threshold_override is not None
        and isinstance(threshold_override, (int, float))
        and not isinstance(threshold_override, bool)
        and threshold_override < profile["default_threshold_percent"]
    ) or bool(overrides.get("exclude_criteria")) or bool(overrides.get("weight_overrides")) or bool(overrides.get("architecture_change"))
    if risky_override:
        approval_id = overrides.get("approval_id")
        approval_decision = str(overrides.get("approval_decision", "")).upper()
        if not isinstance(approval_id, str) or not approval_id.strip() or approval_decision != "APPROVED":
            raise ValueError("risky rubric override requires an APPROVED approval record")
    extension_id, extension_version, extension_criteria = load_extension(review_type, task_type)
    excluded = {str(item).upper() for item in overrides.get("exclude_criteria", [])}
    included = {str(item).upper() for item in overrides.get("include_criteria", [])}
    enabled = [(criterion_id, weight) for criterion_id, weight in QUALITY_CRITERIA[quality_level] if criterion_id not in excluded]
    for extension in extension_criteria:
        criterion_id = str(extension.get("id", "")).upper()
        if criterion_id not in CRITERION:
            raise ValueError(f"unknown rubric criterion in extension: {criterion_id}")
        enabled = [(item_id, weight) for item_id, weight in enabled if item_id != criterion_id]
        if criterion_id not in excluded:
            enabled.append((criterion_id, extension.get("weight", 10)))
    for criterion_id in sorted(included):
        if criterion_id not in CRITERION:
            raise ValueError(f"unknown rubric criterion override: {criterion_id}")
        if criterion_id not in {item[0] for item in enabled}:
            enabled.append((criterion_id, 10))

    weight_overrides = overrides.get("weight_overrides", {})
    if not isinstance(weight_overrides, dict):
        raise ValueError("weight_overrides must be an object")
    normalized_weight_overrides = {str(key).upper(): value for key, value in weight_overrides.items()}
    enabled = [
        (criterion_id, normalized_weight_overrides.get(criterion_id, weight))
        for criterion_id, weight in enabled
    ]

    risk_enabled = {key for key, value in risk_flags.items() if value is True}
    conditional_security = bool(risk_enabled & SECURITY_FLAGS)
    conditional_performance = any(
        risk_flags.get(key) is True
        for key in ("database", "external_api", "concurrency", "shared_state", "infrastructure")
    )
    applicability: dict[str, dict[str, str]] = {}
    criteria: list[dict[str, Any]] = []
    weights: dict[str, float] = {}
    for criterion_id, weight in enabled:
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
            raise ValueError(f"rubric weight must be a positive number: {criterion_id}")
        title, mandatory, minimum_score = CRITERION[criterion_id]
        applicability[criterion_id] = {"status": "APPLICABLE", "evidence": "Included by the resolved quality profile."}
        criteria.append({"id": criterion_id, "title": title, "weight": weight, "mandatory": mandatory, "minimum_score": minimum_score, "evidence_required": True, "applicability": "APPLICABLE"})
        weights[criterion_id] = weight

    conditional: list[tuple[str, bool, str]] = [
        ("SECURITY", conditional_security, "No security-relevant risk flag was enabled."),
        ("PERFORMANCE", conditional_performance, "No performance-relevant risk flag was enabled."),
    ]
    for criterion_id, applies, reason in conditional:
        if criterion_id in excluded or criterion_id in weights:
            if criterion_id in excluded:
                applicability[criterion_id] = {"status": "NOT_APPLICABLE", "evidence": "Explicitly excluded by the approved override."}
            continue
        title, mandatory, minimum_score = CRITERION[criterion_id]
        status = "APPLICABLE" if applies else "NOT_APPLICABLE"
        applicability[criterion_id] = {"status": status, "evidence": "Risk flags require this criterion." if applies else reason}
        criteria.append({"id": criterion_id, "title": title, "weight": 10, "mandatory": mandatory, "minimum_score": minimum_score, "evidence_required": True, "applicability": status, "reason": None if applies else reason})
        if applies:
            weights[criterion_id] = 10

    for criterion_id in sorted(excluded):
        applicability.setdefault(criterion_id, {"status": "NOT_APPLICABLE", "evidence": "Excluded by an approved override."})

    threshold = overrides.get("threshold_percent", profile["default_threshold_percent"])
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 100:
        raise ValueError("threshold_percent must be between 0 and 100")
    rubric = {
        "rubric_id": f"{review_type.upper()}_REVIEW_{task_type.upper()}_{quality_level.upper()}_V1",
        "rubric_version": "1.1",
        "review_type": review_type,
        "task_type": task_type,
        "profile_id": profile["profile_id"],
        "profile_version": profile["profile_version"],
        "profile_hash": profile["profile_hash"],
        "risk_flags": risk_flags,
        "review_policy_version": REVIEW_POLICY_VERSION,
        "pass_threshold_percent": threshold,
        "hard_fail_rules": ["acceptance_criteria_not_met", "required_verification_failed", "changes_outside_write_scope", "unresolved_major_correctness_issue"],
        "criteria": criteria,
        "applicability": applicability,
        "resolved_weights": weights,
        "extension_ids": [extension_id],
        "extension_versions": {extension_id: extension_version},
        "override_approval_id": overrides.get("approval_id") if risky_override else None,
    }
    rubric["rubric_hash"] = hashlib.sha256(canonical(rubric).encode("utf-8")).hexdigest()
    return rubric


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--task-type", default="general")
    parser.add_argument("--risk-flags", default="{}")
    parser.add_argument("--overrides", default="{}")
    parser.add_argument("--review-type", choices=("task", "batch"), default="task")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        result = resolve_rubric(args.profile, args.task_type, parse_object(args.risk_flags, "risk_flags"), parse_object(args.overrides, "overrides"), review_type=args.review_type)
        if args.output:
            from runtime_utils import write_json_atomic

            write_json_atomic(args.output, result)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"RUBRIC_RESOLUTION_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
