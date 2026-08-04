from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from inspect_recovery import classify_async_worktree  # noqa: E402
from merge_worktree import build_merge_authorization_target, merge_worktree  # noqa: E402
from resolve_execution_mode import resolve_execution_mode  # noqa: E402
from worktree_manager import CleanupBlocked, WorktreeManager  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def git(project: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=project, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def init_git_project(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--initial-branch", "main"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "value.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "value.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True, text=True)
    return git(path, "rev-parse", "HEAD")


def init_runtime(project: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "init_runtime.py"), "--project-root", str(project)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)


class Task4MergeRecoveryTests(unittest.TestCase):
    def _merge_fixture(self) -> tuple[Path, Path, WorktreeManager, dict[str, object], dict[str, object]]:
        directory = Path(tempfile.mkdtemp())
        project = directory / "project"
        base_commit = init_git_project(project)
        init_runtime(project)
        worktree_root = directory / "worktrees"
        manager = WorktreeManager(project, worktree_root)
        entry = manager.create("TASK-MERGE", 1)
        source = Path(str(entry["path"]))
        (source / "value.txt").write_text("task change\n", encoding="utf-8")
        subprocess.run(["git", "add", "value.txt"], cwd=source, check=True)
        subprocess.run(["git", "commit", "-m", "task change"], cwd=source, check=True, capture_output=True, text=True)

        task = {
            "task_id": "TASK-MERGE",
            "plan_id": "MP-1",
            "plan_revision": 4,
            "batch_id": "B-1",
            "status": "ACCEPTED",
            "revision": 3,
            "run_id": "RUN-MERGE",
            "attempt_id": "ATTEMPT-MERGE",
            "dispatch_id": "DISPATCH-MERGE",
            "worktree_path": entry["path"],
            "branch_name": entry["branch"],
            "base_commit": base_commit,
            "input_artifact_hashes": {"plan": "a" * 64},
            "output_artifact_hashes": {"result": "b" * 64},
            "review_verdict": "PASS",
        }
        write_json(project / ".agent/work/TASK-MERGE/task-state.json", task)
        write_json(
            project / ".agent/work/TASK-MERGE/review.json",
            {"task_id": "TASK-MERGE", "revision": 1, "verdict": "PASS", "artifact_hash": "c" * 64},
        )
        write_json(
            project / ".agent/work/B-1/batch-contract.json",
            {
                "batch_id": "B-1",
                "revision": 1,
                "contract_hash": "d" * 64,
                "tasks": [{"task_id": "TASK-MERGE", "task_revision": 3}],
            },
        )
        write_json(
            project / ".agent/work/TASK-MERGE/lease.json",
            {
                "task_id": "TASK-MERGE",
                "task_revision": 3,
                "run_id": "RUN-MERGE",
                "attempt_id": "ATTEMPT-MERGE",
                "dispatch_id": "DISPATCH-MERGE",
                "owner": "agent-executor",
                "owner_identity": "agent-executor",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )
        queue = {
            "tasks": [{
                "task_id": "TASK-MERGE",
                "run_id": "RUN-MERGE",
                "attempt_id": "ATTEMPT-MERGE",
                "dispatch_id": "DISPATCH-MERGE",
                "execution_mode": "ASYNC",
                "worktree_path": entry["path"],
                "branch_name": entry["branch"],
                "base_commit": base_commit,
                "plan_revision": 4,
                "input_hashes": {"plan": "a" * 64},
            }],
            "dispatches": [{
                "task_id": "TASK-MERGE",
                "dispatch_id": "DISPATCH-MERGE",
                "run_id": "RUN-MERGE",
                "attempt_id": "ATTEMPT-MERGE",
                "task_revision": 3,
                "worktree_path": entry["path"],
                "branch_name": entry["branch"],
                "base_commit": base_commit,
                "plan_revision": 4,
                "input_artifact_hashes": {"plan": "a" * 64},
            }],
        }
        write_json(project / ".agent/runtime/queue.json", queue)
        return directory, project, manager, task, entry

    def test_merge_rejects_missing_persisted_approval(self) -> None:
        directory, project, manager, _task, entry = self._merge_fixture()
        try:
            with self.assertRaises(PermissionError):
                merge_worktree(
                    project,
                    directory / "worktrees",
                    "TASK-MERGE",
                    1,
                    "main",
                    approval=None,
                    actor="user-1",
                    actor_type="user",
                )
        finally:
            manager.release_lease("TASK-MERGE", 1)

    def test_merge_accepts_only_a_current_typed_persisted_approval(self) -> None:
        directory, project, manager, task, _entry = self._merge_fixture()
        try:
            target = build_merge_authorization_target(project, directory / "worktrees", "TASK-MERGE", 1, "main")
            approval = {
                "approval_id": "APR-WORKTREE-TASK-MERGE-1",
                "target_type": "WORKTREE",
                "target_id": "TASK-MERGE",
                "decision": "APPROVED",
                "approver": "user-1",
                "actor_type": "user",
                "actor_id": "user-1",
                "action": "WORKTREE_MERGE",
                "target_revision": 1,
                "target_hash": target["target_hash"],
                "policy_version": "1",
                "expires_at": "2099-01-01T00:00:00Z",
                "evidence": "review PASS and batch membership verified",
                "created_at": "2026-08-04T00:00:00Z",
                "revision": 1,
            }
            write_json(project / ".agent/approvals/WORKTREE-TASK-MERGE.json", approval)
            result = merge_worktree(
                project,
                directory / "worktrees",
                "TASK-MERGE",
                1,
                "main",
                approval=approval,
                actor="user-1",
                actor_type="user",
            )
            self.assertEqual(result["status"], "MERGED")
            self.assertEqual(result["approval_id"], approval["approval_id"])
            self.assertEqual(git(project, "show", "HEAD:value.txt"), "task change")
            self.assertEqual(manager.get("TASK-MERGE", 1)["status"], "MERGED")
        finally:
            if manager.get("TASK-MERGE", 1).get("status") != "MERGED":
                manager.release_lease("TASK-MERGE", 1)

    def test_merge_rejects_queue_worktree_metadata_mismatch(self) -> None:
        directory, project, manager, _task, _entry = self._merge_fixture()
        try:
            queue_path = project / ".agent/runtime/queue.json"
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            queue["tasks"][0]["worktree_path"] = "C:/wrong-worktree"
            write_json(queue_path, queue)
            with self.assertRaises(ValueError):
                build_merge_authorization_target(project, directory / "worktrees", "TASK-MERGE", 1, "main")
        finally:
            manager.release_lease("TASK-MERGE", 1)

    def test_async_recovery_marks_uncommitted_worktree_stale_requires_review(self) -> None:
        directory = Path(tempfile.mkdtemp())
        project = directory / "project"
        base_commit = init_git_project(project)
        init_runtime(project)
        manager = WorktreeManager(project, directory / "worktrees")
        entry = manager.create("TASK-RECOVERY", 1)
        task = {
            "task_id": "TASK-RECOVERY",
            "status": "RUNNING",
            "revision": 2,
            "run_id": "RUN-RECOVERY",
            "attempt_id": "ATTEMPT-RECOVERY",
            "dispatch_id": "DISPATCH-RECOVERY",
            "execution_mode": "ASYNC",
            "worktree_path": entry["path"],
            "branch_name": entry["branch"],
            "base_commit": base_commit,
        }
        write_json(project / ".agent/work/TASK-RECOVERY/task-state.json", task)
        write_json(
            project / ".agent/work/TASK-RECOVERY/lease.json",
            {
                "task_id": "TASK-RECOVERY",
                "task_revision": 2,
                "run_id": "RUN-RECOVERY",
                "attempt_id": "ATTEMPT-RECOVERY",
                "dispatch_id": "DISPATCH-RECOVERY",
                "owner": "agent-executor",
                "owner_identity": "agent-executor",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )
        try:
            self.assertEqual(classify_async_worktree(project, task), "RESUMABLE")
            Path(str(entry["path"]) + "/value.txt").write_text("uncommitted\n", encoding="utf-8")
            self.assertEqual(classify_async_worktree(project, task), "STALE_REQUIRES_REVIEW")
        finally:
            manager.release_lease("TASK-RECOVERY", 1)

    def test_cleanup_rejects_clean_branch_commit_not_reconciled_into_target(self) -> None:
        directory = Path(tempfile.mkdtemp())
        project = directory / "project"
        init_git_project(project)
        manager = WorktreeManager(project, directory / "worktrees")
        entry = manager.create("TASK-CLEANUP", 1)
        source = Path(str(entry["path"]))
        (source / "value.txt").write_text("unmerged commit\n", encoding="utf-8")
        subprocess.run(["git", "add", "value.txt"], cwd=source, check=True)
        subprocess.run(["git", "commit", "-m", "unmerged commit"], cwd=source, check=True, capture_output=True, text=True)
        manager.set_status("TASK-CLEANUP", 1, "ACCEPTED")
        manager.release_lease("TASK-CLEANUP", 1)
        with self.assertRaises(CleanupBlocked):
            manager.cleanup("TASK-CLEANUP", 1)

    def test_resolver_uses_supplied_time_when_classifying_expired_lease(self) -> None:
        config = {
            "async_execution": {
                "capability_enabled": True,
                "allow_task_opt_in": True,
                "max_parallel_tasks": 2,
                "require_isolated_worktree": True,
                "require_separate_branch": True,
                "require_disjoint_write_scope": True,
                "require_dependency_clearance": True,
                "require_pinned_plan_revision": True,
                "require_pinned_input_hashes": True,
                "require_authorized_merge": True,
                "fallback_to_sync": True,
                "automatic_merge": False,
            },
            "agents": {"agent-executor": {"capabilities": ["repository_editing"]}},
            "planning": {"task_type_capabilities": {"backend": "repository_editing"}},
        }
        task = {
            "task_id": "TASK-TIME",
            "status": "READY",
            "owner": "agent-executor",
            "task_type": "backend",
            "depends_on": [],
            "write_scope": ["src/time.py"],
            "plan_revision": 3,
            "input_artifact_hashes": {"plan": "a" * 64},
            "merge_independent": True,
            "execution_policy": {"requested_mode": "ASYNC_REQUIRED"},
        }
        proof = {
            "task_id": "TASK-TIME",
            "run_id": "RUN-TIME",
            "worktree_path": "C:/worktrees/task-time",
            "branch_name": "async/task-time",
            "base_commit": "b" * 40,
            "plan_revision": 3,
            "write_scope_hash": "c" * 64,
            "active_conflicts_checked_at": "2099-01-01T00:00:00Z",
            "isolation_status": "VERIFIED",
        }
        result = resolve_execution_mode(
            task,
            config=config,
            active_tasks=[],
            queue={"available_slots": 1, "tasks": []},
            lease={"expires_at": "2100-01-01T00:00:00Z"},
            isolation_proof=proof,
            now=datetime(2101, 1, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result["resolved_mode"], "BLOCKED")
        self.assertEqual(result["resolution_reason"], "LEASE_EXPIRED")


if __name__ == "__main__":
    unittest.main()
