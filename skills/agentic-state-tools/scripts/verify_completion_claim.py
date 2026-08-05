"""Reject completion claims that are not fresh, task-bound, and evidence-backed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    read_object,
    read_payload,
    runtime_lock,
    parse_timestamp,
    utc_now,
    validate_identifier,
)
from validate_payload import validate
from verification_contract import (
    PHASES,
    hidden_failure_output,
    is_strict_profile,
    load_task_state,
    normalize_relevant_files,
    profile_policy,
    validate_identity,
    workspace_hash,
)


ROOT = Path(__file__).resolve().parents[1]
CLAIM_SCHEMA = ROOT / "schemas" / "completion-claim.schema.json"
EVIDENCE_SCHEMA = ROOT / "schemas" / "verification-evidence.schema.json"


def _schema_errors(value: Any, schema_path: Path) -> list[str]:
    return validate(value, read_object(schema_path), base_path=schema_path.parent)


def _load_evidence(root: Path, task_id: str, evidence_id: str) -> dict[str, Any]:
    validate_identifier(evidence_id, "evidence_id")
    path = root / "work" / task_id / "verification" / f"{evidence_id}.json"
    if not path.is_file():
        raise ValueError(f"verification evidence is missing: {evidence_id}")
    evidence = read_object(path)
    errors = _schema_errors(evidence, EVIDENCE_SCHEMA)
    if errors:
        raise ValueError(f"verification evidence {evidence_id} is invalid: " + "; ".join(errors))
    if evidence.get("evidence_id") != evidence_id:
        raise ValueError(f"verification evidence identity is invalid: {evidence_id}")
    return evidence


def _validate_exceptions(claim: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    raw = claim.get("exceptions", [])
    if not isinstance(raw, list):
        raise ValueError("completion claim exceptions must be an array")
    allowed = set(policy.get("allowed_exception_types", []))
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("completion claim exceptions must contain objects")
        exception_id = item.get("exception_id")
        exception_type = item.get("type")
        if not isinstance(exception_id, str) or not exception_id.strip() or exception_id in seen:
            raise ValueError("completion claim exception_id must be unique and non-empty")
        if not isinstance(exception_type, str) or exception_type.casefold() not in {str(value).casefold() for value in allowed}:
            raise ValueError(f"verification exception type is not allowed by profile: {exception_type}")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ValueError("verification exception reason is required")
        authority = item.get("authority")
        if not (
            isinstance(authority, str)
            and authority.strip()
            or isinstance(authority, dict)
            and bool(authority)
        ):
            raise ValueError("verification exception authority is required")
        alternative = item.get("alternative_verification")
        valid_alternative = (
            isinstance(alternative, list)
            and bool(alternative)
            and all(isinstance(value, str) and value.strip() for value in alternative)
        ) or (
            isinstance(alternative, dict)
            and isinstance(alternative.get("command"), str)
            and bool(alternative["command"].strip())
            and isinstance(alternative.get("exit_code"), int)
        )
        if not valid_alternative:
            raise ValueError("verification exception requires alternative_verification")
        if not item.get("expires_at") and not item.get("follow_up"):
            raise ValueError("verification exception requires expires_at or follow_up")
        if item.get("expires_at"):
            if parse_timestamp(item["expires_at"]) <= parse_timestamp(utc_now()):
                raise ValueError(f"verification exception is expired: {exception_id}")
        seen.add(exception_id)
        normalized.append(item)
    return normalized


def _missing_phase_reasons(
    claim: dict[str, Any],
    evidence: list[dict[str, Any]],
    policy: dict[str, Any],
    exceptions: list[dict[str, Any]],
) -> list[str]:
    change_kind = claim["change_kind"]
    behavior_types = set(policy.get("behavior_change_types", []))
    harness_available = claim.get("test_harness_available", True)
    tdd_mode = policy.get("tdd_mode")
    tdd_required = change_kind in behavior_types and (
        tdd_mode == "MANDATORY" or (tdd_mode == "REQUIRED_IF_HARNESS" and harness_available)
    )
    phases = {item["phase"] for item in evidence}
    reasons: list[str] = []
    if tdd_required:
        for phase in ("RED", "GREEN"):
            if phase not in phases:
                reasons.append(f"missing required {phase} verification evidence")
    broad_mode = policy.get("broad_suite_mode")
    broad_required = bool(claim.get("broad_required"))
    if broad_mode == "MANDATORY" and change_kind in behavior_types:
        broad_required = True
    if broad_mode == "RISK_BASED" and claim.get("risk_level") in {"high", "critical"}:
        broad_required = True
    if broad_required and "BROAD" not in phases:
        reasons.append("missing required BROAD verification evidence")
    if reasons and exceptions:
        # Exceptions are permitted only after their machine-readable alternative is present.
        return []
    return reasons


def validate_claim(payload: Any, *, project_root: str | Path, root: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("completion claim must be an object")
    schema_errors = _schema_errors(payload, CLAIM_SCHEMA)
    if schema_errors:
        raise ValueError("completion claim schema validation failed: " + "; ".join(schema_errors))
    claim = dict(payload)
    task_id = claim["task_id"]
    validate_identifier(task_id, "task_id")
    task_state = load_task_state(root, task_id)
    validate_identity(claim, task_state, label="completion claim")
    profile, policy = profile_policy(claim["profile_id"])
    if claim.get("profile_hash") is not None and claim["profile_hash"] != profile["profile_hash"]:
        raise ValueError("completion claim profile_hash is stale")
    if claim.get("legacy_migration") is True and is_strict_profile(profile["profile_id"]):
        raise ValueError("LEGACY_UNVERIFIED evidence cannot satisfy strict completion claims")

    evidence_ids = claim.get("evidence_ids") or claim.get("verification_evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise ValueError("completion claim requires evidence IDs; a summary is not evidence")
    evidence = [_load_evidence(root, task_id, evidence_id) for evidence_id in evidence_ids]
    by_id = {item["evidence_id"]: item for item in evidence}
    if len(by_id) != len(evidence_ids):
        raise ValueError("completion claim evidence_ids must be unique")
    for item in evidence:
        for field in ("task_id", "run_id", "attempt_id", "plan_revision", "task_revision"):
            if item.get(field) != claim.get(field):
                raise ValueError(f"verification evidence {item['evidence_id']} {field} does not match completion claim")
        # RED is intentionally the pre-change baseline. It remains historical
        # proof of the intended failure; GREEN/BROAD must be fresh at claim time.
        if item["phase"] != "RED":
            current_evidence_hash = workspace_hash(project_root, item.get("relevant_files", []))
            if current_evidence_hash != item["workspace_hash"]:
                raise ValueError(f"verification evidence is stale for current workspace: {item['evidence_id']}")
        if item["phase"] in {"GREEN", "BROAD"} and (item["status"] != "PASS" or item["exit_code"] != 0):
            raise ValueError(f"{item['phase']} evidence is not a passing command: {item['evidence_id']}")
        if item["phase"] == "RED" and (
            item["exit_code"] in (None, 0)
            or not isinstance(item.get("failure_signature"), str)
            or not item["failure_signature"].strip()
        ):
            raise ValueError(f"RED evidence lacks an intended non-zero failure signature: {item['evidence_id']}")
        hidden = hidden_failure_output(item)
        if hidden and item["phase"] in {"GREEN", "BROAD"}:
            raise ValueError(f"verification output hides skipped or failed checks: {item['evidence_id']}")
    claim_hashes = {item["workspace_hash"] for item in evidence}
    if claim["workspace_hash"] not in claim_hashes:
        raise ValueError("completion claim.workspace_hash is not bound to supplied evidence")
    claim_files = normalize_relevant_files(claim.get("relevant_files"))
    if claim_files and workspace_hash(project_root, claim_files) != claim["workspace_hash"]:
        raise ValueError("completion claim.workspace_hash is stale for relevant files")

    mappings = claim.get("acceptance_criteria") or claim.get("acceptance_evidence_mapping")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("completion claim has no acceptance-criteria evidence mapping")
    mapped_criteria: set[str] = set()
    for mapping in mappings:
        criterion_id = mapping["criterion_id"]
        if criterion_id in mapped_criteria:
            raise ValueError(f"acceptance criterion is mapped more than once: {criterion_id}")
        mapped_criteria.add(criterion_id)
        mapped_ids = mapping["evidence_ids"]
        unknown = sorted(set(mapped_ids) - set(evidence_ids))
        if unknown:
            raise ValueError(f"acceptance criterion {criterion_id} references unknown evidence: {', '.join(unknown)}")
        for evidence_id in mapped_ids:
            if criterion_id not in set(by_id[evidence_id].get("acceptance_criterion_ids", [])):
                raise ValueError(f"evidence {evidence_id} does not claim acceptance criterion {criterion_id}")
        if mapping.get("status") == "NOT_APPLICABLE" and not mapping.get("reason"):
            raise ValueError(f"NOT_APPLICABLE criterion requires a reason: {criterion_id}")
    if not mapped_criteria:
        raise ValueError("completion claim has no acceptance-criteria evidence mapping")
    declared_criteria = set(claim.get("acceptance_criterion_ids", []))
    state_criteria = task_state.get("acceptance_criteria", [])
    if isinstance(state_criteria, list):
        declared_criteria.update(
            item.get("criterion_id")
            for item in state_criteria
            if isinstance(item, dict) and isinstance(item.get("criterion_id"), str)
        )
    missing_criteria = sorted(item for item in declared_criteria if item not in mapped_criteria)
    if missing_criteria:
        raise ValueError("acceptance criteria have no evidence mapping: " + ", ".join(missing_criteria))

    exceptions = _validate_exceptions(claim, policy)
    reasons = _missing_phase_reasons(claim, evidence, policy, exceptions)
    if reasons:
        raise ValueError("completion claim verification is incomplete: " + "; ".join(reasons))
    phases = {item["phase"] for item in evidence}
    if claim["change_kind"] in set(policy.get("behavior_change_types", [])) and policy.get("tdd_mode") == "EXCEPTION_ALLOWED" and not {"RED", "GREEN"}.issubset(phases) and not exceptions:
        raise ValueError("profile permits a TDD exception only when a machine-readable exception is recorded")
    return {
        **claim,
        "verification_status": "VERIFIED",
        "profile_hash": profile["profile_hash"],
        "evidence_count": len(evidence),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
        with runtime_lock(args.project_root) as root:
            result = validate_claim(payload, project_root=root.parent, root=root)
    except RuntimeNotInitializedError as exc:
        print(f"COMPLETION_CLAIM_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"COMPLETION_CLAIM_REJECTED: {exc}", file=sys.stderr)
        return 1
    print("COMPLETION_CLAIM_ACCEPTED: " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
