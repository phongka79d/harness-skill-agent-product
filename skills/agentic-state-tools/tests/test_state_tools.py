from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
sys.path.insert(0, str(SCRIPTS))

from create_context import normalize  # noqa: E402
from create_batch_review import derive_verdict  # noqa: E402
from secret_scanner import context_security_errors  # noqa: E402


def run_script(name: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPTS / name), *args]
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    try:
        return subprocess.run(command, text=True, capture_output=True, check=False, timeout=15, env=process_env)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=exc.stdout or "",
            stderr=f"TIMEOUT: {name} exceeded 15 seconds",
        )


class StateToolsTests(unittest.TestCase):
    def write_json(self, path: Path, value: dict) -> Path:
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_init_append_rebuild_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            result = run_script("init_runtime.py", "--project-root", str(project))
            self.assertEqual(result.returncode, 0, result.stderr)
            event_file = project / "event.json"
            event_file.write_text(
                json.dumps({
                    "type": "TASK_STARTED",
                    "actor": "primary-agent",
                    "task_id": "T-001",
                }),
                encoding="utf-8",
            )
            result = run_script("append_event.py", "--project-root", str(project), "--input", str(event_file))
            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads((project / ".agent/runtime/state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["revision"], 1)
            self.assertEqual(state["task_statuses"]["T-001"], "RUNNING")
            result = run_script("validate_state.py", "--project-root", str(project))
            self.assertEqual(result.returncode, 0, result.stderr)
            result = run_script(
                "validate_payload.py",
                "--input", str(project / ".agent/runtime/state.json"),
                "--schema", str(SCHEMAS / "state.schema.json"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_init_creates_documented_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            result = run_script("init_runtime.py", "--project-root", str(project))
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = (
                ".agent/runtime/state.json",
                ".agent/runtime/events.jsonl",
                ".agent/runtime/agents.json",
                ".agent/runtime/queue.json",
                ".agent/runtime/graph.json",
                ".agent/recovery/recovery-state.json",
                ".agent/recovery/stale-runs.json",
                ".agent/recovery/recovery-log.jsonl",
                ".agent/checklist.md",
            )
            for relative in expected:
                self.assertTrue((project / relative).is_file(), relative)
            self.assertFalse((project / ".agent/config.yaml").exists())

    def test_init_refuses_existing_empty_agent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".agent").mkdir()
            result = run_script("init_runtime.py", "--project-root", str(project))
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_init_rejects_file_project_root_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project-file"
            project.write_text("not a directory", encoding="utf-8")

            result = run_script("init_runtime.py", "--project-root", str(project))
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_fresh_runtime_snapshot_validates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            result = run_script("validate_state.py", "--project-root", str(project))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_snapshot_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            state_path = project / ".agent/runtime/state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["running_tasks"] = ["T-TAMPERED"]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            result = run_script("validate_state.py", "--project-root", str(project))
            self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_non_object_snapshot_is_rejected_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            (project / ".agent/runtime/state.json").write_text("[]\n", encoding="utf-8")

            result = run_script("validate_state.py", "--project-root", str(project))
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_state_validation_does_not_read_during_runtime_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            lock_path = project / ".agent/locks/runtime-state.lock"
            lock_path.write_text(json.dumps({"pid": os.getpid(), "acquired_at": "2026-08-02T00:00:00Z"}), encoding="utf-8")
            result = run_script("validate_state.py", "--project-root", str(project))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("STATE_BUSY", result.stderr)

    def test_dead_runtime_lock_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            child = subprocess.Popen([sys.executable, "-c", "pass"])
            child_pid = child.pid
            child.wait()
            lock_path = project / ".agent/locks/runtime-state.lock"
            lock_path.write_text(json.dumps({"pid": child_pid, "acquired_at": "2000-01-01T00:00:00Z"}), encoding="utf-8")
            event = self.write_json(project / "event.json", {"type": "TASK_STARTED", "actor": "primary-agent", "task_id": "T-001"})
            result = run_script("append_event.py", "--project-root", str(project), "--input", str(event))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_checkpoint_generates_identifier_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            payload = self.write_json(
                project / "checkpoint.json",
                {"task_id": "T-001", "current_step": "inspect", "pending_steps": ["implement"]},
            )
            result = run_script("create_checkpoint.py", "--project-root", str(project), "--input", str(payload))
            self.assertEqual(result.returncode, 0, result.stderr)
            checkpoint = json.loads((project / ".agent/work/T-001/checkpoint.json").read_text(encoding="utf-8"))
            self.assertTrue(checkpoint["checkpoint_id"].startswith("CP-T-001-"))
            journal = (project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8")
            self.assertIn("CHECKPOINT_CREATED", journal)
            stale = self.write_json(
                project / "stale-checkpoint.json",
                {"task_id": "T-001", "current_step": "stale", "pending_steps": [], "expected_revision": 0},
            )
            result = run_script("create_checkpoint.py", "--project-root", str(project), "--input", str(stale))
            self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_handoff_injects_task_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            payload = self.write_json(
                project / "handoff.json",
                {
                    "run_id": "RUN-T-001",
                    "attempt_id": "ATTEMPT-T-001",
                    "from_role": "executor",
                    "to_role": "task-reviewer",
                    "task_revision": 1,
                    "plan_revision": 1,
                    "input_artifact_hashes": {"task": "a" * 64},
                    "output_artifact_hashes": {"handoff": "b" * 64},
                    "evidence": {"summary": "implementation verified"},
                    "status": "COMPLETE",
                    "summary": "implemented",
                    "files_read": [],
                    "files_changed": [],
                    "findings": [],
                    "implementation_details": [],
                    "validation_results": [],
                    "risks": [],
                    "next_steps": [],
                },
            )
            result = run_script("create_handoff.py", "--project-root", str(project), "--task-id", "T-001", "--input", str(payload))
            self.assertEqual(result.returncode, 0, result.stderr)
            handoff = json.loads((project / ".agent/work/T-001/handoff.json").read_text(encoding="utf-8"))
            self.assertEqual(handoff["task_id"], "T-001")
            self.assertIn("handoff_id", handoff)
            self.assertEqual(handoff["revision"], 1)

            incomplete_identity = self.write_json(
                project / "incomplete-identity.json",
                {key: value for key, value in json.loads(payload.read_text(encoding="utf-8")).items() if key != "attempt_id"},
            )
            result = run_script("create_handoff.py", "--project-root", str(project), "--task-id", "T-003", "--input", str(incomplete_identity))
            self.assertNotEqual(result.returncode, 0)

            incomplete = self.write_json(
                project / "incomplete-handoff.json",
                {
                    "status": "COMPLETE",
                    "summary": "missing report fields",
                    "files_read": [],
                    "files_changed": [],
                    "validation_results": [],
                    "next_steps": [],
                },
            )
            result = run_script("create_handoff.py", "--project-root", str(project), "--task-id", "T-002", "--input", str(incomplete))
            self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_recovery_inspection_classifies_safe_completed_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            task = self.write_json(project / "task.json", {"task_id": "T-001", "title": "Example", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(task)).returncode, 0)
            result = run_script("inspect_recovery.py", "--project-root", str(project), "--task-id", "T-001")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"classification": "SAFE_TO_RESUME"', result.stdout)

    def test_lock_scripts_acquire_and_release_named_resource(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            payload = self.write_json(
                project / "lock.json",
                {
                    "kind": "task",
                    "key": "T-001",
                    "task_id": "T-001",
                    "run_id": "RUN-001",
                    "owner": "executor",
                    "lease_seconds": 60,
                },
            )
            result = run_script("acquire_lock.py", "--project-root", str(project), "--input", str(payload))
            self.assertEqual(result.returncode, 0, result.stderr)
            lock_files = list((project / ".agent/locks/tasks").glob("*.json"))
            self.assertEqual(len(lock_files), 1)
            lock = json.loads(lock_files[0].read_text(encoding="utf-8"))
            self.assertEqual(lock["key"], "T-001")

            result = run_script("acquire_lock.py", "--project-root", str(project), "--input", str(payload))
            self.assertNotEqual(result.returncode, 0, result.stderr)
            release = self.write_json(
                project / "release.json",
                {
                    "kind": "task",
                    "key": "T-001",
                    "lock_id": lock["lock_id"],
                    "run_id": "RUN-001",
                    "owner": "executor",
                },
            )
            result = run_script("release_lock.py", "--project-root", str(project), "--input", str(release))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(lock_files[0].exists())
            journal = (project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8")
            self.assertIn("LOCK_ACQUIRED", journal)
            self.assertIn("LOCK_RELEASED", journal)

    def test_malformed_lock_is_rejected_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            payload = self.write_json(
                project / "lock.json",
                {"kind": "task", "key": "T-001", "run_id": "RUN-001", "owner": "executor", "lease_seconds": 60},
            )
            self.assertEqual(run_script("acquire_lock.py", "--project-root", str(project), "--input", str(payload)).returncode, 0)
            lock_file = next((project / ".agent/locks/tasks").glob("*.json"))
            lock_file.write_text("[]", encoding="utf-8")
            release = self.write_json(
                project / "release.json",
                {"kind": "task", "key": "T-001", "lock_id": "LOCK-TASK-INVALID", "run_id": "RUN-001", "owner": "executor"},
            )
            result = run_script("release_lock.py", "--project-root", str(project), "--input", str(release))
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_heartbeat_writes_lease_for_active_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            queued = self.write_json(project / "queued.json", {"task_id": "T-001", "title": "Example", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            running = self.write_json(project / "running.json", {"task_id": "T-001", "title": "Example", "status": "RUNNING", "expected_revision": 1})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(running)).returncode, 0)
            heartbeat = self.write_json(
                project / "heartbeat.json",
                {"task_id": "T-001", "owner": "executor", "run_id": "RUN-001", "lease_seconds": 60},
            )
            result = run_script("record_heartbeat.py", "--project-root", str(project), "--input", str(heartbeat))
            self.assertEqual(result.returncode, 0, result.stderr)
            lease = json.loads((project / ".agent/work/T-001/lease.json").read_text(encoding="utf-8"))
            self.assertEqual(lease["run_id"], "RUN-001")
            self.assertEqual(lease["lease_seconds"], 60)

            other_run = self.write_json(
                project / "other-heartbeat.json",
                {"task_id": "T-001", "owner": "executor", "run_id": "RUN-002", "lease_seconds": 60},
            )
            result = run_script("record_heartbeat.py", "--project-root", str(project), "--input", str(other_run))
            self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_recovery_reconciles_expired_active_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            queued = self.write_json(project / "queued.json", {"task_id": "T-001", "title": "Example", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            running = self.write_json(project / "running.json", {"task_id": "T-001", "title": "Example", "status": "RUNNING", "expected_revision": 1})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(running)).returncode, 0)
            checkpoint = self.write_json(
                project / "checkpoint.json",
                {"task_id": "T-001", "current_step": "resume", "pending_steps": ["verify"], "resume_safe": True},
            )
            self.assertEqual(run_script("create_checkpoint.py", "--project-root", str(project), "--input", str(checkpoint)).returncode, 0)
            heartbeat = self.write_json(
                project / "heartbeat.json",
                {"task_id": "T-001", "owner": "executor", "run_id": "RUN-001", "lease_seconds": 60},
            )
            self.assertEqual(run_script("record_heartbeat.py", "--project-root", str(project), "--input", str(heartbeat)).returncode, 0)
            lease_path = project / ".agent/work/T-001/lease.json"
            lease = json.loads(lease_path.read_text(encoding="utf-8"))
            lease["expires_at"] = "2000-01-01T00:00:00Z"
            lease_path.write_text(json.dumps(lease), encoding="utf-8")

            result = run_script("inspect_recovery.py", "--project-root", str(project), "--task-id", "T-001")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"classification": "NEEDS_RECONCILIATION"', result.stdout)

    def test_recovery_reconciles_incomplete_side_effect_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            queued = self.write_json(project / "queued.json", {"task_id": "T-001", "title": "Example", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            running = self.write_json(project / "running.json", {"task_id": "T-001", "title": "Example", "status": "RUNNING", "expected_revision": 1})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(running)).returncode, 0)
            checkpoint = self.write_json(project / "checkpoint.json", {"task_id": "T-001", "current_step": "resume", "pending_steps": ["verify"], "resume_safe": True})
            self.assertEqual(run_script("create_checkpoint.py", "--project-root", str(project), "--input", str(checkpoint)).returncode, 0)
            heartbeat = self.write_json(project / "heartbeat.json", {"task_id": "T-001", "owner": "executor", "run_id": "RUN-001", "lease_seconds": 60})
            self.assertEqual(run_script("record_heartbeat.py", "--project-root", str(project), "--input", str(heartbeat)).returncode, 0)
            operation = self.write_json(project / "operation.json", {"task_id": "T-001", "run_id": "RUN-001", "type": "OTHER", "status": "STARTED", "command": "external-side-effect"})
            self.assertEqual(run_script("record_operation.py", "--project-root", str(project), "--input", str(operation)).returncode, 0)

            result = run_script("inspect_recovery.py", "--project-root", str(project), "--task-id", "T-001")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"classification": "NEEDS_RECONCILIATION"', result.stdout)

    def test_recovery_rejects_malformed_operation_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            queued = self.write_json(project / "queued.json", {"task_id": "T-001", "title": "Example", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            operation_path = project / ".agent/work/T-001/operations.jsonl"
            operation_path.write_text(json.dumps({"operation_id": "OP-T-001-1", "task_id": "T-001", "status": "STARTED"}) + "\n", encoding="utf-8")

            result = run_script("inspect_recovery.py", "--project-root", str(project), "--task-id", "T-001")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"classification": "UNSAFE_TO_RESUME"', result.stdout)

    def test_recovery_reconciles_unknown_operation_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            queued = self.write_json(project / "queued.json", {"task_id": "T-001", "title": "Example", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            operation = self.write_json(
                project / "operation.json",
                {"task_id": "T-001", "run_id": "RUN-001", "type": "EXTERNAL_RESOURCE", "status": "UNKNOWN", "command": "external-side-effect"},
            )
            self.assertEqual(run_script("record_operation.py", "--project-root", str(project), "--input", str(operation)).returncode, 0)

            result = run_script("inspect_recovery.py", "--project-root", str(project), "--task-id", "T-001")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"classification": "NEEDS_RECONCILIATION"', result.stdout)

    def test_checklist_rejects_non_object_task_state_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            task_dir = project / ".agent/work/T-001"
            task_dir.mkdir(parents=True)
            (task_dir / "task-state.json").write_text("[]\n", encoding="utf-8")

            result = run_script("render_checklist.py", "--project-root", str(project))
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_batch_review_derives_pass_only_from_accepted_task_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            for revision, status in enumerate(("QUEUED", "RUNNING", "COMPLETED")):
                payload = {"task_id": "T-001", "batch_id": "B-001", "title": "Example", "status": status}
                if revision:
                    payload["expected_revision"] = revision
                task_input = self.write_json(project / f"{status.lower()}.json", payload)
                self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(task_input)).returncode, 0)
            task_review = self.write_json(
                project / "task-review.json",
                {
                    "review_id": "REV-T-001",
                    "task_id": "T-001",
                    "legacy_migration": True,
                    "criteria": [{"id": "CORRECTNESS", "score": 4, "weight": 100, "mandatory": True, "evidence": "tests passed"}],
                    "findings": [],
                },
            )
            self.assertEqual(run_script("create_review.py", "--project-root", str(project), "--input", str(task_review)).returncode, 0)
            batch = self.write_json(
                project / "batch-review.json",
                {
                    "batch_id": "B-001",
                    "legacy_migration": True,
                    "task_reviews": ["REV-T-001"],
                    "integration_checks": [{"name": "test-suite", "result": "PASS", "evidence": "all tests passed"}],
                    "findings": [],
                    "verdict": "BLOCKED",
                },
            )
            result = run_script("create_batch_review.py", "--project-root", str(project), "--input", str(batch))
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads((project / ".agent/work/B-001/review.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["verdict"], "PASS")
            self.assertRegex(saved.get("artifact_hash", ""), r"^[0-9a-f]{64}$")

    def test_batch_review_blocks_when_task_review_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            batch = self.write_json(
                project / "batch-review.json",
                {
                    "batch_id": "B-001",
                    "legacy_migration": True,
                    "task_reviews": ["REV-MISSING"],
                    "integration_checks": [{"name": "test-suite", "result": "PASS", "evidence": "not run"}],
                    "findings": [],
                },
            )
            result = run_script("create_batch_review.py", "--project-root", str(project), "--input", str(batch))
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads((project / ".agent/work/B-001/review.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["verdict"], "BLOCKED")

    def test_batch_review_requires_every_task_from_canonical_batch_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            batch_dir = project / ".agent/work/B-COMPLETE"
            batch_dir.mkdir(parents=True)
            (batch_dir / "batch-contract.json").write_text(
                json.dumps({"batch_id": "B-COMPLETE", "tasks": [f"T-{index}" for index in range(1, 6)]}),
                encoding="utf-8",
            )
            review_ids = []
            for index in range(1, 6):
                task_dir = project / ".agent/work" / f"T-{index}"
                task_dir.mkdir(parents=True)
                review_id = f"REV-T-{index}"
                review_ids.append(review_id)
                (task_dir / "review.json").write_text(
                    json.dumps({"review_id": review_id, "task_id": f"T-{index}", "verdict": "PASS"}),
                    encoding="utf-8",
                )
                (task_dir / "task-state.json").write_text(
                    json.dumps({"task_id": f"T-{index}", "status": "ACCEPTED"}),
                    encoding="utf-8",
                )
            batch = self.write_json(
                project / "batch-complete.json",
                {
                    "batch_id": "B-COMPLETE",
                    "legacy_migration": True,
                    "task_reviews": review_ids[:4],
                    "integration_checks": [{"name": "tests", "result": "PASS", "evidence": "all tests passed"}],
                    "findings": [],
                },
            )
            result = run_script("create_batch_review.py", "--project-root", str(project), "--input", str(batch))
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads((batch_dir / "review.json").read_text(encoding="utf-8"))
            self.assertNotEqual(saved["verdict"], "PASS")
            self.assertTrue(any("T-5" in reason for reason in saved["blocking_reasons"]))

    def test_nonlegacy_batch_rejects_a_task_review_with_the_wrong_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".agent"
            task_dir = root / "work" / "T-1"
            batch_dir = root / "work" / "B-1"
            task_dir.mkdir(parents=True)
            batch_dir.mkdir(parents=True)
            task_contract = {
                "project_profile": "personal",
                "profile_hash": "a" * 64,
                "task_type": "backend",
                "risk_flags": {},
                "review_type": "task",
                "rubric_id": "TASK-1",
                "rubric_version": "1",
                "rubric_hash": "b" * 64,
                "review_policy_version": "1",
            }
            review_contract = {**task_contract, "rubric_id": "TASK-2"}
            (batch_dir / "batch-contract.json").write_text(json.dumps({"batch_id": "B-1", "tasks": ["T-1"]}), encoding="utf-8")
            (task_dir / "task-state.json").write_text(json.dumps({"task_id": "T-1", "status": "ACCEPTED", "review_contract": task_contract}), encoding="utf-8")
            (task_dir / "review.json").write_text(json.dumps({"review_id": "REV-T-1", "task_id": "T-1", "verdict": "PASS", "review_contract": review_contract}), encoding="utf-8")
            verdict, reasons = derive_verdict(
                root,
                {
                    "batch_id": "B-1",
                    "task_reviews": ["REV-T-1"],
                    "integration_checks": [
                        {"kind": "integration", "result": "PASS"},
                        {"kind": "regression", "result": "PASS"},
                        {"kind": "scope", "result": "PASS"},
                    ],
                    "findings": [],
                    "scope_valid": True,
                    "legacy_migration": False,
                    "rubric_verdict": "PASS",
                },
            )
            self.assertNotEqual(verdict, "PASS")
            self.assertTrue(any("contract" in reason.lower() for reason in reasons), reasons)

    def test_batch_review_applies_canonical_weighted_rubric_before_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            batch_dir = project / ".agent/work/B-SCORED"
            batch_dir.mkdir(parents=True)
            (batch_dir / "batch-contract.json").write_text(
                json.dumps({"batch_id": "B-SCORED", "tasks": ["T-1"]}),
                encoding="utf-8",
            )
            task_dir = project / ".agent/work/T-1"
            task_dir.mkdir(parents=True)
            (task_dir / "review.json").write_text(
                json.dumps({"review_id": "REV-T-1", "task_id": "T-1", "verdict": "PASS"}),
                encoding="utf-8",
            )
            (task_dir / "task-state.json").write_text(
                json.dumps({"task_id": "T-1", "status": "ACCEPTED"}),
                encoding="utf-8",
            )
            rubric_result = run_script(
                "resolve_rubric.py",
                "--profile", "personal",
                "--task-type", "standard",
                "--review-type", "batch",
                "--risk-flags", "{}",
            )
            self.assertEqual(rubric_result.returncode, 0, rubric_result.stderr)
            rubric = json.loads(rubric_result.stdout)
            (batch_dir / "batch-contract.json").write_text(
                json.dumps({
                    "batch_id": "B-SCORED",
                    "tasks": ["T-1"],
                    "review_contract": {
                        "project_profile": rubric["profile_id"],
                        "profile_hash": rubric["profile_hash"],
                        "task_type": rubric["task_type"],
                        "risk_flags": rubric["risk_flags"],
                        "review_type": rubric["review_type"],
                        "rubric_id": rubric["rubric_id"],
                        "rubric_version": rubric["rubric_version"],
                        "rubric_hash": rubric["rubric_hash"],
                        "review_policy_version": rubric["review_policy_version"],
                    },
                }),
                encoding="utf-8",
            )
            criteria = [
                {
                    "id": criterion_id,
                    "score": 0,
                    "weight": next(item["weight"] for item in rubric["criteria"] if item["id"] == criterion_id),
                    "mandatory": next(item["mandatory"] for item in rubric["criteria"] if item["id"] == criterion_id),
                    "minimum_score": next(item["minimum_score"] for item in rubric["criteria"] if item["id"] == criterion_id),
                    "applicability": "APPLICABLE",
                    "evidence": "verification failed",
                }
                for criterion_id in rubric["resolved_weights"]
            ]
            batch = self.write_json(
                project / "batch-scored.json",
                {
                    "batch_id": "B-SCORED",
                    "task_reviews": ["REV-T-1"],
                    "criteria": criteria,
                    "integration_checks": [{"kind": "integration", "name": "tests", "result": "PASS", "evidence": "tests ran"}, {"kind": "regression", "name": "regression", "result": "PASS", "evidence": "tests ran"}, {"kind": "scope", "name": "scope", "result": "PASS", "evidence": "scope checked"}],
                    "findings": [],
                    "hard_fail_checks": [{"rule": rule, "triggered": False, "evidence": "rule checked"} for rule in rubric["hard_fail_rules"]],
                    "resolved_rubric": rubric,
                },
            )
            result = run_script("create_batch_review.py", "--project-root", str(project), "--input", str(batch))
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads((batch_dir / "review.json").read_text(encoding="utf-8"))
            self.assertNotEqual(saved["verdict"], "PASS")
            self.assertTrue(any("rubric" in reason.lower() for reason in saved["blocking_reasons"]))

    def test_context_script_generates_validated_task_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            context = self.write_json(
                project / "context.json",
                {
                    "task": {"task_id": "T-001", "objective": "Implement the example"},
                    "required_documents": ["docs/agentic/task.md"],
                    "code_context": {"files_to_read": ["src/example.py"], "symbols_to_inspect": [], "existing_patterns": []},
                    "constraints": {"inherited": [], "task_specific": []},
                    "review_history": [],
                    "budget": {"max_files": 20, "max_reference_documents": 8, "max_examples": 3},
                },
            )
            result = run_script("create_context.py", "--project-root", str(project), "--input", str(context))
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads((project / ".agent/work/T-001/context.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["context_id"].startswith("CTX-T-001-"))
            self.assertIn("CONTEXT_CREATED", (project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8"))

    def test_context_script_rejects_budget_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            context = self.write_json(
                project / "context.json",
                {
                    "task": {"task_id": "T-001", "objective": "Implement the example"},
                    "required_documents": ["docs/one.md", "docs/two.md"],
                    "code_context": {"files_to_read": ["src/one.py", "src/two.py"], "symbols_to_inspect": [], "existing_patterns": []},
                    "constraints": {"inherited": [], "task_specific": []},
                    "review_history": [],
                    "budget": {"max_files": 1, "max_reference_documents": 1, "max_examples": 0},
                },
            )
            result = run_script("create_context.py", "--project-root", str(project), "--input", str(context))
            self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_context_builder_rejects_secret_values_and_sensitive_paths_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            context = self.write_json(
                project / "secret-context.json",
                {
                    "task": {"task_id": "T-SECRET", "objective": "inspect repository"},
                    "required_documents": [],
                    "code_context": {
                        "files_to_read": [".env", "src/app.py"],
                        "symbols_to_inspect": [],
                        "existing_patterns": [],
                        "file_contents": {"src/app.py": "Authorization: Bearer token-value"},
                    },
                    "constraints": {"inherited": [], "task_specific": [{"password": "plain-secret"}]},
                    "review_history": [],
                },
            )
            result = run_script("create_context.py", "--project-root", str(project), "--input", str(context))
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertIn("sensitive", result.stderr.lower())
            self.assertFalse((project / ".agent/work/T-SECRET/context.json").exists())

    def test_secret_scanner_rejects_sensitive_key_containers(self) -> None:
        errors = context_security_errors({"api_keys": ["opaque-token"]}, max_bytes=4096)
        self.assertTrue(any("sensitive-key" in error for error in errors), errors)

    def test_context_script_uses_central_budget_when_payload_omits_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            config_value = json.loads(
                (SKILL_ROOT.parent / "agentic-configuration" / "config" / "agentic-config.yaml").read_text(encoding="utf-8")
            )
            config_value["context_budget"].update({"max_files": 1, "max_reference_documents": 1, "max_examples": 0, "max_review_history_items": 1})
            config = self.write_json(project / "agentic-config.json", config_value)
            context = self.write_json(
                project / "context-with-config-budget.json",
                {
                    "task": {"task_id": "T-CONFIG-BUDGET", "objective": "Use configured budget"},
                    "required_documents": ["docs/task.md"],
                    "code_context": {"files_to_read": ["src/example.py"], "symbols_to_inspect": [], "existing_patterns": []},
                    "constraints": {"inherited": [], "task_specific": []},
                    "review_history": [],
                },
            )
            result = run_script(
                "create_context.py",
                "--project-root", str(project),
                "--input", str(context),
                env={"AGENTIC_CONFIG_FILE": str(config)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads((project / ".agent/work/T-CONFIG-BUDGET/context.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["budget"]["max_files"], 1)
            self.assertEqual(saved["budget"]["max_reference_documents"], 1)

    def test_context_normalize_rejects_supplied_invalid_config(self) -> None:
        payload = {
            "task": {"task_id": "T-CONFIG-DIRECT", "objective": "Validate config"},
            "required_documents": [],
            "code_context": {"files_to_read": [], "symbols_to_inspect": [], "existing_patterns": []},
            "constraints": {"inherited": [], "task_specific": []},
            "review_history": [],
        }
        with self.assertRaises(ValueError):
            normalize(payload, config={})

    def test_operation_ledger_is_idempotent_and_blocks_uncertain_retries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            task = self.write_json(project / "task.json", {"task_id": "T-001", "title": "Example", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(task)).returncode, 0)
            started = self.write_json(
                project / "operation-start.json",
                {"task_id": "T-001", "run_id": "RUN-001", "type": "DATABASE_MIGRATION", "status": "STARTED", "command": "migrate"},
            )
            result = run_script("record_operation.py", "--project-root", str(project), "--input", str(started))
            self.assertEqual(result.returncode, 0, result.stderr)
            operation_path = project / ".agent/work/T-001/operations.jsonl"
            records = [json.loads(line) for line in operation_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 1)
            operation_id = records[0]["operation_id"]

            completed = self.write_json(
                project / "operation-complete.json",
                {"operation_id": operation_id, "task_id": "T-001", "run_id": "RUN-001", "type": "DATABASE_MIGRATION", "status": "COMPLETED", "command": "migrate", "result_checksum": "sha256:ok"},
            )
            self.assertEqual(run_script("record_operation.py", "--project-root", str(project), "--input", str(completed)).returncode, 0)
            self.assertEqual(len(operation_path.read_text(encoding="utf-8").splitlines()), 2)

            result = run_script("record_operation.py", "--project-root", str(project), "--input", str(completed))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("IDEMPOTENT", result.stdout)
            self.assertEqual(len(operation_path.read_text(encoding="utf-8").splitlines()), 2)

            retry = self.write_json(
                project / "operation-retry.json",
                {"operation_id": operation_id, "task_id": "T-001", "run_id": "RUN-001", "type": "DATABASE_MIGRATION", "status": "STARTED", "command": "migrate"},
            )
            result = run_script("record_operation.py", "--project-root", str(project), "--input", str(retry))
            self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_operation_writer_rejects_broken_existing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            task = self.write_json(project / "task.json", {"task_id": "T-001", "title": "Example", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(task)).returncode, 0)
            operation_path = project / ".agent/work/T-001/operations.jsonl"
            operation_path.write_text(
                json.dumps(
                    {
                        "operation_id": "OP-T-001-001",
                        "task_id": "T-001",
                        "type": "OTHER",
                        "status": "STARTED",
                        "command": "run",
                        "recorded_at": "2026-08-02T00:00:00Z",
                        "revision": 2,
                        "actor": "executor",
                    }
                ) + "\n",
                encoding="utf-8",
            )
            submitted = self.write_json(
                project / "operation.json",
                {"task_id": "T-001", "run_id": "RUN-001", "type": "OTHER", "status": "STARTED", "command": "new-run"},
            )

            result = run_script("record_operation.py", "--project-root", str(project), "--input", str(submitted))
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(len(operation_path.read_text(encoding="utf-8").splitlines()), 1)

    def test_event_requires_initialized_runtime_and_valid_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            event = self.write_json(
                project / "event.json",
                {"type": "TASK_STARTED", "actor": "primary-agent", "task_id": "T-001"},
            )
            result = run_script("append_event.py", "--project-root", str(project), "--input", str(event))
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertFalse((project / ".agent").exists())

            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            invalid = self.write_json(
                project / "invalid-event.json",
                {"type": "TASK_STARTED", "actor": "primary-agent", "task_id": 123},
            )
            result = run_script("append_event.py", "--project-root", str(project), "--input", str(invalid))
            self.assertNotEqual(result.returncode, 0, result.stderr)

            invalid_id = self.write_json(
                project / "invalid-event-id.json",
                {
                    "event_id": "EVT-12",
                    "type": "TASK_STARTED",
                    "actor": "primary-agent",
                    "task_id": "T-001",
                },
            )
            result = run_script("append_event.py", "--project-root", str(project), "--input", str(invalid_id))
            self.assertNotEqual(result.returncode, 0, result.stderr)

            invalid_type = self.write_json(
                project / "invalid-event-type.json",
                {"type": "task_started", "actor": "primary-agent", "task_id": "T-001"},
            )
            result = run_script("append_event.py", "--project-root", str(project), "--input", str(invalid_type))
            self.assertNotEqual(result.returncode, 0, result.stderr)

            custom = self.write_json(
                project / "custom-event.json",
                {"event_id": "EVT-000100", "type": "TASK_STARTED", "actor": "primary-agent", "task_id": "T-001"},
            )
            self.assertEqual(run_script("append_event.py", "--project-root", str(project), "--input", str(custom)).returncode, 0)
            generated = self.write_json(
                project / "generated-event.json",
                {"type": "TASK_COMPLETED", "actor": "primary-agent", "task_id": "T-001"},
            )
            result = run_script("append_event.py", "--project-root", str(project), "--input", str(generated))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("EVT-000101", result.stdout)

    def test_task_cannot_be_accepted_before_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            queued = self.write_json(project / "queued.json", {"task_id": "T-001", "title": "Example", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            accepted = self.write_json(
                project / "accepted.json",
                {"task_id": "T-001", "title": "Example", "status": "ACCEPTED", "expected_revision": 1},
            )
            result = run_script("update_task_state.py", "--project-root", str(project), "--input", str(accepted))
            self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_direct_acceptance_event_requires_passing_review_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            queued = self.write_json(project / "queued.json", {"task_id": "T-001", "title": "Example", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            event = self.write_json(
                project / "accepted-event.json",
                {"type": "TASK_ACCEPTED", "actor": "task-reviewer", "task_id": "T-001", "data": {"review_id": "REV-MISSING"}},
            )
            result = run_script("append_event.py", "--project-root", str(project), "--input", str(event))
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertIn("accept", result.stderr.lower())
            self.assertEqual(run_script("validate_state.py", "--project-root", str(project)).returncode, 0)

    def test_end_to_end_runtime_workflow_generates_consistent_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)

            context = self.write_json(
                project / "context.json",
                {
                    "task": {"task_id": "T-001", "objective": "Implement the example"},
                    "required_documents": [],
                    "code_context": {"files_to_read": [], "symbols_to_inspect": [], "existing_patterns": []},
                    "constraints": {"inherited": [], "task_specific": []},
                    "review_history": [],
                    "budget": {"max_files": 20, "max_reference_documents": 8, "max_examples": 3},
                },
            )
            self.assertEqual(run_script("create_context.py", "--project-root", str(project), "--input", str(context)).returncode, 0)

            for revision, status in enumerate(("QUEUED", "RUNNING")):
                payload = {"task_id": "T-001", "batch_id": "B-001", "title": "Example", "status": status}
                if revision:
                    payload["expected_revision"] = revision
                task = self.write_json(project / f"{status.lower()}.json", payload)
                self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(task)).returncode, 0)

            lock = self.write_json(
                project / "lock.json",
                {"kind": "file", "key": "src/example.py", "task_id": "T-001", "run_id": "RUN-001", "owner": "executor", "lease_seconds": 120},
            )
            self.assertEqual(run_script("acquire_lock.py", "--project-root", str(project), "--input", str(lock)).returncode, 0)

            heartbeat = self.write_json(
                project / "heartbeat.json",
                {"task_id": "T-001", "owner": "executor", "run_id": "RUN-001", "lease_seconds": 120},
            )
            self.assertEqual(run_script("record_heartbeat.py", "--project-root", str(project), "--input", str(heartbeat)).returncode, 0)
            operation_start = self.write_json(
                project / "operation-start.json",
                {"task_id": "T-001", "run_id": "RUN-001", "type": "OTHER", "status": "STARTED", "command": "python verify.py"},
            )
            self.assertEqual(run_script("record_operation.py", "--project-root", str(project), "--input", str(operation_start)).returncode, 0)
            operation_id = json.loads((project / ".agent/work/T-001/operations.jsonl").read_text(encoding="utf-8").splitlines()[0])["operation_id"]
            operation_complete = self.write_json(
                project / "operation-complete.json",
                {"operation_id": operation_id, "task_id": "T-001", "run_id": "RUN-001", "type": "OTHER", "status": "COMPLETED", "command": "python verify.py", "result_checksum": "sha256:verified"},
            )
            self.assertEqual(run_script("record_operation.py", "--project-root", str(project), "--input", str(operation_complete)).returncode, 0)
            checkpoint = self.write_json(
                project / "checkpoint.json",
                {"task_id": "T-001", "current_step": "verify", "pending_steps": ["review"], "resume_safe": True},
            )
            self.assertEqual(run_script("create_checkpoint.py", "--project-root", str(project), "--input", str(checkpoint)).returncode, 0)

            completed = self.write_json(
                project / "completed.json",
                {"task_id": "T-001", "batch_id": "B-001", "title": "Example", "status": "COMPLETED", "expected_revision": 2},
            )
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(completed)).returncode, 0)

            handoff = self.write_json(
                project / "handoff.json",
                {
                    "run_id": "RUN-T-001",
                    "attempt_id": "ATTEMPT-T-001",
                    "from_role": "executor",
                    "to_role": "task-reviewer",
                    "task_revision": 3,
                    "plan_revision": 1,
                    "input_artifact_hashes": {"task": "a" * 64},
                    "output_artifact_hashes": {"handoff": "b" * 64},
                    "evidence": {"summary": "implementation verified"},
                    "status": "COMPLETE",
                    "summary": "implemented",
                    "files_read": ["src/example.py"],
                    "files_changed": ["src/example.py"],
                    "findings": [],
                    "implementation_details": ["implemented example"],
                    "validation_results": [{"command": "python -m unittest", "result": "PASS", "evidence": "workflow tests pass"}],
                    "risks": [],
                    "next_steps": [],
                },
            )
            self.assertEqual(run_script("create_handoff.py", "--project-root", str(project), "--task-id", "T-001", "--input", str(handoff)).returncode, 0)

            review = self.write_json(
                project / "review.json",
                {
                    "review_id": "REV-T-001",
                    "task_id": "T-001",
                    "legacy_migration": True,
                    "criteria": [{"id": "CORRECTNESS", "score": 4, "weight": 100, "mandatory": True, "evidence": "workflow validation passed"}],
                    "findings": [],
                },
            )
            self.assertEqual(run_script("create_review.py", "--project-root", str(project), "--input", str(review)).returncode, 0)

            self.assertEqual(list((project / ".agent/locks/files").glob("*.json")), [])
            self.assertFalse((project / ".agent/work/T-001/lease.json").exists())

            batch = self.write_json(
                project / "batch.json",
                {
                    "batch_id": "B-001",
                    "legacy_migration": True,
                    "task_reviews": ["REV-T-001"],
                    "integration_checks": [{"name": "workflow", "result": "PASS", "evidence": "all generated artifacts validated"}],
                    "findings": [],
                },
            )
            self.assertEqual(run_script("create_batch_review.py", "--project-root", str(project), "--input", str(batch)).returncode, 0)
            self.assertEqual(run_script("rebuild_state.py", "--project-root", str(project)).returncode, 0)
            self.assertEqual(run_script("inspect_recovery.py", "--project-root", str(project), "--task-id", "T-001").returncode, 0)
            self.assertEqual(run_script("validate_state.py", "--project-root", str(project)).returncode, 0)
            operations = (project / ".agent/work/T-001/operations.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(operations), 2)

            artifacts = (
                ("work/T-001/context.json", "context.schema.json"),
                ("work/T-001/task-state.json", "task-state.schema.json"),
                ("work/T-001/checkpoint.json", "checkpoint.schema.json"),
                ("work/T-001/handoff.json", "handoff.schema.json"),
                ("work/T-001/review.json", "review.schema.json"),
                ("work/B-001/review.json", "batch-review.schema.json"),
            )
            for relative, schema in artifacts:
                result = run_script(
                    "validate_payload.py",
                    "--input", str(project / ".agent" / relative),
                    "--schema", str(SCHEMAS / schema),
                )
                self.assertEqual(result.returncode, 0, f"{relative}: {result.stderr}")
            checklist = (project / ".agent/checklist.md").read_text(encoding="utf-8")
            self.assertIn("- [x] T-001", checklist)
            self.assertFalse((project / ".agent/config.yaml").exists())

    def test_passing_review_accepts_completed_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            for revision, status in enumerate(("QUEUED", "RUNNING", "COMPLETED")):
                payload = {"task_id": "T-001", "title": "Example", "status": status}
                if revision:
                    payload["expected_revision"] = revision
                input_path = self.write_json(project / f"{status.lower()}.json", payload)
                result = run_script("update_task_state.py", "--project-root", str(project), "--input", str(input_path))
                self.assertEqual(result.returncode, 0, result.stderr)
            review = self.write_json(
                project / "review.json",
                {
                    "review_id": "REV-T-001",
                    "task_id": "T-001",
                    "legacy_migration": True,
                    "criteria": [{"id": "CORRECTNESS", "score": 4, "weight": 100, "mandatory": True, "evidence": "targeted test passed"}],
                    "findings": [],
                },
            )
            result = run_script("create_review.py", "--project-root", str(project), "--input", str(review))
            self.assertEqual(result.returncode, 0, result.stderr)
            task_state = json.loads((project / ".agent/work/T-001/task-state.json").read_text(encoding="utf-8"))
            self.assertEqual(task_state["status"], "ACCEPTED")
            checklist = (project / ".agent/checklist.md").read_text(encoding="utf-8")
            self.assertIn("- [x] T-001", checklist)

    def test_insufficient_rubric_context_blocks_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self.write_json(
                Path(directory) / "review.json",
                {
                    "review_id": "REV-T-001",
                    "task_id": "T-001",
                    "criteria": [{"id": "SECURITY", "score": 0, "weight": 10, "applicability": "INSUFFICIENT_CONTEXT"}],
                    "findings": [],
                },
            )
            result = run_script("calculate_rubric_score.py", "--input", str(payload))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"verdict": "BLOCKED"', result.stdout)

    def test_rubric_rejects_major_finding_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self.write_json(
                Path(directory) / "review.json",
                {
                    "review_id": "REV-T-001",
                    "task_id": "T-001",
                    "criteria": [{"id": "CORRECTNESS", "score": 4, "weight": 100, "evidence": "tests passed"}],
                    "findings": [{"severity": "MAJOR", "resolved": False}],
                },
            )
            result = run_script("calculate_rubric_score.py", "--input", str(payload))
            self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_rubric_rejects_non_object_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "review.json"
            payload.write_text("[]\n", encoding="utf-8")

            result = run_script("calculate_rubric_score.py", "--input", str(payload))
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertIn("SCORE_FAILED", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_schema_and_rubric_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            examples = (
                ("event.json", "event.schema.json"),
                ("lock.json", "lock.schema.json"),
                ("heartbeat.json", "lease.schema.json"),
                ("batch-review.json", "batch-review.schema.json"),
                ("context.json", "context.schema.json"),
                ("operation.json", "operation.schema.json"),
            )
            for example_name, schema_name in examples:
                result = run_script(
                    "validate_payload.py",
                    "--input", str(SKILL_ROOT / "examples" / example_name),
                    "--schema", str(SCHEMAS / schema_name),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            result = run_script(
                "calculate_rubric_score.py",
                "--input", str(SKILL_ROOT / "examples/review.json"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"verdict": "PASS"', result.stdout)


if __name__ == "__main__":
    unittest.main()
