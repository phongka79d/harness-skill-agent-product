from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "agentic-state-tools"
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from finalize_delivery import DeliveryBlocked, finalize_delivery, validate_delivery_decision  # noqa: E402


def init_runtime(project: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "init_runtime.py"), "--project-root", str(project)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)


def decision_fixture() -> dict[str, object]:
    approval = {
        "approval_id": "APR-WORKTREE-T-DELIVERY",
        "target_type": "WORKTREE",
        "target_id": "T-DELIVERY",
        "decision": "APPROVED",
        "approver": "user-1",
        "actor_type": "user",
        "actor_id": "user-1",
        "action": "DELIVERY_DECISION",
        "target_revision": 1,
        "target_hash": "d" * 64,
        "policy_version": "1",
        "issued_at": "2026-08-05T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "evidence": "final delivery approval",
        "created_at": "2026-08-05T00:00:00Z",
        "revision": 1,
    }
    return {
        "schema_version": 1,
        "decision_id": "DELIVERY-T-DELIVERY-1",
        "task_id": "T-DELIVERY",
        "batch_id": "B-DELIVERY",
        "plan_revision": 1,
        "task_revision": 1,
        "run_id": "RUN-DELIVERY",
        "attempt_id": "ATTEMPT-DELIVERY",
        "dispatch_id": "DISPATCH-DELIVERY",
        "outcome": "KEEP_BRANCH_AND_WORKTREE",
        "branch_name": "async/t-delivery/r1",
        "worktree_path": "C:/worktrees/t-delivery",
        "base_commit": "a" * 40,
        "write_scope_hash": "b" * 64,
        "input_artifact_hashes": {"task": "c" * 64},
        "output_artifact_hashes": {"delivery_decision": "d" * 64},
        "verification": {
            "status": "PASS",
            "workspace_hash": "e" * 64,
            "verified_at": "2026-08-05T00:00:00Z",
            "checks": [{"evidence_id": "E-FINAL", "command": "python -m unittest", "exit_code": 0, "status": "PASS"}],
        },
        "review": {"task_verdict": "PASS", "batch_verdict": "PASS", "batch_reviewer_performed_merge": False},
        "approval": approval,
        "cleanup": {
            "requested": False,
            "status": "PRESERVED",
            "identity_proven": True,
            "evidence_id": "E-PRESERVED",
            "recorded_at": "2026-08-05T00:00:00Z",
        },
        "status": "RECORDED",
        "created_at": "2026-08-05T00:00:00Z",
        "revision": 1,
    }


class DeliveryFinalizerTests(unittest.TestCase):
    def test_finalizer_persists_approved_decision_before_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            init_runtime(project)
            task_dir = project / ".agent/work/T-DELIVERY"
            task_dir.mkdir(parents=True)
            task = {
                "task_id": "T-DELIVERY",
                "batch_id": "B-DELIVERY",
                "plan_revision": 1,
                "revision": 1,
                "status": "ACCEPTED",
                "run_id": "RUN-DELIVERY",
                "attempt_id": "ATTEMPT-DELIVERY",
                "dispatch_id": "DISPATCH-DELIVERY",
                "branch_name": "async/t-delivery/r1",
                "worktree_path": "C:/worktrees/t-delivery",
                "base_commit": "a" * 40,
                "review_verdict": "PASS",
            }
            (task_dir / "task-state.json").write_text(json.dumps(task), encoding="utf-8")
            (project / ".agent/work/B-DELIVERY").mkdir(parents=True)
            (project / ".agent/work/B-DELIVERY/review.json").write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")
            decision = decision_fixture()
            approval_path = project / ".agent/approvals/WORKTREE-T-DELIVERY.json"
            approval_path.parent.mkdir(parents=True)
            approval_path.write_text(json.dumps(decision["approval"]), encoding="utf-8")

            result = finalize_delivery(project, decision, actor={"actor_type": "user", "actor_id": "user-1"})

            self.assertEqual(result["status"], "RECORDED")
            self.assertTrue((task_dir / "delivery-decision.json").is_file())
            self.assertEqual(json.loads((task_dir / "delivery-decision.json").read_text())["cleanup"]["status"], "PRESERVED")

    def test_discard_requires_user_destructive_approval_and_pending_cleanup(self) -> None:
        decision = decision_fixture()
        decision["outcome"] = "DISCARD_BRANCH_AND_WORKTREE"
        decision["cleanup"] = {
            "requested": True,
            "status": "PENDING",
            "identity_proven": True,
            "evidence_id": "E-DISCARD",
            "recorded_at": "2026-08-05T00:00:00Z",
        }
        decision["approval"] = {**decision["approval"], "actor_type": "primary_agent", "action": "DESTRUCTIVE_OPERATION"}
        with self.assertRaises(DeliveryBlocked):
            validate_delivery_decision(decision)

    def test_conflict_is_reconciliation_and_never_cleanup(self) -> None:
        decision = decision_fixture()
        decision["status"] = "NEEDS_RECONCILIATION"
        decision["conflict"] = {"classification": "CONFLICTED", "details": "target and source changed", "evidence_id": "E-CONFLICT"}
        decision["cleanup"] = {
            "requested": False,
            "status": "PRESERVED",
            "identity_proven": True,
            "evidence_id": "E-PRESERVED",
            "recorded_at": "2026-08-05T00:00:00Z",
        }
        self.assertTrue(validate_delivery_decision(decision))

    def test_stale_revision_cannot_replace_a_recorded_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            init_runtime(project)
            task_dir = project / ".agent/work/T-DELIVERY"
            task_dir.mkdir(parents=True)
            task_dir.joinpath("task-state.json").write_text(
                json.dumps(
                    {
                        "task_id": "T-DELIVERY",
                        "batch_id": "B-DELIVERY",
                        "plan_revision": 1,
                        "revision": 1,
                        "status": "ACCEPTED",
                        "run_id": "RUN-DELIVERY",
                        "attempt_id": "ATTEMPT-DELIVERY",
                        "dispatch_id": "DISPATCH-DELIVERY",
                        "branch_name": "async/t-delivery/r1",
                        "worktree_path": "C:/worktrees/t-delivery",
                        "base_commit": "a" * 40,
                        "review_verdict": "PASS",
                    }
                ),
                encoding="utf-8",
            )
            (project / ".agent/work/B-DELIVERY").mkdir(parents=True)
            (project / ".agent/work/B-DELIVERY/review.json").write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")
            decision = decision_fixture()
            approval_path = project / ".agent/approvals/WORKTREE-T-DELIVERY.json"
            approval_path.parent.mkdir(parents=True)
            approval_path.write_text(json.dumps(decision["approval"]), encoding="utf-8")
            finalize_delivery(project, decision)
            stale = copy.deepcopy(decision)
            stale["outcome"] = "MERGE_LOCAL"
            with self.assertRaises(DeliveryBlocked):
                finalize_delivery(project, stale)


if __name__ == "__main__":
    unittest.main()
