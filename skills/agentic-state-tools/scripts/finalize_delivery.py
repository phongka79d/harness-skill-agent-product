"""Record and gate one controlled delivery outcome."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    ensure_runtime_initialized,
    parse_timestamp,
    read_object,
    read_payload,
    runtime_lock,
)
from validate_payload import validate
from write_artifact import write_validated


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "delivery-decision.schema.json"
OUTCOMES = {"MERGE_LOCAL", "PUSH_AND_CREATE_PR", "KEEP_BRANCH_AND_WORKTREE", "DISCARD_BRANCH_AND_WORKTREE"}
RECORDED_STATUSES = {"RECORDED", "COMPLETED"}
BLOCKED_STATUSES = {"BLOCKED", "NEEDS_RECONCILIATION"}
DESTRUCTIVE_ACTIONS = {"DESTRUCTIVE_OPERATION", "DESTRUCTIVE_ACTION", "WORKTREE_CLEANUP", "DELIVERY_DECISION"}


class DeliveryBlocked(ValueError):
    """The delivery decision is unsafe or not ready to persist as successful."""


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _schema_errors(decision: Any) -> list[str]:
    try:
        schema = read_object(SCHEMA_PATH)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DeliveryBlocked(f"delivery decision schema is unreadable: {exc}") from exc
    return validate(decision, schema, base_path=SCHEMA_PATH.parent)


def _load_task(root: Path, task_id: str) -> dict[str, Any]:
    path = root / "work" / task_id / "task-state.json"
    if not path.is_file():
        raise DeliveryBlocked(f"task state does not exist for {task_id}")
    value = read_object(path)
    if not isinstance(value, dict):
        raise DeliveryBlocked("task state must be an object")
    if value.get("task_id") != task_id:
        raise DeliveryBlocked("task state task_id does not match delivery decision")
    return value


def _check_task_identity(decision: dict[str, Any], task: dict[str, Any]) -> None:
    fields = {
        "task_id": "task_id",
        "batch_id": "batch_id",
        "plan_revision": "plan_revision",
        "task_revision": "revision",
        "run_id": "run_id",
        "attempt_id": "attempt_id",
        "dispatch_id": "dispatch_id",
        "branch_name": "branch_name",
        "worktree_path": "worktree_path",
        "base_commit": "base_commit",
    }
    for decision_field, task_field in fields.items():
        if task.get(task_field) is not None and decision.get(decision_field) != task.get(task_field):
            raise DeliveryBlocked(f"delivery decision {decision_field} does not match task state")
    task_verdict = task.get("review_verdict")
    if task_verdict is not None and str(task_verdict).upper() != "PASS":
        raise DeliveryBlocked("task review is not PASS")
    task_status = str(task.get("status", "")).upper()
    if decision["status"] in RECORDED_STATUSES and task_status not in {"ACCEPTED", "COMPLETED"}:
        raise DeliveryBlocked(f"task status {task_status or '<missing>'} is not ready for delivery finalization")


def _check_persisted_batch_review(root: Path, decision: dict[str, Any]) -> None:
    path = root / "work" / decision["batch_id"] / "review.json"
    if not path.is_file():
        return
    review = read_object(path)
    if not isinstance(review, dict) or str(review.get("verdict", "")).upper() != "PASS":
        raise DeliveryBlocked("persisted Batch Reviewer result is not PASS")


def _check_approval(root: Path, decision: dict[str, Any], *, require_persisted: bool, actor: dict[str, str] | None) -> None:
    approval = decision["approval"]
    if str(approval.get("decision", "")).upper() != "APPROVED":
        raise DeliveryBlocked("delivery outcome requires an APPROVED typed approval")
    if decision["outcome"] == "DISCARD_BRANCH_AND_WORKTREE":
        if approval.get("actor_type") != "user":
            raise DeliveryBlocked("discard requires a user typed approval")
        if str(approval.get("action", "")).upper() not in DESTRUCTIVE_ACTIONS:
            raise DeliveryBlocked("discard requires an explicit destructive approval action")
    if actor is not None:
        if approval.get("actor_type") != actor.get("actor_type") or approval.get("actor_id") != actor.get("actor_id"):
            raise DeliveryBlocked("approval actor does not match the executing actor")
    try:
        issued = parse_timestamp(approval["issued_at"])
        expires = parse_timestamp(approval["expires_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DeliveryBlocked("approval timestamps are invalid") from exc
    if issued > expires or expires <= datetime.now(timezone.utc):
        raise DeliveryBlocked("delivery approval is expired or has an invalid interval")
    if not require_persisted:
        return
    target_type = approval["target_type"]
    target_id = approval["target_id"]
    path = root / "approvals" / f"{target_type}-{target_id}.json"
    if not path.is_file() or path.is_symlink():
        raise DeliveryBlocked("required delivery approval artifact is missing")
    try:
        persisted = read_object(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DeliveryBlocked("required delivery approval artifact is unreadable") from exc
    if persisted != approval:
        raise DeliveryBlocked("delivery approval does not match the persisted approval artifact")


def _check_verification(decision: dict[str, Any]) -> None:
    verification = decision["verification"]
    if str(verification.get("status", "")).upper() != "PASS":
        raise DeliveryBlocked("fresh final verification is not PASS")
    checks = verification.get("checks")
    if not isinstance(checks, list) or not checks:
        raise DeliveryBlocked("delivery decision requires at least one final verification check")
    for check in checks:
        if check.get("status") != "PASS" or check.get("exit_code") != 0:
            raise DeliveryBlocked(f"final verification did not pass: {check.get('command')}")


def _check_cleanup(decision: dict[str, Any]) -> None:
    outcome = decision["outcome"]
    cleanup = decision["cleanup"]
    requested = cleanup["requested"]
    status = cleanup["status"]
    if outcome in {"PUSH_AND_CREATE_PR", "KEEP_BRANCH_AND_WORKTREE"}:
        if requested or status != "PRESERVED":
            raise DeliveryBlocked(f"{outcome} must preserve the branch and worktree")
    elif outcome == "DISCARD_BRANCH_AND_WORKTREE":
        if not requested or not cleanup["identity_proven"] or status not in {"PENDING", "CLEANED"}:
            raise DeliveryBlocked("discard requires a pending or completed identity-proven cleanup record")
    elif requested and (not cleanup["identity_proven"] or status not in {"PENDING", "CLEANED"}):
        raise DeliveryBlocked("requested merge cleanup is not identity-proven")
    if decision["status"] in BLOCKED_STATUSES and requested:
        raise DeliveryBlocked("blocked delivery decisions cannot request cleanup")


def validate_delivery_decision(
    decision: Any,
    project_root: str | Path | None = None,
    *,
    require_persisted_approval: bool = False,
    actor: dict[str, str] | None = None,
) -> bool:
    """Validate schema, evidence, identity, approval, and cleanup fencing."""

    errors = _schema_errors(decision)
    if errors:
        raise ValueError("delivery decision violates its schema: " + "; ".join(errors))
    if not isinstance(decision, dict) or decision["outcome"] not in OUTCOMES:
        raise ValueError("delivery decision outcome is unsupported")
    if decision["status"] not in RECORDED_STATUSES | BLOCKED_STATUSES:
        raise ValueError("delivery decision status is unsupported")
    _check_cleanup(decision)
    if decision["status"] in BLOCKED_STATUSES:
        if "conflict" not in decision:
            raise DeliveryBlocked("blocked delivery decisions require reconciliation evidence")
    else:
        _check_verification(decision)
        if decision["review"]["task_verdict"] != "PASS" or decision["review"]["batch_verdict"] != "PASS":
            raise DeliveryBlocked("delivery requires PASS task and Batch Reviewer verdicts")
        if decision["review"]["batch_reviewer_performed_merge"]:
            raise DeliveryBlocked("Batch Reviewer is not permitted to perform the merge")
    if project_root is not None:
        root = ensure_runtime_initialized(project_root)
        task = _load_task(root, decision["task_id"])
        _check_task_identity(decision, task)
        _check_persisted_batch_review(root, decision)
        _check_approval(root, decision, require_persisted=require_persisted_approval, actor=actor)
    else:
        _check_approval(Path("."), decision, require_persisted=False, actor=actor)
    return True


def finalize_delivery(
    project_root: str | Path,
    decision: dict[str, Any],
    *,
    actor: dict[str, str] | None = None,
    require_persisted_approval: bool = True,
) -> dict[str, Any]:
    """Persist a validated delivery decision before any merge or cleanup side effect."""

    project = Path(project_root).expanduser().resolve()
    root = ensure_runtime_initialized(project)
    with runtime_lock(project):
        validate_delivery_decision(
            decision,
            project,
            require_persisted_approval=require_persisted_approval,
            actor=actor,
        )
        target = root / "work" / decision["task_id"] / "delivery-decision.json"
        if target.is_file():
            current = read_object(target)
            if current.get("decision_id") == decision.get("decision_id") and current == decision:
                return {**decision, "artifact_path": str(target)}
            if decision["revision"] <= int(current.get("revision", 0)):
                raise DeliveryBlocked("delivery decision revision is stale")
        write_validated(str(project), f"work/{decision['task_id']}/delivery-decision.json", decision, SCHEMA_PATH)
        return {**decision, "artifact_path": str(target)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor")
    parser.add_argument("--actor-type", choices=("user", "primary_agent", "agent", "service"))
    parser.add_argument("--allow-unpersisted-approval", action="store_true")
    args = parser.parse_args()
    try:
        actor = None
        if args.actor is not None or args.actor_type is not None:
            if not args.actor or not args.actor_type:
                raise ValueError("--actor and --actor-type must be supplied together")
            actor = {"actor_id": args.actor, "actor_type": args.actor_type}
        result = finalize_delivery(
            args.project_root,
            read_payload(args.input),
            actor=actor,
            require_persisted_approval=not args.allow_unpersisted_approval,
        )
    except (RuntimeNotInitializedError, RuntimeLockedError) as exc:
        print(f"DELIVERY_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except DeliveryBlocked as exc:
        print(f"DELIVERY_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"DELIVERY_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
