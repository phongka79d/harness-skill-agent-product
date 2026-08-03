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


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def init_project(path: Path) -> None:
    result = run_script("init_runtime.py", "--project-root", str(path))
    if result.returncode:
        raise AssertionError(result.stderr)


class RecoveryHardeningTests(unittest.TestCase):
    def test_reconciliation_and_lock_reclaim_schemas_exist(self) -> None:
        self.assertTrue((SCHEMAS / "reconciliation.schema.json").is_file())
        self.assertTrue((SCHEMAS / "lock-reclaim.schema.json").is_file())

    def test_workspace_capture_separates_staged_unstaged_and_untracked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".gitignore").write_text(".agent/\n", encoding="utf-8")
            (project / "staged.py").write_text("value = 1\n", encoding="utf-8")
            (project / "unstaged.py").write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True, text=True)
            (project / "staged.py").write_text("value = 2\n", encoding="utf-8")
            subprocess.run(["git", "add", "staged.py"], cwd=project, check=True)
            (project / "unstaged.py").write_text("value = 2\n", encoding="utf-8")
            (project / "untracked.py").write_text("value = 3\n", encoding="utf-8")
            result = run_script("capture_workspace.py", "--project-root", str(project))
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads(result.stdout)
            self.assertIn("staged.py", snapshot["staged_paths"])
            self.assertIn("unstaged.py", snapshot["unstaged_paths"])
            self.assertIn("untracked.py", snapshot["untracked_paths"])
            self.assertTrue(snapshot["base_commit"])

    def test_checkpoint_persists_workspace_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            init_project(project)
            task = write_json(project / "task.json", {"task_id": "T-001", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(task)).returncode, 0)
            running = write_json(project / "running.json", {"task_id": "T-001", "status": "RUNNING", "expected_revision": 1})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(running)).returncode, 0)
            checkpoint = write_json(project / "checkpoint.json", {"task_id": "T-001", "current_step": "inspect", "pending_steps": ["repair"]})
            result = run_script("create_checkpoint.py", "--project-root", str(project), "--input", str(checkpoint))
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads((project / ".agent/work/T-001/checkpoint.json").read_text(encoding="utf-8"))
            self.assertIn("workspace_snapshot", saved)
            self.assertRegex(saved["workspace_evidence_hash"], r"^[0-9a-f]{64}$")

    def test_expired_lock_with_live_owner_identity_is_not_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            init_project(project)
            lock_input = write_json(project / "lock.json", {"kind": "resource", "key": "shared", "run_id": "RUN-001", "owner": "executor", "lease_seconds": 60})
            self.assertEqual(run_script("acquire_lock.py", "--project-root", str(project), "--input", str(lock_input)).returncode, 0)
            lock_path = next((project / ".agent/locks/resources").glob("*.json"))
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["expires_at"] = "2000-01-01T00:00:00Z"
            lock["owner_pid"] = os.getpid()
            lock["owner_identity"] = "executor:live-test"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            replacement = write_json(project / "replacement.json", {"kind": "resource", "key": "shared", "run_id": "RUN-002", "owner": "new", "lease_seconds": 60})
            result = run_script("acquire_lock.py", "--project-root", str(project), "--input", str(replacement))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("live", result.stderr.lower())

    def test_recovery_persists_reconciliation_evidence_and_event_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            init_project(project)
            queued = write_json(project / "queued.json", {"task_id": "T-001", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            running = write_json(project / "running.json", {"task_id": "T-001", "status": "RUNNING", "expected_revision": 1})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(running)).returncode, 0)
            checkpoint = write_json(project / "checkpoint.json", {"task_id": "T-001", "current_step": "resume", "pending_steps": ["verify"], "resume_safe": True})
            self.assertEqual(run_script("create_checkpoint.py", "--project-root", str(project), "--input", str(checkpoint)).returncode, 0)
            heartbeat = write_json(project / "heartbeat.json", {"task_id": "T-001", "owner": "executor", "run_id": "RUN-001", "lease_seconds": 60})
            self.assertEqual(run_script("record_heartbeat.py", "--project-root", str(project), "--input", str(heartbeat)).returncode, 0)
            result = run_script("inspect_recovery.py", "--project-root", str(project), "--task-id", "T-001")
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)["results"][0]
            self.assertRegex(output["reconciliation_id"], r"^REC-T-001-")
            evidence = project / ".agent/recovery/reconciliation-T-001.json"
            self.assertTrue(evidence.is_file())
            self.assertIn(output["reconciliation_id"], evidence.read_text(encoding="utf-8"))
            self.assertIn("reconciliation_id", (project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8"))

    def test_terminal_cleanup_reports_reconciliation_for_malformed_artifact_and_blocks_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            init_project(project)
            queued = write_json(project / "queued.json", {"task_id": "T-001", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            cancelled = write_json(project / "cancelled.json", {"task_id": "T-001", "status": "CANCELLED", "expected_revision": 1})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(cancelled)).returncode, 0)
            broken = project / ".agent/locks/tasks/broken.json"
            broken.write_text("[]\n", encoding="utf-8")
            checked = run_script("verify_terminal_cleanup.py", "--project-root", str(project), "--task-id", "T-001")
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertIn('"classification": "NEEDS_RECONCILIATION"', checked.stdout)


if __name__ == "__main__":
    unittest.main()
