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

    def _require_runtime_transaction(self) -> None:
        if RuntimeTransaction is None or recover_transactions is None or transaction_module is None:
            self.fail("runtime_transaction.py does not expose the transaction API")

    def _new_transaction(
        self,
        operation_id: str = "OP-T-1-1",
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
            operation_id,
            operation_type,
            idempotency_key,
            expected_revisions or {target: 0 for target in targets},
            targets,
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
        first = self._new_core_transaction()
        first_record = first.prepare(["work/T-1/one.json"])
        self.assertRegex(first_record["operation_id"], r"^OP-[A-Za-z0-9._-]+$")
        second = self._new_core_transaction()
        self.assertEqual(second.prepare(["work/T-1/one.json"])["operation_id"], first_record["operation_id"])

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
            expected_revisions={str(self.project / "outside.json"): 0},
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

        prepared = transaction.prepare()
        self.assertEqual(prepared["status"], "PREPARED")
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"})
        transaction.stage_json("work/T-1/two.json", {"revision": 1, "value": "two"})

        staging = self.project / ".agent/runtime/staging/OP-T-1-1"
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

        with self.assertRaisesRegex(ValueError, "stale revision"):
            transaction.prepare()

        self.assertFalse((self.project / ".agent/runtime/staging/OP-T-1-1").exists())
        self.assertFalse((self.project / ".agent/runtime/transactions/OP-T-1-1.json").exists())

    def test_rollback_removes_staged_files_and_is_idempotent(self) -> None:
        transaction = self._new_transaction()
        transaction.prepare()
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"})

        rolled_back = transaction.rollback("validation failed")
        self.assertEqual(rolled_back["status"], "ROLLED_BACK")
        self.assertEqual(rolled_back["rollback_reason"], "validation failed")
        self.assertFalse((self.project / ".agent/runtime/staging/OP-T-1-1").exists())
        self.assertFalse((self.project / ".agent/work/T-1/one.json").exists())
        self.assertEqual(transaction.rollback("same decision")["status"], "ROLLED_BACK")

    def test_recovery_finishes_a_partial_local_publish_after_a_crash(self) -> None:
        self._require_runtime_transaction()
        transaction = self._new_transaction()
        transaction.prepare()
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"})
        transaction.stage_json("work/T-1/two.json", {"revision": 1, "value": "two"})

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
        self.assertTrue((self.project / ".agent/runtime/staging/OP-T-1-1/work/T-1/two.json").is_file())

        recovered = recover_transactions(self.project)
        record = next(item for item in recovered if item["operation_id"] == "OP-T-1-1")
        self.assertEqual(record["status"], "COMMITTED")
        self.assertEqual(record["evidence"]["classification"], "RECOVERED_COMMIT")
        self.assertEqual(json.loads((self.project / ".agent/work/T-1/two.json").read_text(encoding="utf-8"))["value"], "two")
        self.assertFalse((self.project / ".agent/runtime/staging/OP-T-1-1").exists())

    def test_replay_of_committed_transaction_is_idempotent(self) -> None:
        transaction = self._new_transaction(target_files=["work/T-1/one.json"])
        transaction.prepare()
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"})
        first = transaction.commit()

        replay = self._new_transaction(target_files=["work/T-1/one.json"])
        self.assertEqual(replay.prepare(), first)
        self.assertEqual(replay.commit(), first)
        self.assertEqual(len((self.project / ".agent/runtime/transactions.jsonl").read_text(encoding="utf-8").splitlines()), 3)

    def test_committed_idempotency_key_rejects_changed_staged_content(self) -> None:
        transaction = self._new_transaction(target_files=["work/T-1/one.json"])
        transaction.prepare()
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"})
        transaction.commit()

        replay = self._new_transaction(target_files=["work/T-1/one.json"])
        replay.prepare()
        with self.assertRaisesRegex(RuntimeError, "idempotency"):
            replay.stage_json("work/T-1/one.json", {"revision": 1, "value": "changed"})

    def test_external_side_effect_crash_is_never_retried_automatically(self) -> None:
        self._require_runtime_transaction()
        transaction = self._new_transaction(
            operation_id="OP-T-1-EXTERNAL",
            operation_type="EMAIL",
            idempotency_key="email:T-1:1",
            target_files=["work/T-1/one.json"],
        )
        transaction.prepare()
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"})
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
        record = next(item for item in recovered if item["operation_id"] == "OP-T-1-EXTERNAL")
        self.assertEqual(record["status"], "RECOVERY_PENDING")
        self.assertEqual(record["evidence"]["classification"], "AMBIGUOUS_EXTERNAL_SIDE_EFFECT")
        self.assertFalse(target.exists())
        self.assertTrue((self.project / ".agent/runtime/staging/OP-T-1-EXTERNAL/work/T-1/one.json").is_file())

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

    def test_inspect_recovery_reconciles_transactions_and_reports_hash_evidence(self) -> None:
        self._require_runtime_transaction()
        transaction = self._new_transaction(target_files=["work/T-1/one.json"])
        transaction.prepare()
        transaction.stage_json("work/T-1/one.json", {"revision": 1, "value": "one"})

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
        self.assertEqual(evidence["operation_id"], "OP-T-1-1")
        self.assertEqual(evidence["idempotency_key"], "T-1:state:1")
        self.assertIn("target_paths", evidence)
        self.assertIn("previous_hashes", evidence)
        self.assertIn("target_hashes", evidence)
        self.assertEqual(evidence["classification"], "RECOVERED_COMMIT")


if __name__ == "__main__":
    unittest.main()
