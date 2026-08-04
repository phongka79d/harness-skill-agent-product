from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
sys.path.insert(0, str(SCRIPTS))

try:
    import runtime_transaction as transaction_module  # noqa: E402
    from runtime_transaction import RuntimeTransaction, recover_transactions  # noqa: E402
except ModuleNotFoundError:
    transaction_module = None
    RuntimeTransaction = None
    recover_transactions = None

try:
    from validate_payload import validate  # noqa: E402
except ModuleNotFoundError:
    validate = None

import inspect_recovery  # noqa: E402
import apply_change_request  # noqa: E402
import commit_batch  # noqa: E402
import merge_worktree  # noqa: E402
import record_approval  # noqa: E402
import record_operation  # noqa: E402
import create_batch_review  # noqa: E402
import create_review  # noqa: E402
import dispatch_transaction  # noqa: E402
import update_task_state  # noqa: E402
from runtime_transaction import TransactionError  # noqa: E402
from runtime_utils import RuntimeLockedError, runtime_lock  # noqa: E402
from worktree_manager import WorktreeManager  # noqa: E402


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def init_git_project(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--initial-branch", "main"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "value.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "value.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True, text=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


class TransactionRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.project = Path(self.directory.name)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "init_runtime.py"), "--project-root", str(self.project)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _generic_artifact_schema(self) -> Path:
        schema = self.project / "artifact.schema.json"
        if not schema.is_file():
            write_json(schema, {"type": "object"})
        return schema

    def _merge_conflict_fixture(self, *, conflict: bool = True) -> tuple[Path, WorktreeManager, dict, dict]:
        project = Path(self.directory.name) / "merge-project"
        base_commit = init_git_project(project)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "init_runtime.py"), "--project-root", str(project)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        worktree_root = Path(self.directory.name) / "merge-worktrees"
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
        write_json(
            project / ".agent/runtime/queue.json",
            {
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
            },
        )

        if conflict:
            (project / "value.txt").write_text("target change\n", encoding="utf-8")
            subprocess.run(["git", "add", "value.txt"], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "target change"], cwd=project, check=True, capture_output=True, text=True)
        target = merge_worktree.build_merge_authorization_target(project, worktree_root, "TASK-MERGE", 1, "main")
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
            "issued_at": "2026-08-04T00:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "evidence": "transaction merge boundary",
            "created_at": "2026-08-04T00:00:00Z",
            "revision": 1,
        }
        write_json(project / ".agent/approvals/WORKTREE-TASK-MERGE.json", approval)
        return project, manager, entry, approval

    def _require_runtime_transaction(self) -> None:
        if RuntimeTransaction is None or recover_transactions is None or transaction_module is None:
            self.fail("runtime_transaction.py does not expose the transaction API")

    def _new_transaction(
        self,
        operation_type: str = "TASK_STATE",
        idempotency_key: str = "T-1:state:1",
        *,
        expected_revisions: dict[str, int] | None = None,
        target_files: list[str] | None = None,
    ):
        self._require_runtime_transaction()
        targets = target_files or ["work/T-1/one.json", "work/T-1/two.json"]
        return RuntimeTransaction(
            self.project,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
            expected_revisions=expected_revisions or {target: 0 for target in targets},
        )

    def _new_core_transaction(
        self,
        *,
        operation_type: str = "TASK_STATE",
        idempotency_key: str = "core:T-1:1",
        expected_revisions: dict[str, int] | None = None,
    ):
        self._require_runtime_transaction()
        targets = ["work/T-1/one.json", "work/T-1/two.json"]
        return RuntimeTransaction(
            self.project,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
            expected_revisions=expected_revisions or {target: 0 for target in targets},
        )

    def test_core_public_api_derives_stable_operation_id_and_requires_prepare_targets(self) -> None:
        self._require_runtime_transaction()
        signature = inspect.signature(RuntimeTransaction.__init__)
        self.assertEqual(
            list(signature.parameters),
            ["self", "project_root", "operation_type", "idempotency_key", "expected_revisions"],
        )
        self.assertTrue(all(
            signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
            for name in ("operation_type", "idempotency_key", "expected_revisions")
        ))
        self.assertEqual(list(inspect.signature(RuntimeTransaction.prepare).parameters), ["self", "target_files"])
        self.assertEqual(
            list(inspect.signature(RuntimeTransaction.stage_json).parameters),
            ["self", "relative_path", "value", "schema_path"],
        )
        self.assertIs(inspect.signature(RuntimeTransaction.prepare).parameters["target_files"].default, inspect.Parameter.empty)
        self.assertIs(inspect.signature(RuntimeTransaction.stage_json).parameters["schema_path"].default, inspect.Parameter.empty)
        self.assertIs(RuntimeTransaction.__class__, type)
        self.assertFalse(hasattr(RuntimeTransaction, "_legacy_prepare"))
        self.assertFalse(hasattr(RuntimeTransaction, "_legacy_stage_json"))
        first = self._new_core_transaction()
        first_record = first.prepare(["work/T-1/one.json"])
        self.assertRegex(first_record["operation_id"], r"^OP-[A-Za-z0-9._-]+$")
        second = self._new_core_transaction()
        self.assertEqual(second.prepare(["work/T-1/one.json"])["operation_id"], first_record["operation_id"])

    def test_recovery_loader_rejects_unsafe_operation_id_and_manifest_path(self) -> None:
        self._require_runtime_transaction()
        key = "loader:T-1:1"
        record = {
            "operation_id": "OP-unsafe",
            "operation_type": "TASK_STATE",
            "idempotency_key": key,
            "expected_revisions": {},
            "target_files": [],
        }
        with self.assertRaisesRegex(TransactionError, "operation_id"):
            transaction_module._transaction_for_record(
                self.project,
                record,
                self.project / ".agent/runtime/transactions/invalid.json",
            )

        record["operation_id"] = "OP-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        with self.assertRaisesRegex(TransactionError, "manifest path"):
            transaction_module._transaction_for_record(
                self.project,
                record,
                self.project / "outside-transaction.json",
            )

    def test_apply_change_request_publishes_root_project_output_transactionally(self) -> None:
        output = self.project / "external-plan.json"
        value = {"change_request_id": "CR-EXTERNAL", "version": "1.1", "revision": 1}
        apply_change_request._write_plan_transactionally(output, value)

        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), value)
        manifests = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (self.project / ".agent/runtime/transactions").glob("*.json")
            if not path.name.endswith(".commit.json") and not path.name.endswith(".rollback.json")
        ]
        transaction = next(item for item in manifests if item.get("operation_type") == "PLAN_CHANGE")
        self.assertEqual(transaction["status"], "COMMITTED")
        self.assertEqual(transaction["target_files"], ["project/external-plan.json"])
        self.assertEqual(
            transaction["evidence"]["target_hashes"]["project/external-plan.json"],
            hashlib.sha256(output.read_bytes()).hexdigest(),
        )

    def test_stage_json_validates_the_supplied_schema_before_staging(self) -> None:
        transaction = self._new_core_transaction()
        transaction.prepare(["work/T-1/one.json"])
        schema = self.project / "artifact.schema.json"
        write_json(schema, {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}})

        with self.assertRaisesRegex(ValueError, "invalid"):
            transaction.stage_json("work/T-1/one.json", {"wrong": True}, schema)
        self.assertFalse(any((self.project / ".agent/runtime/staging").rglob("one.json")))
        transaction.stage_json("work/T-1/one.json", {"name": "valid"}, schema)

    def test_target_and_staged_paths_reject_traversal_and_symlink_escape(self) -> None:
        transaction = self._new_core_transaction()
        with self.assertRaises(ValueError):
            transaction.prepare(["../outside.json"])
        transaction = self._new_core_transaction(
            idempotency_key="core:project-escape",
            expected_revisions={"project/outside.json": 0},
        )
        with self.assertRaises(ValueError):
            transaction.prepare([str(self.project / "outside.json")])

        outside = Path(self.directory.name) / "outside.json"
        outside.write_text("outside", encoding="utf-8")
        link = self.project / ".agent/work/T-1/link.json"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable in this Windows test environment")
        with self.assertRaises(ValueError):
            transaction.prepare(["work/T-1/link.json"])

        transaction = self._new_core_transaction(idempotency_key="core:staged-escape")
        transaction.prepare(["work/T-1/one.json"])
        schema = self.project / "artifact.schema.json"
        write_json(schema, {"type": "object"})
        transaction.stage_json("work/T-1/one.json", {"name": "valid"}, schema)
        manifest = transaction.manifest_path
        record = json.loads(manifest.read_text(encoding="utf-8"))
        record["staged_files"][0]["staged_path"] = "runtime/staging/../outside.json"
        manifest.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "staged path"):
            transaction.commit()

    def test_same_key_changed_content_and_conflicting_key_are_rejected_durably(self) -> None:
        schema = self.project / "artifact.schema.json"
        write_json(schema, {"type": "object"})
        transaction = self._new_core_transaction(idempotency_key="core:shared")
        transaction.prepare(["work/T-1/one.json"])
        transaction.stage_json("work/T-1/one.json", {"value": "one"}, schema)
        with self.assertRaisesRegex(RuntimeError, "idempotency"):
            transaction.stage_json("work/T-1/one.json", {"value": "changed-before-commit"}, schema)
        transaction.commit()

        replay = self._new_core_transaction(idempotency_key="core:shared")
        replay.prepare(["work/T-1/one.json"])
        with self.assertRaisesRegex(RuntimeError, "idempotency"):
            replay.stage_json("work/T-1/one.json", {"value": "changed"}, schema)

        conflict = self._new_core_transaction(operation_type="REVIEW", idempotency_key="core:shared")
        with self.assertRaisesRegex(RuntimeError, "idempotency|operation_type"):
            conflict.prepare(["work/T-1/one.json"])

    def test_recovery_marks_committed_marker_or_target_hash_tamper_pending(self) -> None:
        schema = self.project / "artifact.schema.json"
        write_json(schema, {"type": "object"})
        transaction = self._new_core_transaction(idempotency_key="core:tamper")
        transaction.prepare(["work/T-1/one.json"])
        transaction.stage_json("work/T-1/one.json", {"value": "one"}, schema)
        committed = transaction.commit()
        marker = self.project / ".agent" / committed["commit_marker"]
        marker_record = json.loads(marker.read_text(encoding="utf-8"))
        marker_record["target_hashes"]["one"] = "0" * 64
        marker.write_text(json.dumps(marker_record), encoding="utf-8")
        recovered = recover_transactions(self.project)
        record = next(item for item in recovered if item["operation_id"] == committed["operation_id"])
        self.assertEqual(record["status"], "RECOVERY_PENDING")

    def test_partial_publish_with_unknown_replacement_is_recovery_pending(self) -> None:
        schema = self.project / "artifact.schema.json"
        write_json(schema, {"type": "object"})
        transaction = self._new_core_transaction(idempotency_key="core:partial")
        transaction.prepare(["work/T-1/one.json", "work/T-1/two.json"])
        transaction.stage_json("work/T-1/one.json", {"value": "one"}, schema)
        transaction.stage_json("work/T-1/two.json", {"value": "two"}, schema)
        target_two = (self.project / ".agent/work/T-1/two.json").resolve()
        original_replace = os.replace

        def fail_second_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
            if Path(destination).resolve() == target_two:
                raise OSError("replacement outcome is unknown")
            original_replace(source, destination)

        with patch.object(transaction_module.os, "replace", side_effect=fail_second_replace):
            with self.assertRaisesRegex(OSError, "unknown"):
                transaction.commit()
        (self.project / ".agent/work/T-1/two.json").write_bytes(b"unrelated bytes")
        recovered = recover_transactions(self.project)
        record = next(item for item in recovered if item["operation_id"] == transaction.operation_id)
        self.assertEqual(record["status"], "RECOVERY_PENDING")

    def test_runtime_lock_cannot_be_reentered_by_a_different_thread(self) -> None:
        from runtime_utils import RuntimeLockedError, runtime_lock

        acquired = threading.Event()
        release = threading.Event()

        def hold_lock() -> None:
            with runtime_lock(self.project):
                acquired.set()
                release.wait(timeout=5)

        holder = threading.Thread(target=hold_lock)
        holder.start()
        self.assertTrue(acquired.wait(timeout=5))
        try:
            with self.assertRaises(RuntimeLockedError):
                with runtime_lock(self.project):
                    pass
        finally:
            release.set()
            holder.join(timeout=5)

    def test_transaction_publishes_multiple_files_with_durable_hash_evidence(self) -> None:
        transaction = self._new_transaction()
        staging = self.project / ".agent/runtime/staging" / transaction.operation_id

        prepared = transaction.prepare(["work/T-1/one.json", "work/T-1/two.json"])
        self.assertEqual(prepared["status"], "PREPARED")
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"}, self._generic_artifact_schema())
        transaction.stage_json("work/T-1/two.json", {"revision": 1, "value": "two"}, self._generic_artifact_schema())

        self.assertTrue((staging / "work/T-1/one.json").is_file())
        self.assertFalse((self.project / ".agent/work/T-1/one.json").exists())

        committed = transaction.commit()
        self.assertEqual(committed["status"], "COMMITTED")
        self.assertIsNotNone(committed["committed_at"])
        self.assertIsNone(committed["rollback_reason"])
        self.assertFalse(staging.exists())
        self.assertEqual(json.loads((self.project / ".agent/work/T-1/one.json").read_text(encoding="utf-8"))["value"], "one")
        self.assertEqual(json.loads((self.project / ".agent/work/T-1/two.json").read_text(encoding="utf-8"))["value"], "two")

        records = [
            json.loads(line)
            for line in (self.project / ".agent/runtime/transactions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual([record["status"] for record in records], ["PREPARED", "APPLYING", "COMMITTED"])
        self.assertEqual(committed["evidence"]["classification"], "COMMITTED")
        for staged_file in committed["staged_files"]:
            target = self.project / ".agent" / staged_file["target_path"]
            target_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            self.assertEqual(staged_file["target_hash"], target_hash)
        self.assertEqual(validate(committed, json.loads((SCHEMAS / "transaction.schema.json").read_text(encoding="utf-8"))), [])

    def test_expected_revision_is_checked_before_any_staging(self) -> None:
        self._require_runtime_transaction()
        target = self.project / ".agent/work/T-1/one.json"
        write_json(target, {"revision": 3, "value": "old"})
        transaction = self._new_transaction(expected_revisions={"work/T-1/one.json": 2, "work/T-1/two.json": 0})
        staging = self.project / ".agent/runtime/staging" / transaction.operation_id
        manifest = self.project / ".agent/runtime/transactions" / f"{transaction.operation_id}.json"

        with self.assertRaisesRegex(ValueError, "stale revision"):
            transaction.prepare(["work/T-1/one.json", "work/T-1/two.json"])

        self.assertFalse(staging.exists())
        self.assertFalse(manifest.exists())

    def test_rollback_removes_staged_files_and_is_idempotent(self) -> None:
        transaction = self._new_transaction()
        staging = self.project / ".agent/runtime/staging" / transaction.operation_id
        transaction.prepare(["work/T-1/one.json", "work/T-1/two.json"])
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"}, self._generic_artifact_schema())

        rolled_back = transaction.rollback("validation failed")
        self.assertEqual(rolled_back["status"], "ROLLED_BACK")
        self.assertEqual(rolled_back["rollback_reason"], "validation failed")
        self.assertFalse(staging.exists())
        self.assertFalse((self.project / ".agent/work/T-1/one.json").exists())
        self.assertEqual(transaction.rollback("same decision")["status"], "ROLLED_BACK")

    def test_recovery_finishes_a_partial_local_publish_after_a_crash(self) -> None:
        self._require_runtime_transaction()
        transaction = self._new_transaction()
        staging = self.project / ".agent/runtime/staging" / transaction.operation_id
        transaction.prepare(["work/T-1/one.json", "work/T-1/two.json"])
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"}, self._generic_artifact_schema())
        transaction.stage_json("work/T-1/two.json", {"revision": 1, "value": "two"}, self._generic_artifact_schema())

        target_two = (self.project / ".agent/work/T-1/two.json").resolve()
        original_replace = os.replace

        def crash_on_second_target(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
            if Path(destination).resolve() == target_two:
                raise OSError("simulated crash between target replacements")
            original_replace(source, destination)

        with patch.object(transaction_module.os, "replace", side_effect=crash_on_second_target):
            with self.assertRaisesRegex(OSError, "simulated crash"):
                transaction.commit()

        self.assertEqual(json.loads((self.project / ".agent/work/T-1/one.json").read_text(encoding="utf-8"))["value"], "one")
        self.assertFalse((self.project / ".agent/work/T-1/two.json").exists())
        self.assertTrue((staging / "work/T-1/two.json").is_file())

        recovered = recover_transactions(self.project)
        record = next(item for item in recovered if item["operation_id"] == transaction.operation_id)
        self.assertEqual(record["status"], "COMMITTED")
        self.assertEqual(record["evidence"]["classification"], "RECOVERED_COMMIT")
        self.assertEqual(json.loads((self.project / ".agent/work/T-1/two.json").read_text(encoding="utf-8"))["value"], "two")
        self.assertFalse(staging.exists())

    def test_replay_of_committed_transaction_is_idempotent(self) -> None:
        transaction = self._new_transaction(target_files=["work/T-1/one.json"])
        transaction.prepare(["work/T-1/one.json"])
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"}, self._generic_artifact_schema())
        first = transaction.commit()

        replay = self._new_transaction(target_files=["work/T-1/one.json"])
        self.assertEqual(replay.prepare(["work/T-1/one.json"]), first)
        self.assertEqual(replay.commit(), first)
        self.assertEqual(len((self.project / ".agent/runtime/transactions.jsonl").read_text(encoding="utf-8").splitlines()), 3)

    def test_committed_idempotency_key_rejects_changed_staged_content(self) -> None:
        transaction = self._new_transaction(target_files=["work/T-1/one.json"])
        transaction.prepare(["work/T-1/one.json"])
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"}, self._generic_artifact_schema())
        transaction.commit()

        replay = self._new_transaction(target_files=["work/T-1/one.json"])
        replay.prepare(["work/T-1/one.json"])
        with self.assertRaisesRegex(RuntimeError, "idempotency"):
            replay.stage_json("work/T-1/one.json", {"revision": 1, "value": "changed"}, self._generic_artifact_schema())

    def test_external_side_effect_crash_is_never_retried_automatically(self) -> None:
        self._require_runtime_transaction()
        transaction = self._new_transaction(
            operation_type="EMAIL",
            idempotency_key="email:T-1:1",
            target_files=["work/T-1/one.json"],
        )
        staging = self.project / ".agent/runtime/staging" / transaction.operation_id
        transaction.prepare(["work/T-1/one.json"])
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"}, self._generic_artifact_schema())
        target = (self.project / ".agent/work/T-1/one.json").resolve()
        original_replace = os.replace

        def crash_before_external_publish(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
            if Path(destination).resolve() == target:
                raise OSError("transport became uncertain")
            original_replace(source, destination)

        with patch.object(transaction_module.os, "replace", side_effect=crash_before_external_publish):
            with self.assertRaisesRegex(OSError, "transport became uncertain"):
                transaction.commit()

        recovered = recover_transactions(self.project)
        record = next(item for item in recovered if item["operation_id"] == transaction.operation_id)
        self.assertEqual(record["status"], "RECOVERY_PENDING")
        self.assertEqual(record["evidence"]["classification"], "AMBIGUOUS_EXTERNAL_SIDE_EFFECT")
        self.assertFalse(target.exists())
        self.assertTrue((staging / "work/T-1/one.json").is_file())

    def test_state_mutation_publishes_a_committed_transaction_manifest(self) -> None:
        queued = write_json(self.project / "queued.json", {"task_id": "T-1", "status": "QUEUED"})
        result = run_script("update_task_state.py", "--project-root", str(self.project), "--input", str(queued))
        self.assertEqual(result.returncode, 0, result.stderr)

        manifests = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (self.project / ".agent/runtime/transactions").glob("*.json")
            if not path.name.endswith(".commit.json")
        ]
        task_transactions = [item for item in manifests if item.get("operation_type") == "TASK_STATE"]
        self.assertEqual(len(task_transactions), 1)
        self.assertEqual(task_transactions[0]["status"], "COMMITTED")
        expected_operation_id = "OP-" + hashlib.sha256("task-state:T-1:1".encode("utf-8")).hexdigest()[:32]
        self.assertEqual(task_transactions[0]["operation_id"], expected_operation_id)

    def test_inspect_recovery_reconciles_transactions_and_reports_hash_evidence(self) -> None:
        self._require_runtime_transaction()
        transaction = self._new_transaction(target_files=["work/T-1/one.json"])
        staging = self.project / ".agent/runtime/staging" / transaction.operation_id
        transaction.prepare(["work/T-1/one.json"])
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"}, self._generic_artifact_schema())

        target = (self.project / ".agent/work/T-1/one.json").resolve()
        original_replace = os.replace

        def crash_before_target_publish(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
            if Path(destination).resolve() == target:
                raise OSError("simulated inspection recovery crash")
            original_replace(source, destination)

        with patch.object(transaction_module.os, "replace", side_effect=crash_before_target_publish):
            with self.assertRaisesRegex(OSError, "simulated inspection recovery crash"):
                transaction.commit()

        result = run_script("inspect_recovery.py", "--project-root", str(self.project), "--task-id", "T-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        transaction_results = output.get("transactions", [])
        self.assertEqual(len(transaction_results), 1)
        evidence = transaction_results[0]
        self.assertEqual(evidence["operation_id"], transaction.operation_id)
        self.assertEqual(evidence["idempotency_key"], "T-1:state:1")
        self.assertIn("target_paths", evidence)
        self.assertIn("previous_hashes", evidence)
        self.assertIn("target_hashes", evidence)
        self.assertEqual(evidence["classification"], "RECOVERED_COMMIT")

    def test_approval_and_event_are_published_as_one_transaction(self) -> None:
        approval = write_json(
            self.project / "approval.json",
            {
                "target_type": "TASK",
                "target_id": "T-1",
                "decision": "APPROVED",
                "approver": "primary-agent",
                "actor_type": "primary_agent",
                "actor_id": "primary-agent",
                "action": "TASK",
                "target_revision": 1,
                "target_hash": "a" * 64,
                "policy_version": "1",
                "issued_at": "2026-08-03T00:00:00Z",
                "expires_at": "2099-01-01T00:00:00Z",
                "evidence": "transaction event boundary",
            },
        )
        with patch.object(record_approval, "append_event_for_root", side_effect=AssertionError("event must be staged")):
            with patch.object(sys, "argv", ["record_approval.py", "--project-root", str(self.project), "--input", str(approval)]):
                self.assertEqual(record_approval.main(), 0)
        self.assertTrue((self.project / ".agent/approvals/TASK-T-1.json").is_file())
        self.assertIn("APPROVAL_RECORDED", (self.project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8"))

    def test_operation_and_event_are_published_as_one_transaction(self) -> None:
        operation = write_json(
            self.project / "operation.json",
            {"task_id": "T-1", "type": "OTHER", "status": "STARTED", "command": "verify"},
        )
        with patch.object(record_operation, "append_event_for_root", side_effect=AssertionError("event must be staged")):
            with patch.object(sys, "argv", ["record_operation.py", "--project-root", str(self.project), "--input", str(operation)]):
                self.assertEqual(record_operation.main(), 0)
        self.assertTrue((self.project / ".agent/work/T-1/operations.jsonl").is_file())
        self.assertIn("OPERATION_RECORDED", (self.project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8"))

    def test_commit_batch_does_not_publish_operation_without_its_event(self) -> None:
        batch_id = "B-COMMIT"
        write_json(
            self.project / f".agent/work/{batch_id}/review.json",
            {"batch_id": batch_id, "revision": 1, "legacy_migration": True},
        )
        operation_path = self.project / f".agent/work/{batch_id}/operations.jsonl"
        events_path = self.project / ".agent/runtime/events.jsonl"
        events_before = events_path.read_text(encoding="utf-8")
        original_stage_text = commit_batch.RuntimeTransaction.stage_text
        stage_calls = 0

        def fail_between_operation_and_event(transaction, relative_path, content):
            nonlocal stage_calls
            stage_calls += 1
            if stage_calls == 2:
                raise OSError("injected commit-batch event staging failure")
            return original_stage_text(transaction, relative_path, content)

        with patch.object(commit_batch, "validate_batch_review_artifact"), patch.object(
            commit_batch, "validate_batch_review_semantics"
        ), patch.object(commit_batch, "require_persisted_approval"), patch.object(
            commit_batch, "validate_commit_authorization", return_value="APR-B-COMMIT"
        ), patch.object(commit_batch, "_used_approval", return_value=False), patch.object(
            commit_batch.RuntimeTransaction, "stage_text", autospec=True, side_effect=fail_between_operation_and_event
        ):
            with self.assertRaisesRegex(OSError, "event staging failure"):
                commit_batch.commit_batch(
                    self.project,
                    batch_id,
                    {},
                    actor={"actor_type": "user", "actor_id": "alice"},
                    paths=["src/app.py"],
                    message="commit batch",
                    dry_run=True,
                )

        self.assertEqual(stage_calls, 2)
        self.assertFalse(operation_path.is_file())
        self.assertEqual(events_path.read_text(encoding="utf-8"), events_before)

    def test_merge_holds_runtime_lock_during_authorization_snapshot(self) -> None:
        project, manager, entry, approval = self._merge_conflict_fixture(conflict=False)
        observed: list[bool] = []
        original_target_builder = merge_worktree.build_merge_authorization_target

        def inspect_lock(*args, **kwargs):
            contention: list[bool] = []

            def probe() -> None:
                try:
                    with runtime_lock(project):
                        contention.append(False)
                except RuntimeLockedError:
                    contention.append(True)

            thread = threading.Thread(target=probe)
            thread.start()
            thread.join(timeout=5)
            observed.extend(contention)
            return original_target_builder(*args, **kwargs)

        try:
            with patch.object(merge_worktree, "build_merge_authorization_target", side_effect=inspect_lock):
                merge_worktree.merge_worktree(
                    project,
                    Path(self.directory.name) / "merge-worktrees",
                    "TASK-MERGE",
                    1,
                    "main",
                    approval=approval,
                    actor="user-1",
                    actor_type="user",
                )
            self.assertEqual(observed, [True])
        finally:
            if manager.get("TASK-MERGE", 1).get("status") != "MERGED":
                manager.release_lease("TASK-MERGE", 1)

    def test_merge_stage_failure_does_not_publish_registry_or_conflict_artifact(self) -> None:
        project, manager, entry, approval = self._merge_conflict_fixture()
        metadata_before = manager.metadata_path.read_bytes()
        recovery_before = sorted(manager.recovery_root.glob("RECOVERY_PENDING-TASK-MERGE-*.json"))
        try:
            with patch.object(
                merge_worktree.RuntimeTransaction,
                "stage_text",
                autospec=True,
                side_effect=OSError("injected merge artifact staging failure"),
            ):
                with self.assertRaisesRegex(OSError, "merge artifact staging failure"):
                    merge_worktree.merge_worktree(
                        project,
                        Path(self.directory.name) / "merge-worktrees",
                        "TASK-MERGE",
                        1,
                        "main",
                        approval=approval,
                        actor="user-1",
                        actor_type="user",
                    )
            self.assertEqual(manager.metadata_path.read_bytes(), metadata_before)
            self.assertEqual(sorted(manager.recovery_root.glob("RECOVERY_PENDING-TASK-MERGE-*.json")), recovery_before)
            self.assertFalse(any((project / ".agent/recovery").glob("RECOVERY_PENDING-TASK-MERGE-*.json")))
        finally:
            if manager.get("TASK-MERGE", 1).get("status") != "MERGED":
                manager.release_lease("TASK-MERGE", 1)

    def test_merge_after_git_success_failure_persists_recovery_evidence(self) -> None:
        project, manager, entry, approval = self._merge_conflict_fixture(conflict=False)
        metadata_before = manager.metadata_path.read_bytes()

        def fail_registry_update(manager_instance, task_id, revision, updates):
            metadata_files = sorted((project / ".agent/recovery").glob("merge-metadata-TASK-MERGE-1.json"))
            self.assertEqual(len(metadata_files), 1)
            evidence = json.loads(metadata_files[0].read_text(encoding="utf-8"))
            self.assertIn("registry_snapshot", evidence)
            self.assertIn("before", evidence["registry_snapshot"])
            self.assertIn("before_hash", evidence["registry_snapshot"])
            raise OSError("injected registry update failure")

        try:
            with patch.object(
                WorktreeManager,
                "_set_entry_locked",
                autospec=True,
                side_effect=fail_registry_update,
            ):
                with self.assertRaisesRegex(OSError, "injected registry update failure"):
                    merge_worktree.merge_worktree(
                        project,
                        Path(self.directory.name) / "merge-worktrees",
                        "TASK-MERGE",
                        1,
                        "main",
                        approval=approval,
                        actor="user-1",
                        actor_type="user",
                    )

            merged_content = subprocess.run(
                ["git", "show", "HEAD:value.txt"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(merged_content, "task change")
            registry_after = manager.get("TASK-MERGE", 1)
            self.assertIn(registry_after["status"], {"ACTIVE", "RECOVERY_PENDING"})
            if registry_after["status"] == "ACTIVE":
                self.assertEqual(manager.metadata_path.read_bytes(), metadata_before)
            recovery_artifacts = sorted((project / ".agent/recovery").glob("*TASK-MERGE-1*.json"))
            self.assertTrue(recovery_artifacts)
            evidence = next(
                json.loads(path.read_text(encoding="utf-8"))
                for path in recovery_artifacts
                if path.name.startswith("merge-metadata-")
            )
            self.assertIn("registry_snapshot", evidence)
            self.assertIn("before", evidence["registry_snapshot"])
            self.assertIn("before_hash", evidence["registry_snapshot"])
            self.assertEqual(evidence["status"], "RECOVERY_PENDING")
            manifests = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (project / ".agent/runtime/transactions").glob("*.json")
                if not path.name.endswith(".commit.json") and not path.name.endswith(".rollback.json")
            ]
            merge_manifests = [item for item in manifests if item.get("operation_type") == "MERGE_WORKTREE"]
            self.assertTrue(merge_manifests)
            self.assertTrue(any(item.get("status") == "RECOVERY_PENDING" for item in merge_manifests))
        finally:
            if manager.get("TASK-MERGE", 1).get("status") != "MERGED":
                manager.release_lease("TASK-MERGE", 1)

    def test_inspect_recovery_reports_transaction_errors_as_structured_output(self) -> None:
        output = StringIO()
        with patch.object(inspect_recovery, "recover_transactions", side_effect=TransactionError("manifest is corrupt")):
            with patch.object(sys, "argv", ["inspect_recovery.py", "--project-root", str(self.project), "--task-id", "T-1"]):
                with redirect_stdout(output):
                    result = inspect_recovery.main()
        self.assertEqual(result, 1)
        value = json.loads(output.getvalue())
        self.assertEqual(value["classification"], "RECOVERY_PENDING")
        self.assertEqual(value["error_type"], "TransactionError")
        self.assertIn("manifest is corrupt", value["error"])

    def test_inspect_recovery_does_not_split_reconciliation_and_event_publication(self) -> None:
        events_path = self.project / ".agent/runtime/events.jsonl"
        recovery_state_path = self.project / ".agent/recovery/recovery-state.json"
        reconciliation_path = self.project / ".agent/recovery/reconciliation-T-1.json"
        events_before = events_path.read_bytes()
        recovery_state_before = recovery_state_path.read_bytes()
        original_stage_text = transaction_module.RuntimeTransaction.stage_text

        def fail_event_staging(transaction, relative_path, content):
            if relative_path == "runtime/events.jsonl":
                raise OSError("injected recovery event staging failure")
            return original_stage_text(transaction, relative_path, content)

        output = StringIO()
        with patch.object(
            transaction_module.RuntimeTransaction,
            "stage_text",
            autospec=True,
            side_effect=fail_event_staging,
        ):
            with patch.object(sys, "argv", ["inspect_recovery.py", "--project-root", str(self.project), "--task-id", "T-1"]):
                with redirect_stdout(output):
                    result = inspect_recovery.main()

        self.assertEqual(result, 1)
        failure = json.loads(output.getvalue())
        self.assertEqual(failure["classification"], "RECOVERY_PENDING")
        self.assertIn("persistence_error", failure)
        self.assertIn("injected recovery event staging failure", failure["persistence_error"])
        self.assertEqual(events_path.read_bytes(), events_before)
        self.assertEqual(recovery_state_path.read_bytes(), recovery_state_before)
        self.assertFalse(reconciliation_path.exists())

    def test_review_event_staging_failure_does_not_publish_review_or_task_state(self) -> None:
        write_json(
            self.project / ".agent/work/T-1/task-state.json",
            {"task_id": "T-1", "status": "COMPLETED", "revision": 1},
        )
        (self.project / ".agent/runtime/events.jsonl").write_text(
            json.dumps(
                {
                    "event_id": "EVT-000001",
                    "timestamp": "2026-08-04T00:00:00Z",
                    "type": "TASK_COMPLETED",
                    "actor": "executor",
                    "task_id": "T-1",
                    "data": {"task_revision": 1},
                },
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        review = write_json(
            self.project / "review.json",
            {
                "task_id": "T-1",
                "legacy_migration": True,
                "criteria": [{"id": "C-1", "score": 4, "weight": 1, "evidence": "verified"}],
                "findings": [],
                "hard_fail": False,
                "pass_threshold_percent": 85,
            },
        )
        with patch.object(create_review.RuntimeTransaction, "stage_text", side_effect=OSError("event staging failed")):
            with patch.object(sys, "argv", ["create_review.py", "--project-root", str(self.project), "--input", str(review)]):
                result = create_review.main()
        self.assertEqual(result, 1)
        self.assertFalse((self.project / ".agent/work/T-1/review.json").exists())
        self.assertEqual(
            json.loads((self.project / ".agent/work/T-1/task-state.json").read_text(encoding="utf-8"))["status"],
            "COMPLETED",
        )
        self.assertNotIn("REVIEW_CREATED", (self.project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8"))

    def test_terminal_cleanup_event_failure_is_structured_and_not_silent(self) -> None:
        write_json(
            self.project / ".agent/work/T-1/task-state.json",
            {"task_id": "T-1", "status": "COMPLETED", "revision": 1},
        )
        write_json(
            self.project / ".agent/work/T-1/lease.json",
            {"task_id": "T-1", "run_id": "RUN-CLEANUP"},
        )
        review = write_json(
            self.project / "cleanup-review.json",
            {
                "task_id": "T-1",
                "legacy_migration": True,
                "criteria": [{"id": "C-1", "score": 4, "weight": 1, "evidence": "verified"}],
                "findings": [],
                "hard_fail": False,
                "pass_threshold_percent": 85,
            },
        )
        events_path = self.project / ".agent/runtime/events.jsonl"
        events_path.write_text(
            json.dumps(
                {
                    "event_id": "EVT-000001",
                    "timestamp": "2026-08-04T00:00:00Z",
                    "type": "TASK_COMPLETED",
                    "actor": "executor",
                    "task_id": "T-1",
                    "data": {"task_revision": 1},
                },
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        original_stage_text = create_review.RuntimeTransaction.stage_text

        def fail_cleanup_event(transaction, relative_path, content):
            if transaction.operation_type == "TERMINAL_CLEANUP":
                raise OSError("injected cleanup event staging failure")
            return original_stage_text(transaction, relative_path, content)

        output = StringIO()
        with patch.object(
            create_review.RuntimeTransaction,
            "stage_text",
            autospec=True,
            side_effect=fail_cleanup_event,
        ):
            with patch.object(
                sys,
                "argv",
                ["create_review.py", "--project-root", str(self.project), "--input", str(review)],
            ):
                with redirect_stderr(output):
                    result = create_review.main()

        self.assertEqual(result, 1)
        failure = json.loads(output.getvalue())
        self.assertEqual(failure["classification"], "RECOVERY_PENDING")
        self.assertEqual(failure["operation_type"], "TERMINAL_CLEANUP")
        self.assertEqual(failure["error_type"], "OSError")
        self.assertEqual(failure["target_paths"], ["runtime/events.jsonl"])
        self.assertIn("injected cleanup event staging failure", failure["error"])
        events_after = events_path.read_text(encoding="utf-8")
        self.assertIn("REVIEW_CREATED", events_after)
        self.assertIn("TASK_ACCEPTED", events_after)
        self.assertNotIn("LEASE_RELEASED", events_after)
        self.assertFalse((self.project / ".agent/work/T-1/lease.json").exists())

    def test_batch_review_event_staging_failure_does_not_publish_review(self) -> None:
        write_json(
            self.project / ".agent/work/T-1/task-state.json",
            {"task_id": "T-1", "status": "ACCEPTED", "revision": 1},
        )
        write_json(
            self.project / ".agent/work/T-1/review.json",
            {"task_id": "T-1", "review_id": "REV-T-1", "verdict": "PASS"},
        )
        batch_review = write_json(
            self.project / "batch-review.json",
            {
                "batch_id": "B-1",
                "task_reviews": ["REV-T-1"],
                "integration_checks": [{"name": "integration", "result": "PASS", "evidence": "verified"}],
                "findings": [],
                "legacy_migration": True,
            },
        )
        with patch.object(create_batch_review.RuntimeTransaction, "stage_text", side_effect=OSError("event staging failed")):
            with patch.object(sys, "argv", ["create_batch_review.py", "--project-root", str(self.project), "--input", str(batch_review)]):
                result = create_batch_review.main()
        self.assertEqual(result, 1)
        self.assertFalse((self.project / ".agent/work/B-1/review.json").exists())
        self.assertNotIn("BATCH_REVIEW_CREATED", (self.project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8"))

    def test_dispatch_event_staging_failure_does_not_publish_dispatch_artifacts(self) -> None:
        task_id = "T-DISPATCH"
        task_path = self.project / f".agent/work/{task_id}/task-state.json"
        write_json(task_path, {"task_id": task_id, "status": "READY", "revision": 1, "depends_on": [], "write_scope": []})
        queue_path = self.project / ".agent/runtime/queue.json"
        graph_path = self.project / ".agent/runtime/graph.json"
        before_queue = queue_path.read_text(encoding="utf-8")
        before_graph = graph_path.read_text(encoding="utf-8")
        dispatch = {
            "task_id": task_id,
            "selected_mode": "SYNC",
            "selected_owner": "primary-agent",
            "dispatch_id": "DSP-DISPATCH",
            "input_revisions": {"task": 1, "queue": 0},
        }
        contract = {
            "project_profile": "personal",
            "profile_hash": "a" * 64,
            "task_type": "backend",
            "risk_flags": {},
            "review_type": "task",
            "rubric_id": "R-1",
            "rubric_version": "1",
            "rubric_hash": "b" * 64,
            "review_policy_version": "1",
        }
        with patch.object(dispatch_transaction, "validate_contract", return_value=contract):
            with patch.object(dispatch_transaction.RuntimeTransaction, "stage_text", side_effect=OSError("event staging failed")):
                with self.assertRaises(OSError):
                    dispatch_transaction.persist_dispatch(
                        self.project,
                        dispatch,
                        {"execution": {"async_execution_enabled": False, "max_parallel_tasks": 2}},
                        {},
                    )
        self.assertEqual(queue_path.read_text(encoding="utf-8"), before_queue)
        self.assertEqual(graph_path.read_text(encoding="utf-8"), before_graph)
        self.assertEqual(task_path.read_text(encoding="utf-8"), json.dumps({"task_id": task_id, "status": "READY", "revision": 1, "depends_on": [], "write_scope": []}))
        self.assertFalse((self.project / f".agent/work/{task_id}/lease.json").exists())
        self.assertFalse((self.project / f".agent/work/{task_id}/operations.jsonl").exists())
        self.assertNotIn("TASK_QUEUED_SYNC", (self.project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8"))

    def test_task_state_event_staging_failure_does_not_publish_state(self) -> None:
        task_state = self.project / "task-state.json"
        write_json(task_state, {"task_id": "T-STATE", "status": "READY"})
        with patch.object(update_task_state.RuntimeTransaction, "stage_text", side_effect=OSError("event staging failed")):
            with patch.object(sys, "argv", ["update_task_state.py", "--project-root", str(self.project), "--input", str(task_state)]):
                result = update_task_state.main()
        self.assertEqual(result, 1)
        self.assertFalse((self.project / ".agent/work/T-STATE/task-state.json").exists())
        self.assertNotIn("TASK_READY", (self.project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
