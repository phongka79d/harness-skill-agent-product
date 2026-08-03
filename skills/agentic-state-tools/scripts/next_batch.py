"""Authorize the transition from one accepted batch to the next batch."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from authorization import AuthorizationError, authorize, require_persisted_approval
from commit_batch import CommitRejected, _target
from runtime_utils import RuntimeLockedError, RuntimeNotInitializedError, read_object, read_payload, runtime_lock, utc_now, validate_identifier, write_json_atomic


def validate_next_batch_authorization(
    batch_review: Any,
    approval: Any,
    *,
    actor: Any,
    now: datetime | None = None,
) -> str:
    if not isinstance(batch_review, dict) or str(batch_review.get("verdict", "")).upper() != "PASS":
        raise CommitRejected("next batch requires a PASS batch review")
    try:
        return authorize("NEXT_BATCH", _target(batch_review), approval, actor=actor, now=now)
    except AuthorizationError as exc:
        raise CommitRejected(str(exc)) from exc


def start_next_batch(
    project_root: str | Path,
    current_batch_id: str,
    next_batch_id: str,
    approval: dict[str, Any],
    *,
    actor: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(next_batch_id, str) or not next_batch_id.strip():
        raise CommitRejected("next_batch_id is required")
    try:
        validate_identifier(current_batch_id, "current_batch_id")
        validate_identifier(next_batch_id, "next_batch_id")
    except ValueError as exc:
        raise CommitRejected(str(exc)) from exc
    with runtime_lock(project_root) as root:
        review = read_object(root / "work" / current_batch_id / "review.json")
        require_persisted_approval(root, approval, target_type="BATCH", target_id=current_batch_id)
        approval_id = validate_next_batch_authorization(review, approval, actor=actor)
        marker_path = root / "runtime" / "next-batch.json"
        if marker_path.is_file():
            existing = read_object(marker_path)
            if existing.get("approval_id") == approval_id and existing.get("next_batch_id") == next_batch_id:
                return existing
            raise CommitRejected("a different next-batch authorization is already recorded")
        marker = {
            "schema_version": 1,
            "current_batch_id": current_batch_id,
            "next_batch_id": next_batch_id,
            "approval_id": approval_id,
            "created_at": utc_now(),
        }
        write_json_atomic(marker_path, marker)
        return marker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--current-batch-id", required=True)
    parser.add_argument("--next-batch-id", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--actor-type", required=True, choices=("user", "primary_agent", "agent", "service"))
    args = parser.parse_args()
    try:
        result = start_next_batch(
            args.project_root,
            args.current_batch_id,
            args.next_batch_id,
            read_payload(args.approval),
            actor={"actor_type": args.actor_type, "actor_id": args.actor},
        )
    except (RuntimeNotInitializedError, RuntimeLockedError) as exc:
        print(f"NEXT_BATCH_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (CommitRejected, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"NEXT_BATCH_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
