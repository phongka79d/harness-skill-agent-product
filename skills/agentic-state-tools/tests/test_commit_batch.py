from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    from commit_batch import CommitRejected, validate_commit_authorization  # noqa: E402
except ModuleNotFoundError:
    CommitRejected = None
    validate_commit_authorization = None

try:
    from next_batch import validate_next_batch_authorization  # noqa: E402
except ModuleNotFoundError:
    validate_next_batch_authorization = None


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def review(verdict: str = "PASS") -> dict[str, object]:
    return {
        "batch_id": "B-1",
        "revision": 4,
        "artifact_hash": "b" * 64,
        "verdict": verdict,
        "task_reviews": ["REV-T-1"],
    }


def approval(actor_type: str = "user", actor_id: str = "alice") -> dict[str, object]:
    return {
        "approval_id": "APR-B-1-COMMIT",
        "target_type": "BATCH",
        "target_id": "B-1",
        "decision": "APPROVED",
        "approver": actor_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": "BATCH_COMMIT",
        "target_revision": 4,
        "target_hash": "b" * 64,
        "policy_version": "1",
        "expires_at": "2026-08-04T12:00:00Z",
        "evidence": "batch review and integration checks passed",
    }


class CommitBatchTests(unittest.TestCase):
    def require_commit_api(self):
        if not callable(validate_commit_authorization) or not isinstance(CommitRejected, type):
            self.fail("commit_batch authorization API is not implemented")
        return validate_commit_authorization, CommitRejected

    def require_next_api(self):
        if not callable(validate_next_batch_authorization) or not isinstance(CommitRejected, type):
            self.fail("next_batch authorization API is not implemented")
        return validate_next_batch_authorization, CommitRejected

    def test_commit_requires_passing_batch_and_user_approval(self) -> None:
        validator, error = self.require_commit_api()
        with self.assertRaises(error):
            validator(
                review(),
                approval(actor_type="primary_agent", actor_id="primary-agent"),
                actor={"actor_type": "primary_agent", "actor_id": "primary-agent"},
                now=NOW,
            )

    def test_commit_rejects_non_passing_batch_even_with_valid_approval(self) -> None:
        validator, error = self.require_commit_api()
        with self.assertRaises(error):
            validator(
                review("REPAIR_REQUIRED"),
                approval(),
                actor={"actor_type": "user", "actor_id": "alice"},
                now=NOW,
            )

    def test_commit_returns_consumed_approval_id(self) -> None:
        validator, _ = self.require_commit_api()
        approval_id = validator(
            review(),
            approval(),
            actor={"actor_type": "user", "actor_id": "alice"},
            now=NOW,
        )
        self.assertEqual(approval_id, "APR-B-1-COMMIT")

    def test_next_batch_requires_user_approval_for_the_passing_batch(self) -> None:
        validator, error = self.require_next_api()
        with self.assertRaises(error):
            validator(
                review(),
                {**approval(), "action": "NEXT_BATCH", "actor_type": "primary_agent", "actor_id": "primary-agent"},
                actor={"actor_type": "primary_agent", "actor_id": "primary-agent"},
                now=NOW,
            )
        approval_id = validator(
            review(),
            {**approval(), "approval_id": "APR-B-1-NEXT", "action": "NEXT_BATCH"},
            actor={"actor_type": "user", "actor_id": "alice"},
            now=NOW,
        )
        self.assertEqual(approval_id, "APR-B-1-NEXT")


if __name__ == "__main__":
    unittest.main()
