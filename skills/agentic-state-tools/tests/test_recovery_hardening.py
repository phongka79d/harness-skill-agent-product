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

from worktree_manager import CleanupBlocked, WorktreeError, WorktreeManager  # noqa: E402
from merge_worktree import merge_worktree  # noqa: E402


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


def init_git_project(path: Path) -> None:
    subprocess.run(["git", "init", "--initial-branch", "main"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "value.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "value.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True, text=True)


class RecoveryHardeningTests(unittest.TestCase):
    def test_stale_metadata_requires_expired_lease_and_authorized_reclaim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            init_git_project(project)
            manager = WorktreeManager(project, Path(directory) / "worktrees", lease_seconds=1)
            original = manager.create("TASK-1", 1)
            state_path = Path(manager.metadata_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            key = "TASK-1@1"
            state["entries"][key]["path"] = str(Path(directory) / "missing-worktree")
            state["entries"][key]["lease"]["expires_at"] = "2000-01-01T00:00:00Z"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(PermissionError):
                manager.reclaim("TASK-1", 1)
            reclaimed = manager.reclaim("TASK-1", 1, authorized=True)
            self.assertEqual(reclaimed["status"], "STALE")
            replacement = manager.create("TASK-1", 1)
            self.assertNotEqual(replacement["branch"], original["branch"])

    def test_cleanup_is_blocked_before_acceptance_and_conflicts_fence_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            init_git_project(project)
            root = Path(directory) / "worktrees"
            manager = WorktreeManager(project, root)
            entry = manager.create("TASK-1", 1)
            with self.assertRaises(CleanupBlocked):
                manager.cleanup("TASK-1", 1)
            source = Path(entry["path"])
            (source / "value.txt").write_text("from-task\n", encoding="utf-8")
            subprocess.run(["git", "add", "value.txt"], cwd=source, check=True)
            subprocess.run(["git", "commit", "-m", "task-change"], cwd=source, check=True, capture_output=True, text=True)
            (project / "value.txt").write_text("from-target\n", encoding="utf-8")
            subprocess.run(["git", "add", "value.txt"], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "target-change"], cwd=project, check=True, capture_output=True, text=True)
            result = merge_worktree(project, root, "TASK-1", 1, "main", authorized=True)
            self.assertEqual(result["status"], "RECOVERY_PENDING")
            self.assertTrue(Path(result["conflict_artifact"]).is_file())
            self.assertEqual(manager.get("TASK-1", 1)["status"], "RECOVERY_PENDING")

    def test_worktree_branches_are_not_reused_across_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            init_git_project(project)
            manager = WorktreeManager(project, Path(directory) / "worktrees")
            first = manager.create("TASK-1", 1)
            second = manager.create("TASK-1", 2)
            self.assertNotEqual(first["branch"], second["branch"])
            self.assertEqual(manager.create("TASK-1", 1)["branch"], first["branch"])

    def test_workspace_lock_reclaims_a_lock_owned_by_a_dead_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            init_git_project(project)
            root = Path(directory) / "worktrees"
            manager = WorktreeManager(project, root)
            manager.lock_path.write_text(
                json.dumps({"pid": 99999999, "acquired_at": "2000-01-01T00:00:00Z", "expires_at": "2000-01-01T00:01:00Z"}),
                encoding="utf-8",
            )
            entry = manager.create("TASK-DEAD-LOCK", 1)
            self.assertEqual(entry["status"], "ACTIVE")
            self.assertFalse(manager.lock_path.exists())

    def test_worktree_registry_writes_are_schema_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            init_git_project(project)
            manager = WorktreeManager(project, Path(directory) / "worktrees")
            invalid = manager._empty_state()
            invalid["schema_version"] = 2
            with self.assertRaises(WorktreeError):
                manager._save_state(invalid)

    def test_worktree_cleanup_rejects_metadata_path_outside_configured_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            init_git_project(project)
            manager = WorktreeManager(project, Path(directory) / "worktrees")
            manager.create("TASK-OUTSIDE", 1)
            state = json.loads(manager.metadata_path.read_text(encoding="utf-8"))
            entry = state["entries"]["TASK-OUTSIDE@1"]
            entry["path"] = str(project)
            entry["status"] = "ACCEPTED"
            entry["lease"] = None
            manager.metadata_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(CleanupBlocked, "outside configured worktree root"):
                manager.cleanup("TASK-OUTSIDE", 1)

    def test_worktree_cleanup_rejects_metadata_path_outside_configured_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            init_git_project(project)
            manager = WorktreeManager(project, Path(directory) / "worktrees")
            manager.create("TASK-OUTSIDE", 1)
            state = json.loads(manager.metadata_path.read_text(encoding="utf-8"))
            entry = state["entries"]["TASK-OUTSIDE@1"]
            entry["path"] = str(project)
            entry["status"] = "ACCEPTED"
            entry["lease"] = None
            manager.metadata_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(CleanupBlocked, "outside configured worktree root"):
                manager.cleanup("TASK-OUTSIDE", 1)
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
