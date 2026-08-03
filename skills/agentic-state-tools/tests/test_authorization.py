from __future__ import annotations

import sys
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import authorization  # noqa: E402


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
PYTHON = sys.executable
SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"


def target() -> dict[str, object]:
    return {
        "target_type": "BATCH",
        "target_id": "B-1",
        "revision": 3,
        "target_hash": "a" * 64,
    }


def approval(*, actor_type: str, actor_id: str) -> dict[str, object]:
    return {
        "approval_id": "APR-B-1-3",
        "target_type": "BATCH",
        "target_id": "B-1",
        "decision": "APPROVED",
        "approver": actor_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": "BATCH_COMMIT",
        "target_revision": 3,
        "target_hash": "a" * 64,
        "policy_version": "1",
        "expires_at": "2026-08-04T12:00:00Z",
        "evidence": "batch review passed",
    }


class AuthorizationTests(unittest.TestCase):
    def require_authorize(self):
        candidate = getattr(authorization, "authorize", None)
        if not callable(candidate):
            self.fail("authorization.authorize is not implemented")
        return candidate

    def require_error(self):
        candidate = getattr(authorization, "AuthorizationError", None)
        if not isinstance(candidate, type):
            self.fail("authorization.AuthorizationError is not implemented")
        return candidate

    def test_batch_commit_requires_user_approval(self) -> None:
        with self.assertRaises(self.require_error()):
            self.require_authorize()(
                "BATCH_COMMIT",
                target(),
                approval(actor_type="primary_agent", actor_id="primary-agent"),
                actor={"actor_type": "primary_agent", "actor_id": "primary-agent"},
                now=NOW,
            )

    def test_valid_user_approval_is_bound_to_actor_and_target(self) -> None:
        result = self.require_authorize()(
            "BATCH_COMMIT",
            target(),
            approval(actor_type="user", actor_id="alice"),
            actor={"actor_type": "user", "actor_id": "alice"},
            now=NOW,
        )
        self.assertEqual(result, "APR-B-1-3")

    def test_string_actor_is_not_an_authenticated_identity(self) -> None:
        with self.assertRaises(self.require_error()):
            self.require_authorize()(
                "BATCH_COMMIT",
                target(),
                approval(actor_type="user", actor_id="alice"),
                actor="alice",
                now=NOW,
            )

    def test_protected_action_requires_the_exact_persisted_approval_artifact(self) -> None:
        helper = getattr(authorization, "require_persisted_approval", None)
        self.assertTrue(callable(helper))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "approvals").mkdir()
            value = approval(actor_type="user", actor_id="alice")
            (root / "approvals/BATCH-B-1.json").write_text(json.dumps(value), encoding="utf-8")
            helper(root, value, target_type="BATCH", target_id="B-1")
            with self.assertRaises(authorization.AuthorizationError):
                helper(root, {**value, "evidence": "altered"}, target_type="BATCH", target_id="B-1")

    def test_persisted_approval_target_cannot_escape_the_approval_directory(self) -> None:
        helper = getattr(authorization, "require_persisted_approval", None)
        self.assertTrue(callable(helper))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "approvals").mkdir()
            value = approval(actor_type="user", actor_id="alice")
            (root / "BATCH-B-1.json").write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(authorization.AuthorizationError):
                helper(root, value, target_type="../BATCH", target_id="B-1")

    def test_record_approval_rejects_actor_type_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            initialized = subprocess.run(
                [PYTHON, str(SCRIPT_DIR / "init_runtime.py"), "--project-root", str(project)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            input_path = project / "approval.json"
            input_path.write_text(
                json.dumps({
                    "target_type": "BATCH",
                    "target_id": "B-1",
                    "decision": "APPROVED",
                    "approver": "primary-agent",
                    "actor_type": "user",
                    "actor_id": "primary-agent",
                    "action": "BATCH_COMMIT",
                    "target_revision": 1,
                    "target_hash": "a" * 64,
                    "evidence": "forged actor type",
                }),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    PYTHON,
                    str(SCRIPT_DIR / "record_approval.py"),
                    "--project-root",
                    str(project),
                    "--input",
                    str(input_path),
                    "--actor",
                    "primary-agent",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("actor_type", result.stderr)


if __name__ == "__main__":
    unittest.main()
