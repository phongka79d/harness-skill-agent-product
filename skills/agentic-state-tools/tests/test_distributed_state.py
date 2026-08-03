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
from validate_payload import validate  # noqa: E402


BASE_TIME = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


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
