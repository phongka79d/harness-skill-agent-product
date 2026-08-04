"""Validate approval records at the side-effect boundary."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import sys
from pathlib import Path
from typing import Any

from runtime_utils import parse_timestamp


CONFIG_SKILL = Path(__file__).resolve().parents[2] / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))
from load_config import load_config  # noqa: E402


POLICY_VERSION = "1"
ACTOR_TYPES = {"user", "primary_agent", "agent", "service"}

# These actions are deliberately stricter than ordinary task execution. The
# caller must supply a typed identity and an approval bound to the same target.
REQUIRED_ACTOR_TYPES = {
    "MASTER_PLAN": "primary_agent",
    "PLAN_APPROVE": "primary_agent",
    "MASTER_PLAN_APPROVE": "primary_agent",
    "SUB_PLAN_APPROVE": "primary_agent",
    "BATCH_APPROVE": "primary_agent",
    "ARCHITECTURE_CHANGE": "user",
    "SCHEMA_MIGRATION": "user",
    "DESTRUCTIVE_OPERATION": "user",
    "PRODUCTION_DEPLOYMENT": "user",
    "BATCH_COMMIT": "user",
    "WORKTREE_MERGE": "user",
    "MERGE_WORKTREE": "user",
    "NEXT_BATCH": "user",
    "ROLLBACK": "primary_agent",
}
ACTION_POLICY_KEYS = {
    "MASTER_PLAN": "plan_approval",
    "PLAN_APPROVE": "plan_approval",
    "MASTER_PLAN_APPROVE": "plan_approval",
    "SUB_PLAN_APPROVE": "plan_approval",
    "BATCH_APPROVE": "batch_approval",
    "ARCHITECTURE_CHANGE": "architecture_change",
    "SCHEMA_MIGRATION": "schema_migration",
    "DESTRUCTIVE_OPERATION": "destructive_operation",
    "PRODUCTION_DEPLOYMENT": "production_deployment",
    "BATCH_COMMIT": "batch_commit",
    "WORKTREE_MERGE": "worktree_merge",
    "MERGE_WORKTREE": "worktree_merge",
    "NEXT_BATCH": "next_batch",
    "ROLLBACK": "rollback",
}
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class AuthorizationError(ValueError):
    """Raised when a protected side effect has insufficient authorization."""


def _validate_target_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise AuthorizationError(f"authorization {field} must be a safe identifier")
    return value


def _actor_identity(actor: Any) -> tuple[str, str]:
    if not isinstance(actor, dict):
        raise AuthorizationError("executing actor must be an authenticated identity object")
    actor_type = actor.get("actor_type")
    actor_id = actor.get("actor_id")
    if actor_type not in ACTOR_TYPES:
        raise AuthorizationError("executing actor has an unsupported actor_type")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise AuthorizationError("executing actor requires a non-empty actor_id")
    return actor_type, actor_id


def required_actor_type(action: str, approval_matrix: dict[str, Any] | None = None) -> str | None:
    normalized = str(action).upper()
    key = ACTION_POLICY_KEYS.get(normalized)
    matrix = approval_matrix
    if matrix is None:
        try:
            matrix = load_config().get("approval_matrix", {})
        except (OSError, TypeError, ValueError):
            matrix = {}
    configured = matrix.get(key) if isinstance(matrix, dict) and key else None
    if configured == "automatic":
        return None
    if configured in ACTOR_TYPES:
        return configured
    return REQUIRED_ACTOR_TYPES.get(normalized)


def validate_approval(
    approval: Any,
    *,
    action: str,
    target_type: str,
    target_id: str,
    target_revision: int,
    target_hash: str,
    now: datetime | None = None,
    actor_id: str | None = None,
) -> str:
    if not isinstance(approval, dict):
        raise ValueError("approval must be an object")
    if str(approval.get("decision", "")).upper() != "APPROVED":
        raise ValueError("approval decision must be APPROVED")
    if approval.get("target_type") != target_type or approval.get("target_id") != target_id:
        raise ValueError("approval target does not match the protected artifact")
    if approval.get("action") != action:
        raise ValueError("approval action does not match the protected operation")
    if approval.get("policy_version") != POLICY_VERSION:
        raise ValueError("approval policy version is stale")
    if approval.get("target_revision") != target_revision or approval.get("target_hash") != target_hash:
        raise ValueError("approval is bound to a different artifact revision or hash")
    for field in ("actor_type", "actor_id", "expires_at", "approval_id"):
        if not isinstance(approval.get(field), str) or not approval[field].strip():
            raise ValueError(f"approval.{field} is required")
    if actor_id is not None and approval["actor_id"] != actor_id:
        raise ValueError("approval actor identity does not match the executing actor")
    expiry = parse_timestamp(approval["expires_at"])
    current = now or datetime.now(timezone.utc)
    if expiry <= current.astimezone(timezone.utc):
        raise ValueError("approval has expired")
    return approval["approval_id"]


def authorize(
    action: str,
    target: Any,
    approval: Any,
    *,
    actor: Any,
    now: datetime | None = None,
) -> str:
    """Authorize one protected operation against an immutable target snapshot."""

    normalized_action = str(action).upper()
    if not isinstance(target, dict):
        raise AuthorizationError("authorization target must be an object")
    target_type = target.get("target_type")
    target_id = target.get("target_id")
    target_revision = target.get("revision")
    target_hash = target.get("target_hash")
    _validate_target_identifier(target_type, "target_type")
    _validate_target_identifier(target_id, "target_id")
    if isinstance(target_revision, bool) or not isinstance(target_revision, int) or target_revision < 1:
        raise AuthorizationError("authorization target revision is invalid")
    if not isinstance(target_hash, str) or not target_hash.strip():
        raise AuthorizationError("authorization target hash is required")

    actor_type, actor_id = _actor_identity(actor)
    required_type = required_actor_type(normalized_action)
    if required_type is not None and actor_type != required_type:
        raise AuthorizationError(f"{normalized_action} requires actor_type={required_type}")
    if not isinstance(approval, dict) or approval.get("actor_type") != actor_type:
        raise AuthorizationError("approval actor_type does not match the executing actor")
    try:
        return validate_approval(
            approval,
            action=normalized_action,
            target_type=target_type,
            target_id=target_id,
            target_revision=target_revision,
            target_hash=target_hash,
            now=now,
            actor_id=actor_id,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorizationError(str(exc)) from exc


def require_persisted_approval(approval_root: str | Path, approval: Any, *, target_type: str, target_id: str) -> None:
    """Require the exact approval artifact recorded under the runtime root."""

    _validate_target_identifier(target_type, "target_type")
    _validate_target_identifier(target_id, "target_id")
    path = Path(approval_root).resolve() / "approvals" / f"{target_type}-{target_id}.json"
    try:
        persisted = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorizationError("required approval artifact is missing or unreadable") from exc
    if not isinstance(persisted, dict) or persisted != approval:
        raise AuthorizationError("approval input does not match the persisted approval artifact")
