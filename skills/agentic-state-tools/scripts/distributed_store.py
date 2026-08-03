"""Backend-neutral remote-state contracts and a file-backed reference adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol

from runtime_utils import apply_event, empty_state, iter_events, validate_event
from validate_payload import validate


SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
SNAPSHOT_SCHEMA = SCHEMA_ROOT / "remote-snapshot.schema.json"
LOCK_SCHEMA = SCHEMA_ROOT / "distributed-lock.schema.json"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def etag(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


class StoreError(RuntimeError):
    classification = "NEEDS_RECONCILIATION"

    def __init__(self, message: str, *, operation_id: str | None = None, **details: Any) -> None:
        super().__init__(message)
        self.operation_id = operation_id or f"OP-{uuid.uuid4().hex[:16].upper()}"
        self.details = details

    def to_record(self) -> dict[str, Any]:
        record = {
            "error_id": f"ERR-{self.operation_id}",
            "classification": self.classification,
            "message": str(self),
            "operation_id": self.operation_id,
        }
        record.update(self.details)
        return record


class RevisionConflict(StoreError):
    classification = "REVISION_CONFLICT"


class EventConflict(StoreError):
    classification = "EVENT_CONFLICT"


class OwnershipConflict(StoreError):
    classification = "OWNERSHIP_CONFLICT"


class NetworkUncertain(StoreError):
    classification = "NETWORK_UNCERTAIN"

    def __init__(self, message: str, *, operation_id: str, reconcile_path: str) -> None:
        super().__init__(message, operation_id=operation_id, reconcile_path=reconcile_path)
        self.reconcile_path = reconcile_path


class ReconciliationRequired(StoreError):
    classification = "NEEDS_RECONCILIATION"


class StoreBusy(StoreError):
    classification = "STORE_BUSY"


class StateStore(Protocol):
    def read_snapshot(self) -> dict[str, Any]: ...

    def append_event(self, event: dict[str, Any], *, expected_revision: int, expected_etag: str) -> dict[str, Any]: ...


def write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReconciliationRequired(f"{label} is unreadable") from exc


class FileStateStore:
    """Remote-style store with atomic local files for deterministic tests."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.runtime = self.root / "runtime"
        self.locks = self.root / "locks"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        if not (self.runtime / "events.jsonl").exists():
            (self.runtime / "events.jsonl").write_text("", encoding="utf-8")
        if not (self.runtime / "state.json").exists():
            write_atomic(self.runtime / "state.json", empty_state())
        if not (self.runtime / "idempotency.json").exists():
            write_atomic(self.runtime / "idempotency.json", {})
        if not (self.runtime / "fencing-sequence.json").exists():
            write_atomic(self.runtime / "fencing-sequence.json", {"next": 1})

    @contextmanager
    def _mutation_lock(self) -> Iterator[None]:
        lock_path = self.root / ".store.lock"
        try:
            descriptor = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError as exc:
            raise StoreBusy("remote store is busy") from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"pid": os.getpid(), "acquired_at": timestamp()}, handle)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            yield
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def read_snapshot(self) -> dict[str, Any]:
        state = read_json(self.runtime / "state.json", "state snapshot")
        if not isinstance(state, dict):
            raise ReconciliationRequired("state snapshot must be an object")
        try:
            events = iter_events(self.runtime / "events.jsonl")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ReconciliationRequired("event journal is invalid") from exc
        event_ids = [event.get("event_id") for event in events]
        if len(event_ids) != len(set(event_ids)):
            raise ReconciliationRequired("event journal contains duplicate event IDs")
        revision = state.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision != len(events):
            raise ReconciliationRequired("state revision does not match event journal")
        rebuilt = empty_state()
        for event in events:
            rebuilt = apply_event(rebuilt, event)
        if not events:
            rebuilt["updated_at"] = state.get("updated_at")
        if state != rebuilt:
            raise ReconciliationRequired("state snapshot does not match replayed event journal")
        snapshot = {
            "schema_version": 1,
            "revision": revision,
            "etag": etag(state),
            "state": state,
            "events": events,
        }
        errors = validate(snapshot, json.loads(SNAPSHOT_SCHEMA.read_text(encoding="utf-8")))
        if errors:
            raise ReconciliationRequired("snapshot schema is invalid")
        return snapshot

    def _idempotency(self) -> dict[str, Any]:
        value = read_json(self.runtime / "idempotency.json", "idempotency ledger")
        if not isinstance(value, dict):
            raise ReconciliationRequired("idempotency ledger must be an object")
        return value

    def append_event(self, event: dict[str, Any], *, expected_revision: int, expected_etag: str) -> dict[str, Any]:
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        if not isinstance(expected_etag, str) or len(expected_etag) != 64:
            raise ValueError("expected_etag must be a SHA-256 hex digest")
        validate_event(event)
        event_id = event["event_id"]
        with self._mutation_lock():
            idempotency = self._idempotency()
            saved = idempotency.get(event_id)
            if saved is not None:
                if saved.get("event") != event:
                    raise EventConflict(f"event ID already has different content: {event_id}")
                return saved["result"]
            current = self.read_snapshot()
            for existing in current["events"]:
                if existing.get("event_id") == event_id:
                    if existing != event:
                        raise EventConflict(f"event ID already has different content: {event_id}")
                    raise ReconciliationRequired(f"event {event_id} exists without an idempotency result")
            if current["revision"] != expected_revision or current["etag"] != expected_etag:
                raise RevisionConflict(
                    "remote snapshot is newer than the mutation input",
                    expected_revision=expected_revision,
                    current_revision=current["revision"],
                    expected_etag=expected_etag,
                    current_etag=current["etag"],
                )
            record = dict(event)
            event_path = self.runtime / "events.jsonl"
            with event_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            next_state = apply_event(current["state"], record)
            write_atomic(self.runtime / "state.json", next_state)
            result = {"event": record, "revision": next_state["revision"], "etag": etag(next_state), "state": next_state}
            idempotency[event_id] = {"event": record, "result": result}
            write_atomic(self.runtime / "idempotency.json", idempotency)
            return result

    def _next_fencing_token(self) -> int:
        sequence = read_json(self.runtime / "fencing-sequence.json", "fencing sequence")
        if not isinstance(sequence, dict) or not isinstance(sequence.get("next"), int) or sequence["next"] < 1:
            raise ReconciliationRequired("fencing sequence is invalid")
        token = sequence["next"]
        sequence["next"] = token + 1
        write_atomic(self.runtime / "fencing-sequence.json", sequence)
        return token

    def _lock_path(self, kind: str, key: str) -> Path:
        digest = hashlib.sha256(f"{kind}:{key}".encode("utf-8")).hexdigest()[:24]
        return self.locks / f"{kind}-{digest}.json"

    def _read_lock(self, path: Path) -> dict[str, Any]:
        value = read_json(path, "distributed lock")
        if not isinstance(value, dict):
            raise ReconciliationRequired("distributed lock must be an object")
        errors = validate(value, json.loads(LOCK_SCHEMA.read_text(encoding="utf-8")))
        if errors:
            raise ReconciliationRequired("distributed lock schema is invalid")
        return value

    def acquire_lock(
        self,
        kind: str,
        key: str,
        owner_id: str,
        run_id: str,
        lease_seconds: int,
        *,
        now: datetime | None = None,
        reclaim_expired: bool = False,
    ) -> dict[str, Any]:
        if kind not in {"task", "file", "resource"}:
            raise ValueError("lock kind is invalid")
        if not all(isinstance(value, str) and value.strip() for value in (key, owner_id, run_id)):
            raise ValueError("lock key, owner_id, and run_id must be non-empty strings")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds <= 0:
            raise ValueError("lease_seconds must be a positive integer")
        current_time = now or datetime.now(timezone.utc)
        path = self._lock_path(kind, key)
        with self._mutation_lock():
            old: dict[str, Any] | None = None
            if path.is_file():
                old = self._read_lock(path)
                if parse_time(old["expires_at"]) > current_time:
                    raise OwnershipConflict(f"lock is held: {kind}:{key}")
                if not reclaim_expired:
                    raise OwnershipConflict("lock expired; explicit reclaim is required")
            acquired = timestamp(current_time)
            record = {
                "lock_id": f"LOCK-{kind.upper()}-{uuid.uuid4().hex[:12].upper()}",
                "kind": kind,
                "key": key,
                "owner_id": owner_id,
                "run_id": run_id,
                "fencing_token": self._next_fencing_token(),
                "acquired_at": acquired,
                "last_heartbeat": acquired,
                "expires_at": timestamp(current_time + timedelta(seconds=lease_seconds)),
                "lease_seconds": lease_seconds,
                "reclaimed_from": old["lock_id"] if old else None,
            }
            errors = validate(record, json.loads(LOCK_SCHEMA.read_text(encoding="utf-8")))
            if errors:
                raise ValueError("distributed lock schema is invalid")
            write_atomic(path, record)
            return record

    def _find_lock(self, lock_id: str) -> tuple[Path, dict[str, Any]]:
        for path in sorted(self.locks.glob("*.json")):
            record = self._read_lock(path)
            if record["lock_id"] == lock_id:
                return path, record
        raise OwnershipConflict(f"lock does not exist: {lock_id}")

    @staticmethod
    def _assert_owner(record: dict[str, Any], owner_id: str, run_id: str, fencing_token: int) -> None:
        if (record["owner_id"], record["run_id"], record["fencing_token"]) != (owner_id, run_id, fencing_token):
            raise OwnershipConflict("lock owner or fencing token does not match")

    def heartbeat(
        self,
        lock_id: str,
        owner_id: str,
        run_id: str,
        fencing_token: int,
        lease_seconds: int,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current_time = now or datetime.now(timezone.utc)
        with self._mutation_lock():
            path, record = self._find_lock(lock_id)
            self._assert_owner(record, owner_id, run_id, fencing_token)
            if parse_time(record["expires_at"]) <= current_time:
                raise OwnershipConflict("lock lease has expired")
            record["last_heartbeat"] = timestamp(current_time)
            record["lease_seconds"] = lease_seconds
            record["expires_at"] = timestamp(current_time + timedelta(seconds=lease_seconds))
            write_atomic(path, record)
            return record

    def release_lock(self, lock_id: str, owner_id: str, run_id: str, fencing_token: int) -> None:
        with self._mutation_lock():
            path, record = self._find_lock(lock_id)
            self._assert_owner(record, owner_id, run_id, fencing_token)
            path.unlink()

    def list_locks(self) -> list[dict[str, Any]]:
        return [self._read_lock(path) for path in sorted(self.locks.glob("*.json"))]

    def validate_fencing_token(
        self,
        kind: str,
        key: str,
        owner_id: str,
        run_id: str,
        fencing_token: int,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Prove that a remote owner still holds the current live fence."""

        path = self._lock_path(kind, key)
        if not path.is_file():
            raise OwnershipConflict(f"lock does not exist: {kind}:{key}")
        record = self._read_lock(path)
        self._assert_owner(record, owner_id, run_id, fencing_token)
        current_time = now or datetime.now(timezone.utc)
        if parse_time(record["expires_at"]) <= current_time:
            raise OwnershipConflict("lock lease has expired")
        return record


class Transport(Protocol):
    def request(self, method: str, path: str, body: dict[str, Any] | None, headers: dict[str, str]) -> Any: ...


class JsonHttpTransport:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, body: dict[str, Any] | None, headers: dict[str, str]) -> Any:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(f"{self.base_url}{path}", data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body_value = json.loads(exc.read().decode("utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                body_value = {"message": "remote HTTP error", "classification": "NEEDS_RECONCILIATION"}
            if not isinstance(body_value, dict):
                body_value = {"message": "remote HTTP error", "classification": "NEEDS_RECONCILIATION"}
            return {"error": body_value}


class RemoteStateClient:
    def __init__(self, base_url: str, transport: Transport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport or JsonHttpTransport(self.base_url)

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None, *, mutation: bool = False, expected_etag: str | None = None) -> Any:
        operation_id = f"OP-{uuid.uuid4().hex[:16].upper()}"
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if mutation:
            headers["Idempotency-Key"] = operation_id
        if expected_etag is not None:
            headers["If-Match"] = expected_etag
        try:
            response = self.transport.request(method, path, body, headers)
        except (TimeoutError, ConnectionError, OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeError) as exc:
            raise NetworkUncertain(
                "remote mutation outcome is unknown; reconcile before retrying",
                operation_id=operation_id,
                reconcile_path=f"{self.base_url}/operations/{operation_id}",
            ) from exc
        if not isinstance(response, dict):
            raise NetworkUncertain(
                "remote response is not a JSON object",
                operation_id=operation_id,
                reconcile_path=f"{self.base_url}/operations/{operation_id}",
            )
        remote_error = response.get("error")
        if isinstance(remote_error, dict):
            classification = remote_error.get("classification") or "NEEDS_RECONCILIATION"
            message = str(remote_error.get("message") or "remote request was rejected")
            if classification == "NETWORK_UNCERTAIN":
                raise NetworkUncertain(
                    message,
                    operation_id=operation_id,
                    reconcile_path=str(remote_error.get("reconcile_path") or f"{self.base_url}/operations/{operation_id}"),
                )
            error_type = {
                "REVISION_CONFLICT": RevisionConflict,
                "EVENT_CONFLICT": EventConflict,
                "OWNERSHIP_CONFLICT": OwnershipConflict,
                "NEEDS_RECONCILIATION": ReconciliationRequired,
                "STORE_BUSY": StoreBusy,
            }.get(classification)
            if error_type is not None:
                details = {key: value for key, value in remote_error.items() if key not in {"message", "classification", "operation_id", "error_id"}}
                raise error_type(message, operation_id=operation_id, **details)
        return response

    def read_snapshot(self) -> dict[str, Any]:
        return self._request("GET", "/snapshot")

    def append_event(self, event: dict[str, Any], *, expected_revision: int, expected_etag: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/events",
            {"event": event, "expected_revision": expected_revision, "expected_etag": expected_etag},
            mutation=True,
            expected_etag=expected_etag,
        )

    def acquire_lock(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/locks/acquire", payload, mutation=True)

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/locks/heartbeat", payload, mutation=True)

    def release_lock(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/locks/release", payload, mutation=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--store-root", required=True)
    append_parser = subparsers.add_parser("append-event")
    append_parser.add_argument("--store-root", required=True)
    append_parser.add_argument("--input", required=True)
    append_parser.add_argument("--expected-revision", required=True, type=int)
    append_parser.add_argument("--expected-etag", required=True)
    args = parser.parse_args()
    try:
        store = FileStateStore(args.store_root)
        if args.command == "snapshot":
            print(json.dumps(store.read_snapshot(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = store.append_event(payload, expected_revision=args.expected_revision, expected_etag=args.expected_etag)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except StoreError as exc:
        print(f"REMOTE_REJECTED: {exc.classification}: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"REMOTE_REJECTED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
