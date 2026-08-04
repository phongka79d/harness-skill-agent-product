from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / "agentic-state-tools"
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
sys.path.insert(0, str(SCRIPTS))

import inspect_recovery  # noqa: E402

recovery_policy = getattr(inspect_recovery, "recovery_policy", None)
validate_checkpoint_binding = getattr(inspect_recovery, "validate_checkpoint_binding", None)
validate_lease_binding = getattr(inspect_recovery, "validate_lease_binding", None)

from runtime_utils import apply_event, empty_state, validate_event_preconditions  # noqa: E402


class RecoveryPolicyTests(unittest.TestCase):
    def test_every_canonical_state_has_explicit_recovery_policy(self) -> None:
        if not callable(recovery_policy):
            self.fail("inspect_recovery.recovery_policy is not implemented")
        state_machine = json.loads((SCHEMAS / "state-machine.json").read_text(encoding="utf-8"))
        for status in state_machine["statuses"]:
            policy = recovery_policy(status)
            self.assertIsInstance(policy, dict, status)
            for field in ("resume", "requires_lease", "inspect_git", "rollback", "terminal"):
                self.assertIn(field, policy, status)

    def test_unknown_state_is_unsupported_and_fail_closed(self) -> None:
        if not callable(recovery_policy):
            self.fail("inspect_recovery.recovery_policy is not implemented")
        policy = recovery_policy("NOT_A_CANONICAL_STATE")
        self.assertEqual(policy["resume"], "UNSAFE_TO_RESUME")
        self.assertTrue(policy["unsupported"])

    def test_event_replay_rejects_acceptance_without_prior_task_transition(self) -> None:
        with self.assertRaises(ValueError):
            apply_event(
                empty_state(),
                {
                    "event_id": "EVT-000001",
                    "timestamp": "2026-08-03T12:00:00Z",
                    "type": "TASK_ACCEPTED",
                    "actor": "task-reviewer",
                    "task_id": "T-1",
                    "data": {"review_id": "REV-T-1"},
                },
            )

    def test_checkpoint_binding_rejects_revision_attempt_and_input_hash_mismatch(self) -> None:
        if not callable(validate_checkpoint_binding):
            self.fail("inspect_recovery.validate_checkpoint_binding is not implemented")
        errors = validate_checkpoint_binding(
            {"task_id": "T-1", "revision": 4, "attempt_id": "ATTEMPT-4", "input_artifact_hashes": {"plan": "a" * 64}},
            {"task_id": "T-1", "task_revision": 3, "attempt_id": "ATTEMPT-3", "input_artifact_hashes": {"plan": "b" * 64}},
        )
        self.assertEqual(len(errors), 3)

    def test_checkpoint_schema_declares_resume_identity_fields(self) -> None:
        schema = json.loads((SCHEMAS / "checkpoint.schema.json").read_text(encoding="utf-8"))
        for field in ("task_revision", "attempt_id", "input_artifact_hashes"):
            self.assertIn(field, schema["properties"])

    def test_terminal_operation_conflicting_evidence_is_not_idempotent(self) -> None:
        scripts = SKILL_ROOT / "scripts"
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            run = lambda payload: subprocess.run(
                [sys.executable, str(scripts / "record_operation.py"), "--project-root", str(project), "--input", str(payload)],
                capture_output=True,
                text=True,
                check=False,
            )
            initialized = subprocess.run(
                [sys.executable, str(scripts / "init_runtime.py"), "--project-root", str(project)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            start = project / "start.json"
            start.write_text(json.dumps({"operation_id": "OP-T-1-1", "task_id": "T-1", "run_id": "RUN-1", "type": "OTHER", "status": "STARTED", "command": "run"}), encoding="utf-8")
            self.assertEqual(run(start).returncode, 0)
            complete = project / "complete.json"
            complete.write_text(json.dumps({"operation_id": "OP-T-1-1", "task_id": "T-1", "run_id": "RUN-1", "type": "OTHER", "status": "COMPLETED", "command": "run", "result_checksum": "sha256:first"}), encoding="utf-8")
            self.assertEqual(run(complete).returncode, 0)
            complete.write_text(json.dumps({"operation_id": "OP-T-1-1", "task_id": "T-1", "run_id": "RUN-1", "type": "OTHER", "status": "COMPLETED", "command": "run", "result_checksum": "sha256:second"}), encoding="utf-8")
            conflicting = run(complete)
            self.assertNotEqual(conflicting.returncode, 0)

    def test_runtime_reconciliation_detects_task_state_snapshot_mismatch(self) -> None:
        if not callable(getattr(inspect_recovery, "reconcile_runtime_artifacts", None)):
            self.fail("inspect_recovery.reconcile_runtime_artifacts is not implemented")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".agent"
            (root / "runtime").mkdir(parents=True)
            (root / "work/T-1").mkdir(parents=True)
            (root / "runtime/state.json").write_text(json.dumps({"task_statuses": {"T-1": "READY"}}), encoding="utf-8")
            (root / "runtime/queue.json").write_text(json.dumps({"tasks": [], "task_states": [], "dispatches": [], "locks": []}), encoding="utf-8")
            (root / "runtime/graph.json").write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
            (root / "work/T-1/task-state.json").write_text(json.dumps({"task_id": "T-1", "status": "RUNNING"}), encoding="utf-8")
            reasons = inspect_recovery.reconcile_runtime_artifacts(root, "T-1", "RUNNING")
            self.assertTrue(any("state snapshot" in reason for reason in reasons))

    def test_terminal_recovery_detects_a_leftover_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".agent"
            task_dir = root / "work" / "T-1"
            task_dir.mkdir(parents=True)
            (task_dir / "task-state.json").write_text(json.dumps({"task_id": "T-1", "status": "ACCEPTED"}), encoding="utf-8")
            (task_dir / "lease.json").write_text(json.dumps({"task_id": "T-1", "expires_at": "2099-01-01T00:00:00Z"}), encoding="utf-8")
            result = inspect_recovery.inspect_task(root, "T-1")
            self.assertEqual(result["classification"], "NEEDS_RECONCILIATION")
            self.assertTrue(any("LEASE" in reason for reason in result["reasons"]), result)

    def test_dispatched_queue_recovery_requires_a_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".agent"
            task_dir = root / "work" / "T-1"
            task_dir.mkdir(parents=True)
            (task_dir / "task-state.json").write_text(json.dumps({"task_id": "T-1", "status": "QUEUED_SYNC", "revision": 2}), encoding="utf-8")
            result = inspect_recovery.inspect_task(root, "T-1")
            self.assertEqual(result["classification"], "NEEDS_RECONCILIATION")
            self.assertTrue(any("lease" in reason.lower() for reason in result["reasons"]), result)

    def test_lease_binding_rejects_stale_run_and_attempt_identity(self) -> None:
        if not callable(validate_lease_binding):
            self.fail("inspect_recovery.validate_lease_binding is not implemented")
        errors = validate_lease_binding(
            {"task_id": "T-1", "revision": 4, "run_id": "RUN-4", "attempt_id": "ATTEMPT-4"},
            {"task_id": "T-1", "task_revision": 3, "run_id": "RUN-3", "attempt_id": "ATTEMPT-3", "owner_identity": ""},
        )
        self.assertGreaterEqual(len(errors), 3)

    def test_review_events_require_matching_persisted_review_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".agent"
            (root / "work/T-1").mkdir(parents=True)
            with self.assertRaises(ValueError):
                validate_event_preconditions(
                    root,
                    {
                        "type": "REVIEW_CREATED",
                        "task_id": "T-1",
                        "data": {"review_id": "REV-T-1"},
                    },
                )


if __name__ == "__main__":
    unittest.main()
