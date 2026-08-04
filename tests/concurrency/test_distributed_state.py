from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / "agentic-state-tools"
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
sys.path.insert(0, str(SCRIPTS))

from distributed_store import (  # noqa: E402
    EventConflict,
    FileStateStore,
    NetworkUncertain,
    OwnershipConflict,
    ReconciliationRequired,
    RemoteStateClient,
    RevisionConflict,
)
from runtime_utils import apply_event, empty_state  # noqa: E402
from resolve_execution_mode import resolve_execution_mode  # noqa: E402
from validate_payload import validate  # noqa: E402
from worktree_manager import (  # noqa: E402
    WorktreeError,
    WorkspaceBusy,
    WorktreeManager,
    validate_canonical_isolation_proof,
)


BASE_TIME = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def init_git_project(path: Path) -> str:
    subprocess.run(["git", "init", "--initial-branch", "main"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True, text=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


def event(event_id: str, task_id: str = "T-001") -> dict[str, object]:
    return {
        "event_id": event_id,
        "timestamp": "2026-08-02T12:00:00Z",
        "type": "TASK_QUEUED",
        "actor": "primary-agent",
        "task_id": task_id,
    }


class FailingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, path: str, body: dict[str, object] | None, headers: dict[str, str]) -> object:
        self.calls.append({"method": method, "path": path, "body": body, "headers": headers})
        raise TimeoutError("connection reset after request")


class ErrorTransport:
    def request(self, method: str, path: str, body: dict[str, object] | None, headers: dict[str, str]) -> object:
        return {"error": {"message": "remote did not classify the response"}}


class DistributedStateTests(unittest.TestCase):
    def test_canonical_isolation_proof_requires_exact_verified_identity(self) -> None:
        task = {
            "task_id": "TASK-CANONICAL",
            "run_id": "RUN-CANONICAL",
            "plan_revision": 3,
            "worktree_path": "C:/worktrees/task-canonical",
            "branch_name": "async/task-canonical",
        }
        proof = {
            "task_id": "TASK-CANONICAL",
            "run_id": "RUN-CANONICAL",
            "worktree_path": "C:/worktrees/task-canonical",
            "branch_name": "async/task-canonical",
            "base_commit": "b" * 40,
            "plan_revision": 3,
            "write_scope_hash": "c" * 64,
            "active_conflicts_checked_at": "2026-08-02T12:00:00Z",
            "isolation_status": "VERIFIED",
        }
        self.assertTrue(validate_canonical_isolation_proof(task, proof))
        self.assertFalse(validate_canonical_isolation_proof(task, {**proof, "isolation_status": "PENDING"}))
        self.assertFalse(validate_canonical_isolation_proof(task, {**proof, "task_id": "OTHER"}))
        self.assertFalse(validate_canonical_isolation_proof(task, {**proof, "unexpected": True}))

    def test_execution_policy_accepts_canonical_proof_without_legacy_manager_envelope(self) -> None:
        task = {
            "task_id": "TASK-CANONICAL-RESOLVE",
            "status": "READY",
            "owner": "agent-executor",
            "task_type": "backend",
            "depends_on": [],
            "write_scope": ["src/policy.py"],
            "plan_revision": 3,
            "input_artifact_hashes": {"plan": "a" * 64},
            "merge_independent": True,
            "execution_policy": {"requested_mode": "ASYNC_PREFERRED"},
        }
        proof = {
            "task_id": "TASK-CANONICAL-RESOLVE",
            "run_id": "RUN-CANONICAL-RESOLVE",
            "worktree_path": "C:/worktrees/task-canonical-resolve",
            "branch_name": "async/task-canonical-resolve",
            "base_commit": "b" * 40,
            "plan_revision": 3,
            "write_scope_hash": "c" * 64,
            "active_conflicts_checked_at": "2026-08-02T12:00:00Z",
            "isolation_status": "VERIFIED",
        }
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
            },
            "agents": {"agent-executor": {"capabilities": ["repository_editing"]}},
            "planning": {"task_type_capabilities": {"backend": "repository_editing"}},
        }
        policy = resolve_execution_mode(
            task,
            config=config,
            active_tasks=[],
            queue={"revision": 0, "tasks": []},
            lease={"expires_at": "2099-01-01T00:00:00Z"},
            isolation_proof=proof,
            now=BASE_TIME,
        )
        self.assertEqual(policy["resolved_mode"], "ASYNC")

    def test_execution_policy_resolves_requested_modes_with_complete_identity(self) -> None:
        config = {
            "async_execution": {
                "capability_enabled": True,
                "default_mode": "async",
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
            "version_control": {"isolated_worktrees": True},
            "agents": {"agent-executor": {"capabilities": ["repository_editing"]}},
            "planning": {"task_type_capabilities": {"backend": "repository_editing"}},
        }
        task = {
            "task_id": "TASK-POLICY",
            "status": "READY",
            "owner": "agent-executor",
            "task_type": "backend",
            "depends_on": [],
            "write_scope": ["src/policy.py"],
            "plan_revision": 3,
            "input_artifact_hashes": {"plan": "a" * 64},
            "merge_independent": True,
            "execution_policy": {
                "requested_mode": "ASYNC_PREFERRED",
                "resolved_mode": None,
                "resolution_reason": "",
                "resolved_by": "",
                "resolved_at": "",
                "isolation_proof": None,
            },
        }
        proof = {
            "task_id": "TASK-POLICY",
            "run_id": "RUN-POLICY",
            "worktree_path": "C:/worktrees/task-policy",
            "branch_name": "async/task-policy",
            "base_commit": "b" * 40,
            "plan_revision": 3,
            "write_scope_hash": "c" * 64,
            "active_conflicts_checked_at": "2026-08-02T12:00:00Z",
            "isolation_status": "VERIFIED",
        }
        lease = {
            "task_id": "TASK-POLICY",
            "run_id": "RUN-POLICY",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        queue = {"revision": 4, "tasks": [], "available_slots": 2}
        with patch("resolve_execution_mode.validate_isolation_proof", return_value=True):
            policy = resolve_execution_mode(
                task,
                config=config,
                active_tasks=[],
                queue=queue,
                lease=lease,
                isolation_proof=proof,
                now=BASE_TIME,
            )
        self.assertEqual(set(policy), {"requested_mode", "resolved_mode", "resolution_reason", "resolved_by", "resolved_at", "isolation_proof"})
        self.assertEqual(policy["resolved_mode"], "ASYNC")
        self.assertEqual(policy["requested_mode"], "ASYNC_PREFERRED")
        self.assertEqual(policy["isolation_proof"], proof)

    def test_async_required_blocks_with_machine_readable_reason_when_proof_is_missing(self) -> None:
        config = {"async_execution": {
            "capability_enabled": True, "default_mode": "sync", "allow_task_opt_in": True,
            "max_parallel_tasks": 2, "require_isolated_worktree": True, "require_separate_branch": True,
            "require_disjoint_write_scope": True, "require_dependency_clearance": True,
            "require_pinned_plan_revision": True, "require_pinned_input_hashes": True,
            "require_authorized_merge": True, "fallback_to_sync": True, "automatic_merge": False,
        }}
        task = {"task_id": "TASK-BLOCKED", "status": "READY", "execution_policy": {
            "requested_mode": "ASYNC_REQUIRED", "resolved_mode": None, "resolution_reason": "",
            "resolved_by": "", "resolved_at": "", "isolation_proof": None,
        }}
        policy = resolve_execution_mode(task, config=config, active_tasks=[], queue={"revision": 0, "tasks": []}, lease=None, isolation_proof=None, now=BASE_TIME)
        self.assertEqual(policy["resolved_mode"], "BLOCKED")
        self.assertTrue(policy["resolution_reason"].startswith("ISOLATION_PROOF_MISSING"))
    def test_worktree_mapping_is_unique_persistent_and_rejects_shared_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            init_git_project(project)
            root = Path(directory) / "worktrees"
            manager = WorktreeManager(project, root)
            first = manager.create("TASK-1", 1)
            second = manager.create("TASK-2", 1)
            revision = manager.create("TASK-1", 2)
            self.assertEqual(len({first["path"], second["path"], revision["path"]}), 3)
            self.assertEqual(len({first["branch"], second["branch"], revision["branch"]}), 3)
            self.assertEqual(WorktreeManager(project, root).get("TASK-1", 1), first)
            with self.assertRaises(WorktreeError):
                WorktreeManager(project, project / "inside")

    def test_workspace_lock_and_async_resolution_fail_closed_without_manager_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            init_git_project(project)
            root = Path(directory) / "worktrees"
            manager = WorktreeManager(project, root)
            manager.create("TASK-1", 1)
            config = {
                "execution": {
                    "default_mode": "auto",
                    "async_execution_enabled": True,
                    "async_requires_isolated_worktree": True,
                },
                "version_control": {"isolated_worktrees": True},
            }
            with patch("resolve_execution_mode.load_config", return_value=config):
                self.assertEqual(
                    resolve_execution_mode(
                        {"task_id": "TASK-1", "revision": 1, "execution_mode": "async"}
                    ),
                    "BLOCKED",
                )
                proof = manager.validate_isolation("TASK-1", 1)
                self.assertEqual(
                    resolve_execution_mode(
                        {"task_id": "TASK-1", "revision": 1, "execution_mode": "async"},
                        isolation_proof=proof,
                    ),
                    "ASYNC",
                )
            other = WorktreeManager(project, root)
            with manager.workspace_lock():
                with self.assertRaises(WorkspaceBusy):
                    other.create("TASK-2", 1)
    def test_remote_contract_schemas_exist_and_validate_initial_snapshot(self) -> None:
        for name in (
            "remote-event.schema.json",
            "remote-snapshot.schema.json",
            "distributed-lock.schema.json",
            "remote-error.schema.json",
        ):
            self.assertTrue((SCHEMAS / name).is_file(), name)
        schema = json.loads((SCHEMAS / "remote-snapshot.schema.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            snapshot = FileStateStore(Path(directory)).read_snapshot()
        self.assertEqual(validate(snapshot, schema), [])

    def test_event_append_enforces_revision_etag_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = FileStateStore(Path(directory))
            initial = store.read_snapshot()
            first = store.append_event(event("EVT-000001"), expected_revision=initial["revision"], expected_etag=initial["etag"])
            replay = store.append_event(event("EVT-000001"), expected_revision=initial["revision"], expected_etag=initial["etag"])
            self.assertEqual(replay, first)
            with self.assertRaises(RevisionConflict):
                store.append_event(event("EVT-000002"), expected_revision=0, expected_etag=initial["etag"])
            with self.assertRaises(EventConflict):
                store.append_event({**event("EVT-000001"), "actor": "different-owner"}, expected_revision=0, expected_etag=initial["etag"])

    def test_lock_heartbeat_and_release_require_owner_and_fencing_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = FileStateStore(Path(directory))
            lock = store.acquire_lock("task", "T-001", "machine-a", "RUN-001", 60, now=BASE_TIME)
            with self.assertRaises(OwnershipConflict):
                store.heartbeat(lock["lock_id"], "machine-b", "RUN-001", lock["fencing_token"], 60, now=BASE_TIME)
            refreshed = store.heartbeat(lock["lock_id"], "machine-a", "RUN-001", lock["fencing_token"], 60, now=BASE_TIME)
            self.assertGreaterEqual(refreshed["expires_at"], "2026-08-02T12:01:00Z")
            with self.assertRaises(OwnershipConflict):
                store.release_lock(lock["lock_id"], "machine-a", "RUN-001", lock["fencing_token"] + 1)
            store.release_lock(lock["lock_id"], "machine-a", "RUN-001", lock["fencing_token"])
            self.assertEqual(store.list_locks(), [])

    def test_expired_reclaim_increments_fencing_and_rejects_stale_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = FileStateStore(Path(directory))
            old = store.acquire_lock("file", "src/a.py", "machine-a", "RUN-001", 1, now=BASE_TIME)
            replacement = store.acquire_lock(
                "file",
                "src/a.py",
                "machine-b",
                "RUN-002",
                60,
                now=BASE_TIME.replace(second=2),
                reclaim_expired=True,
            )
            self.assertGreater(replacement["fencing_token"], old["fencing_token"])
            with self.assertRaises(OwnershipConflict):
                store.heartbeat(old["lock_id"], "machine-a", "RUN-001", old["fencing_token"], 60, now=BASE_TIME.replace(second=3))

    def test_replay_matches_local_runtime_state(self) -> None:
        events = [event("EVT-000001"), {**event("EVT-000002"), "type": "TASK_STARTED", "actor": "executor"}]
        expected = empty_state()
        with tempfile.TemporaryDirectory() as directory:
            store = FileStateStore(Path(directory))
            for item in events:
                current = store.read_snapshot()
                store.append_event(item, expected_revision=current["revision"], expected_etag=current["etag"])
                expected = apply_event(expected, item)
            self.assertEqual(store.read_snapshot()["state"], expected)

    def test_malformed_remote_state_requires_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = FileStateStore(root)
            (root / "runtime/state.json").write_text("[]\n", encoding="utf-8")
            with self.assertRaises(ReconciliationRequired) as raised:
                store.read_snapshot()
            self.assertEqual(raised.exception.classification, "NEEDS_RECONCILIATION")

    def test_snapshot_replay_mismatch_requires_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = FileStateStore(root)
            state = json.loads((root / "runtime/state.json").read_text(encoding="utf-8"))
            state["task_statuses"]["T-001"] = "RUNNING"
            (root / "runtime/state.json").write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(ReconciliationRequired):
                store.read_snapshot()

    def test_network_uncertainty_is_structured_and_not_retried(self) -> None:
        transport = FailingTransport()
        client = RemoteStateClient("https://state.example", transport)
        with self.assertRaises(NetworkUncertain) as raised:
            client.append_event(event("EVT-000001"), expected_revision=0, expected_etag="0" * 64)
        self.assertEqual(raised.exception.classification, "NETWORK_UNCERTAIN")
        self.assertTrue(raised.exception.operation_id)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0]["headers"]["Idempotency-Key"], raised.exception.operation_id)
        error_record = raised.exception.to_record()
        self.assertEqual(error_record["classification"], "NETWORK_UNCERTAIN")
        error_schema = json.loads((SCHEMAS / "remote-error.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(error_record, error_schema), [])

    def test_unclassified_remote_error_requires_reconciliation(self) -> None:
        client = RemoteStateClient("https://state.example", ErrorTransport())
        with self.assertRaises(ReconciliationRequired):
            client.read_snapshot()

    def test_cli_snapshot_and_append_event_use_the_same_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "remote-store"
            snapshot_command = [sys.executable, str(SCRIPTS / "distributed_store.py"), "snapshot", "--store-root", str(root)]
            initial = subprocess.run(snapshot_command, text=True, capture_output=True, check=False, timeout=20)
            self.assertEqual(initial.returncode, 0, initial.stderr)
            initial_snapshot = json.loads(initial.stdout)
            event_path = Path(directory) / "event.json"
            event_path.write_text(json.dumps(event("EVT-000001")), encoding="utf-8")
            appended = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "distributed_store.py"),
                    "append-event",
                    "--store-root",
                    str(root),
                    "--input",
                    str(event_path),
                    "--expected-revision",
                    str(initial_snapshot["revision"]),
                    "--expected-etag",
                    initial_snapshot["etag"],
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(appended.returncode, 0, appended.stderr)
            final = json.loads(subprocess.run(snapshot_command, text=True, capture_output=True, check=True, timeout=20).stdout)
            self.assertEqual(final["revision"], 1)


if __name__ == "__main__":
    unittest.main()
