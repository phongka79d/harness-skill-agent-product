"""Validate immutable review-policy pins from a canonical task or batch contract."""

from __future__ import annotations

from typing import Any

from risk_flags import normalize_risk_flags
from resolve_rubric import resolve_rubric


CONTRACT_FIELDS = (
    "project_profile",
    "profile_hash",
    "task_type",
    "risk_flags",
    "review_type",
    "rubric_id",
    "rubric_version",
    "rubric_hash",
    "review_policy_version",
)
RUBRIC_PIN_FIELDS = (
    "profile_id",
    "profile_hash",
    "task_type",
    "risk_flags",
    "review_type",
    "rubric_id",
    "rubric_version",
    "rubric_hash",
    "review_policy_version",
)


def contract_from_rubric(rubric: Any) -> dict[str, Any]:
    if not isinstance(rubric, dict):
        raise ValueError("rubric must be an object")
    missing = [field for field in RUBRIC_PIN_FIELDS if field not in rubric]
    if missing:
        raise ValueError("rubric is missing contract fields: " + ", ".join(missing))
    return {
        "project_profile": rubric["profile_id"],
        "profile_hash": rubric["profile_hash"],
        "task_type": rubric["task_type"],
        "risk_flags": rubric["risk_flags"],
        "review_type": rubric["review_type"],
        "rubric_id": rubric["rubric_id"],
        "rubric_version": rubric["rubric_version"],
        "rubric_hash": rubric["rubric_hash"],
        "review_policy_version": rubric["review_policy_version"],
    }


def validate_contract(contract: Any, *, review_type: str | None = None) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError("review_contract must be an object")
    missing = [field for field in CONTRACT_FIELDS if field not in contract]
    if missing:
        raise ValueError("review_contract is missing fields: " + ", ".join(missing))
    if review_type is not None and contract.get("review_type") != review_type:
        raise ValueError(f"review_contract.review_type must be {review_type}")
    if not isinstance(contract.get("project_profile"), str) or not contract["project_profile"].strip():
        raise ValueError("review_contract.project_profile must be a non-empty string")
    try:
        normalized_risk_flags = normalize_risk_flags(contract.get("risk_flags"))
    except ValueError as exc:
        raise ValueError(f"review_contract.risk_flags is invalid: {exc}") from exc
    try:
        canonical = resolve_rubric(
            contract["project_profile"],
            contract["task_type"],
            normalized_risk_flags,
            review_type=contract["review_type"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"review_contract cannot be resolved: {exc}") from exc
    expected = {
        "project_profile": canonical["profile_id"],
        "profile_hash": canonical["profile_hash"],
        "task_type": canonical["task_type"],
        "risk_flags": canonical["risk_flags"],
        "review_type": canonical["review_type"],
        "rubric_id": canonical["rubric_id"],
        "rubric_version": canonical["rubric_version"],
        "rubric_hash": canonical["rubric_hash"],
        "review_policy_version": canonical["review_policy_version"],
    }
    for field in CONTRACT_FIELDS:
        if contract.get(field) != expected[field]:
            raise ValueError(f"review_contract.{field} does not match the canonical rubric source")
    return canonical


def validate_rubric_against_contract(
    rubric: Any,
    contract: Any,
    *,
    review_type: str,
    allow_approved_override: bool = False,
) -> None:
    canonical = validate_contract(contract, review_type=review_type)
    if not isinstance(rubric, dict):
        raise ValueError("resolved_rubric must be an object")
    override_approval_id = rubric.get("override_approval_id")
    if override_approval_id is not None and not allow_approved_override:
        raise ValueError("rubric overrides are not valid for an unmodified review contract")
    for field in RUBRIC_PIN_FIELDS:
        # An authorized override gets a new self-consistent hash; every other contract pin stays immutable.
        if field == "rubric_hash" and override_approval_id is not None and allow_approved_override:
            continue
        expected = canonical["profile_id"] if field == "profile_id" else canonical.get(field)
        if rubric.get(field) != expected:
            raise ValueError(f"resolved_rubric.{field} does not match the pinned review contract")
