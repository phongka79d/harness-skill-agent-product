"""Authorize and optionally commit one accepted batch."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from authorization import AuthorizationError, authorize, require_persisted_approval
from create_batch_review import artifact_hash as batch_review_artifact_hash
from create_batch_review import derive_verdict, load_batch_contract
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    append_jsonl,
    read_object,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
)
from validate_payload import validate


class CommitRejected(AuthorizationError):
    """Raised when a batch is not eligible for an authorized commit."""


BATCH_REVIEW_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/batch-review.schema.json"


def _target(review: dict[str, Any]) -> dict[str, Any]:
    batch_id = review.get("batch_id")
    revision = review.get("revision")
    artifact_hash = review.get("artifact_hash")
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise CommitRejected("batch review requires batch_id")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise CommitRejected("batch review revision is invalid")
    if not isinstance(artifact_hash, str) or len(artifact_hash) != 64:
        raise CommitRejected("batch review requires a canonical artifact_hash")
    return {
        "target_type": "BATCH",
        "target_id": batch_id,
        "revision": revision,
        "target_hash": artifact_hash,
    }


def validate_commit_authorization(
    batch_review: Any,
    approval: Any,
    *,
    actor: Any,
    now: datetime | None = None,
) -> str:
    if not isinstance(batch_review, dict):
        raise CommitRejected("batch review must be an object")
    if str(batch_review.get("verdict", "")).upper() != "PASS":
        raise CommitRejected("only a PASS batch review can be committed")
    try:
        return authorize("BATCH_COMMIT", _target(batch_review), approval, actor=actor, now=now)
    except AuthorizationError as exc:
        raise CommitRejected(str(exc)) from exc


def validate_batch_review_artifact(batch_review: Any, batch_id: str) -> None:
    """Validate the persisted review schema, identity, and canonical content hash."""

    if not isinstance(batch_review, dict):
        raise CommitRejected("current batch review must be an object")
    if batch_review.get("batch_id") != batch_id:
        raise CommitRejected("current batch review batch_id does not match requested batch_id")
    errors = validate(batch_review, read_object(BATCH_REVIEW_SCHEMA), base_path=BATCH_REVIEW_SCHEMA.parent)
    if errors:
        raise CommitRejected("current batch review is invalid: " + "; ".join(errors))
    if batch_review.get("artifact_hash") != batch_review_artifact_hash(batch_review):
        raise CommitRejected("current batch review artifact_hash does not match content")


def validate_batch_contract_pin(batch_review: Any, current_contract: Any, *, allow_legacy: bool = True) -> None:
    """Require a non-legacy review to pin the currently canonical contract."""

    if allow_legacy and current_contract is None and isinstance(batch_review, dict) and batch_review.get("legacy_migration") is True:
        return
    if not isinstance(current_contract, dict):
        raise CommitRejected("current batch contract is missing")
    revision = batch_review.get("batch_contract_revision") if isinstance(batch_review, dict) else None
    contract_hash = batch_review.get("batch_contract_hash") if isinstance(batch_review, dict) else None
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise CommitRejected("batch review requires a batch contract pin revision")
    if not isinstance(contract_hash, str) or len(contract_hash) != 64:
        raise CommitRejected("batch review requires a batch contract pin hash")
    if revision != current_contract.get("revision") or contract_hash != current_contract.get("contract_hash"):
        raise CommitRejected("batch review batch contract pin does not match the current contract")
    if not isinstance(current_contract.get("review_contract"), dict):
        raise CommitRejected("current batch contract review_contract is missing")
    if not isinstance(batch_review.get("review_contract"), dict) or batch_review["review_contract"] != current_contract["review_contract"]:
        raise CommitRejected("batch review review_contract does not match the current contract")


def validate_batch_review_semantics(batch_review: Any, root: Path, current_contract: Any) -> None:
    """Recompute the current runtime evidence before authorizing a batch commit."""

    if not isinstance(batch_review, dict):
        raise CommitRejected("current batch review must be an object")
    if current_contract is not None and batch_review.get("legacy_migration") is True:
        raise CommitRejected("legacy_migration=true is not allowed when a current batch contract exists")
    try:
        derived_verdict, reasons = derive_verdict(root, batch_review)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CommitRejected(f"current batch review evidence is malformed or missing: {exc}") from exc
    if derived_verdict != "PASS":
        detail = "; ".join(reasons) if reasons else f"derived verdict is {derived_verdict}"
        raise CommitRejected(f"current batch review evidence does not derive PASS: {detail}")


def _safe_paths(project_root: Path, paths: list[str]) -> list[str]:
    if not paths:
        raise CommitRejected("at least one commit path is required")
    normalized: list[str] = []
    for value in paths:
        if not isinstance(value, str) or not value.strip():
            raise CommitRejected("commit paths must be non-empty strings")
        candidate = Path(value)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (project_root / candidate).resolve()
        try:
            relative = resolved.relative_to(project_root).as_posix()
        except ValueError as exc:
            raise CommitRejected("commit path escapes project root") from exc
        if relative == ".agent" or relative.startswith(".agent/"):
            raise CommitRejected("runtime state cannot be committed")
        if relative not in normalized:
            normalized.append(relative)
    return normalized


def _operation_path(root: Path, batch_id: str) -> Path:
    path = root / "work" / batch_id / "operations.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _used_approval(path: Path, approval_id: str) -> bool:
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CommitRejected(f"malformed commit operation ledger: {exc}") from exc
        if isinstance(record, dict) and record.get("approval_id") == approval_id and str(record.get("status", "")).upper() == "COMPLETED":
            return True
    return False


def commit_batch(
    project_root: str | Path,
    batch_id: str,
    approval: dict[str, Any],
    *,
    actor: dict[str, str],
    paths: list[str],
    message: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    root_path = Path(project_root).expanduser().resolve()
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise CommitRejected("batch_id is required")
    try:
        validate_identifier(batch_id, "batch_id")
    except ValueError as exc:
        raise CommitRejected(str(exc)) from exc
    if not isinstance(message, str) or not message.strip():
        raise CommitRejected("commit message is required")
    selected_paths = _safe_paths(root_path, paths)
    with runtime_lock(root_path) as root:
        review = read_object(root / "work" / batch_id / "review.json")
        validate_batch_review_artifact(review, batch_id)
        try:
            current_contract = load_batch_contract(root, batch_id)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CommitRejected(f"current batch contract is invalid: {exc}") from exc
        validate_batch_contract_pin(review, current_contract, allow_legacy=current_contract is None)
        validate_batch_review_semantics(review, root, current_contract)
        require_persisted_approval(root, approval, target_type="BATCH", target_id=batch_id)
        approval_id = validate_commit_authorization(review, approval, actor=actor)
        operation_path = _operation_path(root, batch_id)
        if _used_approval(operation_path, approval_id):
            raise CommitRejected("approval has already been consumed")
        operation_id = f"OP-{batch_id}-COMMIT-{review['revision']}"
        started = {
            "operation_id": operation_id,
            "task_id": batch_id,
            "type": "COMMIT",
            "status": "STARTED",
            "command": "git commit --only",
            "approval_id": approval_id,
            "paths": selected_paths,
            "recorded_at": utc_now(),
            "revision": 1,
            "actor": actor["actor_id"],
        }
        append_jsonl(operation_path, started)
        result: dict[str, Any] = {
            "operation_id": operation_id,
            "approval_id": approval_id,
            "batch_id": batch_id,
            "paths": selected_paths,
            "dry_run": dry_run,
        }
        if dry_run:
            result["status"] = "AUTHORIZED"
            append_jsonl(operation_path, {**started, "status": "COMPLETED", "result_summary": "commit authorization validated", "revision": 2})
            return result
        try:
            subprocess.run(["git", "add", "--", *selected_paths], cwd=root_path, check=True, capture_output=True, text=True)
            completed = subprocess.run(
                ["git", "commit", "--only", "-m", message, "--", *selected_paths],
                cwd=root_path,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            append_jsonl(operation_path, {**started, "status": "FAILED", "result_summary": (exc.stderr or exc.stdout or str(exc)).strip(), "revision": 2})
            raise CommitRejected("git commit failed") from exc
        result["status"] = "COMMITTED"
        result["commit_output"] = (completed.stdout or "").strip()
        append_jsonl(operation_path, {**started, "status": "COMPLETED", "result_summary": result["commit_output"], "revision": 2})
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--actor-type", required=True, choices=("user", "primary_agent", "agent", "service"))
    parser.add_argument("--message", required=True)
    parser.add_argument("--path", action="append", required=True, dest="paths")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = commit_batch(
            args.project_root,
            args.batch_id,
            read_payload(args.approval),
            actor={"actor_type": args.actor_type, "actor_id": args.actor},
            paths=args.paths,
            message=args.message,
            dry_run=args.dry_run,
        )
    except (RuntimeNotInitializedError, RuntimeLockedError) as exc:
        print(f"COMMIT_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (CommitRejected, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"COMMIT_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
