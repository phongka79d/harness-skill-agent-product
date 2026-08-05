"""Validate immutable review-policy pins from a canonical task or batch contract."""

from __future__ import annotations

import hashlib
import json
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

REVIEW_STAGES = ("SPEC_COMPLIANCE", "CODE_QUALITY")
LIGHTWEIGHT_REVIEW_PROFILES = frozenset({"personal", "quick_change", "prototype"})


def required_review_stages(profile_id: Any) -> tuple[str, ...]:
    """Return the final review stages required by the resolved profile."""

    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("review profile must be a non-empty string")
    if profile_id in LIGHTWEIGHT_REVIEW_PROFILES:
        return ("SPEC_COMPLIANCE",)
    return REVIEW_STAGES


def canonical_artifact_hash(identity: dict[str, Any]) -> str:
    """Calculate the stable identity hash for the implementation under review."""

    value = dict(identity)
    value.pop("artifact_hash", None)
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_artifact_identity(identity: Any, *, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate the immutable implementation identity carried by a staged review."""

    if not isinstance(identity, dict):
        raise ValueError("review.artifact_identity must be an object")
    required = ("task_id", "task_revision", "run_id", "attempt_id", "dispatch_id", "workspace_hash", "artifact_hash")
    missing = [field for field in required if field not in identity]
    if missing:
        raise ValueError("review.artifact_identity is missing fields: " + ", ".join(missing))
    if not isinstance(identity["task_id"], str) or not identity["task_id"].strip():
        raise ValueError("review.artifact_identity.task_id must be a non-empty string")
    if isinstance(identity["task_revision"], bool) or not isinstance(identity["task_revision"], int) or identity["task_revision"] < 1:
        raise ValueError("review.artifact_identity.task_revision must be a positive integer")
    for field in ("run_id", "attempt_id", "dispatch_id", "workspace_hash", "artifact_hash"):
        if not isinstance(identity[field], str) or not identity[field].strip():
            raise ValueError(f"review.artifact_identity.{field} must be a non-empty string")
    if len(identity["workspace_hash"]) != 64 or len(identity["artifact_hash"]) != 64:
        raise ValueError("review.artifact_identity hashes must be SHA-256 values")
    if identity["artifact_hash"] != canonical_artifact_hash(identity):
        raise ValueError("review.artifact_identity.artifact_hash does not match its contents")
    normalized = dict(identity)
    if expected is not None and normalized != expected:
        raise ValueError("review artifact identity does not match the prior or current implementation")
    return normalized


def validate_stage_chain(review: Any, prior_review: Any = None, *, profile_id: Any = None) -> dict[str, Any]:
    """Validate stage ordering and immutable identity for a task review chain."""

    if not isinstance(review, dict):
        raise ValueError("review must be an object")
    stage = review.get("stage")
    if stage not in REVIEW_STAGES:
        raise ValueError("review.stage must be SPEC_COMPLIANCE or CODE_QUALITY")
    identity = validate_artifact_identity(review.get("artifact_identity"))
    if profile_id is not None and stage not in required_review_stages(profile_id):
        if stage == "CODE_QUALITY" and not isinstance(prior_review, dict):
            raise ValueError("CODE_QUALITY requires a preceding SPEC_COMPLIANCE review")
    if stage == "SPEC_COMPLIANCE":
        if isinstance(prior_review, dict) and prior_review.get("stage") == "CODE_QUALITY":
            raise ValueError("a new SPEC_COMPLIANCE review is required after a CODE_QUALITY correction")
        return identity
    if not isinstance(prior_review, dict) or prior_review.get("stage") != "SPEC_COMPLIANCE":
        raise ValueError("CODE_QUALITY must follow a passing SPEC_COMPLIANCE review")
    if str(prior_review.get("verdict", "")).upper() != "PASS":
        raise ValueError("CODE_QUALITY requires a passing SPEC_COMPLIANCE review")
    prior_identity = validate_artifact_identity(prior_review.get("artifact_identity"))
    if identity != prior_identity:
        raise ValueError("CODE_QUALITY review artifact identity does not match SPEC_COMPLIANCE")
    if review.get("previous_review_id") != prior_review.get("review_id"):
        raise ValueError("CODE_QUALITY must link the immediately preceding SPEC_COMPLIANCE review")
    if review.get("previous_stage") != "SPEC_COMPLIANCE":
        raise ValueError("CODE_QUALITY previous_stage must be SPEC_COMPLIANCE")
    if review.get("previous_artifact_identity") != prior_identity:
        raise ValueError("CODE_QUALITY previous_artifact_identity does not match SPEC_COMPLIANCE")
    return identity


def validate_final_review_stages(
    reviews: Any,
    *,
    profile_id: Any,
    review_index: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Validate the final task-review artifacts consumed by a batch review."""

    if not isinstance(reviews, list) or not reviews:
        raise ValueError("batch review requires at least one task review")
    required = required_review_stages(profile_id)
    for index, review in enumerate(reviews):
        if not isinstance(review, dict):
            raise ValueError(f"task review {index} must be an object")
        stage = review.get("stage")
        if stage is None:
            # Existing artifacts are accepted only for the legacy-compatible lightweight path.
            if required != ("SPEC_COMPLIANCE",):
                raise ValueError(f"task review {index} has no final review stage")
            continue
        if stage != required[-1] or str(review.get("verdict", "")).upper() != "PASS":
            raise ValueError(f"task review {index} does not have a passing final {required[-1]} stage")
        validate_artifact_identity(review.get("artifact_identity"))
        if required == REVIEW_STAGES:
            if review.get("previous_stage") != "SPEC_COMPLIANCE":
                raise ValueError(f"task review {index} is missing its SPEC_COMPLIANCE predecessor")
            if not isinstance(review.get("previous_review_id"), str) or not review["previous_review_id"].strip():
                raise ValueError(f"task review {index} is missing previous_review_id")
            previous_identity = validate_artifact_identity(review.get("previous_artifact_identity"))
            if previous_identity != review.get("artifact_identity"):
                raise ValueError(f"task review {index} has mismatched stage identities")
            if review_index is not None:
                previous_id = review["previous_review_id"]
                previous_review = review_index.get(previous_id)
                if not isinstance(previous_review, dict):
                    raise ValueError(f"task review {index} predecessor is missing: {previous_id}")
                validate_stage_chain(review, previous_review, profile_id=profile_id)


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
