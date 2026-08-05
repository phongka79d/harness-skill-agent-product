from __future__ import annotations

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

from capture_workspace_baseline import BaselineError, _command_text, capture_workspace_baseline  # noqa: E402
from validate_payload import validate  # noqa: E402
from worktree_manager import WorktreeManager  # noqa: E402


def init_git_project(path: Path) -> str:
    subprocess.run(["git", "init", "--initial-branch", "main"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "value.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "value.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True, text=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


class WorkspaceBaselineTests(unittest.TestCase):
    def test_clean_baseline_is_identity_bound_and_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            base_commit = init_git_project(project)
            artifact = capture_workspace_baseline(
                project,
                task_id="TASK-BASELINE",
                run_id="RUN-BASELINE",
                base_commit=base_commit,
                baseline_commands=[[sys.executable, "-c", "print('ok')"]],
            )

            self.assertEqual(artifact["status"], "CLEAN")
            self.assertEqual(artifact["base_commit"], base_commit)
            self.assertEqual(artifact["head_commit"], base_commit)
            self.assertFalse(artifact["is_isolated"])
            self.assertEqual(
                validate(
                    artifact,
                    json.loads((SKILL_ROOT / "schemas/workspace-baseline.schema.json").read_text(encoding="utf-8")),
                    base_path=SKILL_ROOT / "schemas",
                ),
                [],
            )

    def test_existing_failure_requires_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            init_git_project(project)
            command = [sys.executable, "-c", "import sys; sys.exit(3)"]
            command_text = _command_text(command)

            blocked = capture_workspace_baseline(
                project,
                task_id="TASK-FAIL",
                run_id="RUN-FAIL",
                baseline_commands=[command],
            )
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertFalse(blocked["known_failures"][0]["approved"])

            approved = capture_workspace_baseline(
                project,
                task_id="TASK-FAIL-APPROVED",
                run_id="RUN-FAIL-APPROVED",
                baseline_commands=[command],
                known_failures=[command_text],
            )
            self.assertEqual(approved["status"], "KNOWN_FAILURES_APPROVED")
            self.assertTrue(approved["known_failures"][0]["approved"])

    def test_base_commit_mismatch_is_rejected_before_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            init_git_project(project)
            with self.assertRaisesRegex(BaselineError, "base_commit"):
                capture_workspace_baseline(
                    project,
                    task_id="TASK-MISMATCH",
                    run_id="RUN-MISMATCH",
                    base_commit="a" * 40,
                    baseline_commands=[[sys.executable, "-c", "print('should not run')"]],
                )

    def test_worktree_registry_requires_approved_baseline_for_async_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            base_commit = init_git_project(project)
            manager = WorktreeManager(project, Path(directory) / "external-worktrees")
            entry = manager.create("TASK-WORKTREE", 1)
            baseline = {
                "baseline_id": "BASELINE-TASK-WORKTREE-1",
                "task_id": "TASK-WORKTREE",
                "run_id": "RUN-WORKTREE",
                "worktree_path": entry["path"],
                "branch": entry["branch"],
                "base_commit": base_commit,
                "workspace_hash": "a" * 64,
                "status": "CLEAN",
                "captured_at": "2026-08-05T00:00:00Z",
            }
            manager.attach_baseline("TASK-WORKTREE", 1, baseline)
            proof = manager.validate_isolation("TASK-WORKTREE", 1, require_baseline=True)
            self.assertEqual(proof["baseline_id"], baseline["baseline_id"])
            self.assertEqual(proof["baseline_status"], "CLEAN")


if __name__ == "__main__":
    unittest.main()
