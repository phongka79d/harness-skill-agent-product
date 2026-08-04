"""Durable multi-file publication and crash recovery for runtime artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from runtime_utils import (
    append_jsonl,
    ensure_runtime_initialized,
    project_path,
    read_json,
    read_object,
    runtime_lock,
    utc_now,
)
from validate_payload import validate


ROOT = Path(__file__).resolve().parents[1]
TRANSACTION_SCHEMA = ROOT / "schemas/transaction.schema.json"
TERMINAL_STATUSES = {"COMMITTED", "ROLLED_BACK"}
NON_TERMINAL_STATUSES = {"PREPARED", "APPLYING", "RECOVERY_PENDING"}
EXTERNAL_OPERATION_TYPES = {
    "DATABASE_MIGRATION",
    "EMAIL",
    "EXTERNAL_RESOURCE",
    "PUSH",
    "DEPLOY",
    "DELETE",
    "DEPENDENCY_INSTALL",
    "SCHEMA_CHANGE",
    "MERGE_WORKTREE",
    "WORKTREE_MERGE",
}


class TransactionError(RuntimeError):
    """Raised when a transaction cannot be safely advanced."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return None


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _write_json_durable(path: Path, value: Any) -> None:
    _write_bytes_atomic(path, _json_bytes(value))


def _normalize_relative(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must contain non-empty paths")
    normalized = value.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"{field} must be a relative path")
    parts = normalized.split("/")
    if not normalized or normalized == "." or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{field} must not contain traversal")
    return "/".join(parts)


def _contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _canonical_target(project: Path, value: str, *, field: str = "target path") -> tuple[str, Path]:
    agent = (project / ".agent").resolve()
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
        if _contained(resolved, agent) and resolved != agent:
            return resolved.relative_to(agent).as_posix(), resolved
        if _contained(resolved, project) and resolved != project:
            return f"project/{resolved.relative_to(project).as_posix()}", resolved
        raise ValueError(f"{field} must remain inside the project root")

    normalized = _normalize_relative(value, field=field)
    if normalized == ".agent" or normalized.startswith(".agent/"):
        normalized = normalized.removeprefix(".agent/")
        normalized = _normalize_relative(normalized, field=field)
    if normalized.startswith("project/"):
        relative = _normalize_relative(normalized[len("project/"):], field=field)
        resolved = (project / relative).resolve(strict=False)
        if not _contained(resolved, project) or resolved == project:
            raise ValueError(f"{field} must remain inside the project root")
        return f"project/{relative}", resolved

    resolved = (agent / normalized).resolve(strict=False)
    if not _contained(resolved, agent) or resolved == agent:
        raise ValueError(f"{field} must remain inside project/.agent")
    return normalized, resolved


def _target_from_manifest(project: Path, value: str) -> Path:
    canonical, resolved = _canonical_target(project, value, field="target path")
    if canonical != value:
        raise ValueError("manifest target path is not canonical")
    return resolved


def _safe_agent_path(root: Path, value: str, *, field: str) -> Path:
    normalized = _normalize_relative(value, field=field)
    resolved = (root / normalized).resolve(strict=False)
    if not _contained(resolved, root) or resolved == root:
        raise TransactionError(f"{field} escapes project/.agent")
    return resolved


def _staging_relative(operation_id: str, target_path: str) -> str:
    return (Path("runtime") / "staging" / operation_id / target_path).as_posix()


def _manifest_path(root: Path, operation_id: str) -> Path:
    return root / "runtime" / "transactions" / f"{operation_id}.json"


def _transaction_ledger_path(root: Path) -> Path:
    return root / "runtime" / "transactions.jsonl"


def _marker_path(root: Path, operation_id: str, suffix: str = "commit") -> Path:
    return root / "runtime" / "transactions" / f"{operation_id}.{suffix}.json"


def _validate_manifest(record: dict[str, Any]) -> None:
    errors = validate(record, read_object(TRANSACTION_SCHEMA), base_path=TRANSACTION_SCHEMA.parent)
    if errors:
        raise TransactionError("invalid transaction record: " + "; ".join(errors))


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        record = read_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise TransactionError(f"transaction manifest is unreadable: {path}: {exc}") from exc
    _validate_manifest(record)
    return record


def _append_ledger(root: Path, record: dict[str, Any]) -> None:
    _validate_manifest(record)
    append_jsonl(_transaction_ledger_path(root), record)


def _read_ledger(root: Path) -> list[dict[str, Any]]:
    path = _transaction_ledger_path(root)
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TransactionError(f"transaction ledger line {line_number} is invalid: {exc}") from exc
            if not isinstance(record, dict):
                raise TransactionError(f"transaction ledger line {line_number} is not an object")
            _validate_manifest(record)
            records.append(record)
    except (OSError, UnicodeError) as exc:
        raise TransactionError(f"transaction ledger is unreadable: {exc}") from exc
    return records


def _current_revision(path: Path) -> int:
    if not path.is_file() or path.is_symlink():
        return 0
    if path.suffix.lower() == ".jsonl":
        try:
            return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        except (OSError, UnicodeError):
            return 0
    try:
        value = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return 0
    if isinstance(value, dict) and isinstance(value.get("revision"), int) and not isinstance(value.get("revision"), bool):
        return value["revision"]
    return 0


def _derive_operation_id(idempotency_key: str) -> str:
    return "OP-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]


class _RuntimeTransactionMeta(type):
    """Private compatibility adapter for pre-Task-5 positional callers."""

    def __call__(cls, project_root: str | Path, *args: Any, **kwargs: Any) -> Any:
        if len(args) == 5 and not kwargs:
            operation_id, operation_type, idempotency_key, expected_revisions, target_files = args
            instance = super().__call__(
                project_root,
                operation_type=operation_type,
                idempotency_key=idempotency_key,
                expected_revisions=expected_revisions,
            )
            instance.operation_id = operation_id
            instance._legacy_mode = True
            instance._legacy_target_files = list(target_files)
            instance.manifest_path = _manifest_path(instance.root, operation_id)
            return instance
        return super().__call__(project_root, *args, **kwargs)


class RuntimeTransaction(metaclass=_RuntimeTransactionMeta):
    """Publish JSON files with durable preparation, commit, and recovery evidence."""

    def __getattribute__(self, name: str) -> Any:
        if name in {"prepare", "stage_json"}:
            try:
                legacy_mode = object.__getattribute__(self, "_legacy_mode")
            except AttributeError:
                legacy_mode = False
            if legacy_mode:
                return object.__getattribute__(self, f"_legacy_{name}")
        return object.__getattribute__(self, name)

    def __init__(
        self,
        project_root: str | Path,
        *,
        operation_type: str,
        idempotency_key: str,
        expected_revisions: dict[str, int],
    ) -> None:
        if not isinstance(operation_type, str) or not operation_type.strip():
            raise ValueError("operation_type must be a non-empty string")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key must be a non-empty string")
        if not isinstance(expected_revisions, dict):
            raise ValueError("expected_revisions must be an object")
        self.project_root = project_path(project_root)
        self.root = ensure_runtime_initialized(self.project_root)
        self.operation_id = _derive_operation_id(idempotency_key)
        self.operation_type = operation_type.strip().upper()
        self.idempotency_key = idempotency_key
        self.expected_revisions: dict[str, int] = {}
        for path, revision in expected_revisions.items():
            canonical, _ = _canonical_target(self.project_root, path, field="expected_revisions path")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise ValueError(f"expected revision for {canonical} must be a non-negative integer")
            self.expected_revisions[canonical] = revision
        self._target_files: list[str] = []
        self._legacy_mode = False
        self._legacy_target_files: list[str] = []
        self.manifest_path = _manifest_path(self.root, self.operation_id)

    def _canonical_targets(self, target_files: list[str]) -> list[str]:
        if not isinstance(target_files, list) or not target_files:
            raise ValueError("target_files must be a non-empty list")
        targets = [_canonical_target(self.project_root, item)[0] for item in target_files]
        if not self._legacy_mode and any(target.startswith("project/") for target in targets):
            raise ValueError("target_files must remain inside project/.agent")
        if len(set(targets)) != len(targets):
            raise ValueError("target_files must not contain duplicates")
        missing = [path for path in targets if path not in self.expected_revisions]
        if missing:
            raise ValueError("expected_revisions is missing target files: " + ", ".join(missing))
        return targets

    def _identity_matches(self, record: dict[str, Any], *, include_operation_id: bool = True) -> None:
        if include_operation_id and record.get("operation_id") != self.operation_id:
            raise TransactionError("transaction operation_id does not match")
        if record.get("operation_type") != self.operation_type:
            raise TransactionError("transaction operation_type conflicts with existing operation")
        if record.get("idempotency_key") != self.idempotency_key:
            raise TransactionError("transaction idempotency_key conflicts with existing operation")
        if record.get("expected_revisions") != self.expected_revisions:
            raise TransactionError("transaction expected_revisions conflict with existing operation")
        if record.get("target_files") != self._target_files:
            raise TransactionError("transaction target_files conflict with existing operation")

    def _find_idempotent_record(self) -> dict[str, Any] | None:
        manifests = [
            path for path in sorted((self.root / "runtime" / "transactions").glob("*.json"))
            if not path.name.endswith(".commit.json") and not path.name.endswith(".rollback.json")
        ]
        records: list[dict[str, Any]] = []
        for path in manifests:
            record = _read_manifest(path)
            if record.get("idempotency_key") == self.idempotency_key:
                records.append(record)
        records.extend(record for record in _read_ledger(self.root) if record.get("idempotency_key") == self.idempotency_key)
        if not records:
            return None
        latest = records[-1]
        if latest.get("operation_id") != self.operation_id:
            raise TransactionError("idempotency_key is already bound to another operation")
        self._identity_matches(latest)
        if not self.manifest_path.is_file():
            raise TransactionError("idempotency evidence exists but transaction manifest is missing")
        return _read_manifest(self.manifest_path)

    def _validate_revisions_and_hashes(self) -> tuple[dict[str, str | None], dict[str, str]]:
        previous_hashes: dict[str, str | None] = {}
        current_revisions: dict[str, int] = {}
        for target_path in self._target_files:
            target = _target_from_manifest(self.project_root, target_path)
            expected = self.expected_revisions[target_path]
            current = _current_revision(target)
            if current != expected:
                raise ValueError(f"stale revision for {target_path}: expected {expected}, current {current}")
            previous_hashes[target_path] = _sha256_file(target)
            current_revisions[target_path] = current
        return previous_hashes, {path: str(value) for path, value in current_revisions.items()}

    def _staging_dir(self) -> Path:
        return _safe_agent_path(self.root, f"runtime/staging/{self.operation_id}", field="staging path")

    def _initial_record(self, previous_hashes: dict[str, str | None]) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "idempotency_key": self.idempotency_key,
            "status": "PREPARED",
            "expected_revisions": dict(self.expected_revisions),
            "target_files": list(self._target_files),
            "staged_files": [],
            "started_at": utc_now(),
            "committed_at": None,
            "rollback_reason": None,
            "commit_marker": None,
            "rollback_marker": None,
            "evidence": {
                "classification": "PREPARED",
                "phase": "PREPARE",
                "previous_hashes": previous_hashes,
                "target_hashes": {},
                "staged_hashes": {},
                "previous_files": {},
                "errors": [],
            },
        }

    def _save(self, record: dict[str, Any]) -> None:
        _validate_manifest(record)
        _write_json_durable(self.manifest_path, record)

    def _load_required(self) -> dict[str, Any]:
        if not self.manifest_path.is_file():
            raise TransactionError("transaction is not prepared")
        record = _read_manifest(self.manifest_path)
        self._target_files = list(record["target_files"])
        self._identity_matches(record)
        return record

    def _legacy_prepare(self) -> dict[str, Any]:
        return type(self).prepare(self, self._legacy_target_files)

    def prepare(self, target_files: list[str]) -> dict[str, Any]:
        self._target_files = self._canonical_targets(target_files)
        with runtime_lock(self.project_root) as root:
            existing = self._find_idempotent_record()
            if existing is not None:
                self._target_files = list(existing["target_files"])
                return existing
            previous_hashes, _ = self._validate_revisions_and_hashes()
            staging = self._staging_dir()
            staging.mkdir(parents=True, exist_ok=True)
            record = self._initial_record(previous_hashes)
            try:
                for target_path, previous_hash in previous_hashes.items():
                    if previous_hash is None:
                        continue
                    target = _target_from_manifest(self.project_root, target_path)
                    previous_path = _safe_agent_path(
                        self.root,
                        f"runtime/staging/{self.operation_id}/.previous/{target_path}",
                        field="previous backup path",
                    )
                    _write_bytes_atomic(previous_path, target.read_bytes())
                    record["evidence"]["previous_files"][target_path] = previous_path.relative_to(self.root).as_posix()
                self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
                self._save(record)
                _append_ledger(root, record)
                return record
            except Exception:
                try:
                    self._cleanup_staging()
                except Exception as cleanup_error:
                    raise TransactionError(f"prepare failed and staging cleanup failed: {cleanup_error}") from cleanup_error
                raise

    def _validate_schema(self, schema_path: str | Path) -> None:
        try:
            schema = read_json(schema_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid schema_path: {schema_path}: {exc}") from exc
        errors = validate({}, schema, base_path=Path(schema_path).resolve().parent)
        # A schema may require fields, so only its shape is checked here; payload validation follows.
        if errors and not isinstance(schema, dict):
            raise ValueError(f"invalid schema_path: {schema_path}")

    def _validated_json_bytes(self, value: Any, schema_path: str | Path) -> bytes:
        try:
            schema = read_json(schema_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid schema_path: {schema_path}: {exc}") from exc
        if not isinstance(schema, dict):
            raise ValueError(f"invalid schema_path: {schema_path}")
        errors = validate(value, schema, base_path=Path(schema_path).resolve().parent)
        if errors:
            raise ValueError("invalid runtime artifact: " + "; ".join(errors))
        return _json_bytes(value)

    def _stage_content(self, relative_path: str, content: bytes, *, allow_content_change: bool = False) -> dict[str, Any]:
        canonical, _ = _canonical_target(self.project_root, relative_path)
        if not self._legacy_mode and canonical.startswith("project/"):
            raise ValueError("staged target must remain inside project/.agent")
        with runtime_lock(self.project_root) as root:
            record = self._load_required()
            if canonical not in record["target_files"]:
                raise ValueError(f"target file was not declared: {canonical}")
            content_hash = _sha256_bytes(content)
            existing = next((item for item in record["staged_files"] if item["target_path"] == canonical), None)
            if existing is not None and existing["staged_hash"] != content_hash and not allow_content_change:
                raise TransactionError("idempotency key conflicts with changed staged content")
            if record["status"] == "COMMITTED":
                self._verify_committed(record)
                return record
            if record["status"] in {"ROLLED_BACK", "RECOVERY_PENDING", "APPLYING"}:
                raise TransactionError(f"cannot stage transaction in status {record['status']}")
            if not record["staged_files"]:
                current_hash = _sha256_file(_target_from_manifest(self.project_root, canonical))
                if current_hash != record["evidence"]["previous_hashes"].get(canonical):
                    raise ValueError(f"target changed after prepare: {canonical}")
            staged_relative = _staging_relative(self.operation_id, canonical)
            staged_path = _safe_agent_path(root, staged_relative, field="staged path")
            previous_hash = record["evidence"]["previous_hashes"].get(canonical)
            entry = {
                "target_path": canonical,
                "staged_path": staged_relative,
                "previous_hash": previous_hash,
                "staged_hash": content_hash,
                "target_hash": None,
            }
            _write_bytes_atomic(staged_path, content)
            staged_files = [item for item in record["staged_files"] if item["target_path"] != canonical]
            staged_files.append(entry)
            record["staged_files"] = sorted(staged_files, key=lambda item: item["target_path"])
            record["evidence"]["staged_hashes"][canonical] = content_hash
            record["evidence"]["phase"] = "PREPARE"
            self._save(record)
            return record

    def _legacy_stage_json(self, relative_path: str, value: Any, schema_path: str | Path | None = None) -> dict[str, Any]:
        if schema_path is None:
            return self._stage_content(
                relative_path,
                _json_bytes(value),
                allow_content_change=self.operation_type == "MERGE_WORKTREE",
            )
        return type(self).stage_json(self, relative_path, value, schema_path)

    def stage_json(self, relative_path: str, value: Any, schema_path: str | Path) -> dict[str, Any]:
        content = self._validated_json_bytes(value, schema_path)
        return self._stage_content(relative_path, content)

    def stage_text(self, relative_path: str, content: str) -> dict[str, Any]:
        if not isinstance(content, str):
            raise TypeError("staged text content must be a string")
        return self._stage_content(relative_path, content.encode("utf-8"))

    def _staged_by_target(self, record: dict[str, Any]) -> dict[str, dict[str, Any]]:
        staged_by_target = {item["target_path"]: item for item in record["staged_files"]}
        missing = [path for path in record["target_files"] if path not in staged_by_target]
        if missing:
            raise TransactionError("transaction is missing staged files: " + ", ".join(missing))
        for target_path in record["target_files"]:
            item = staged_by_target[target_path]
            staged_path = _safe_agent_path(self.root, item["staged_path"], field="staged path")
            if not staged_path.is_file() or staged_path.is_symlink():
                raise TransactionError(f"staged file is missing or unsafe: {staged_path}")
            if _sha256_file(staged_path) != item["staged_hash"]:
                raise TransactionError(f"staged hash mismatch for {target_path}")
        return staged_by_target

    def _write_commit_marker(self, record: dict[str, Any], committed_at: str) -> str:
        marker = _marker_path(self.root, self.operation_id)
        _write_json_durable(
            marker,
            {
                "operation_id": self.operation_id,
                "operation_type": self.operation_type,
                "idempotency_key": self.idempotency_key,
                "status": "COMMITTED",
                "committed_at": committed_at,
                "target_hashes": dict(record["evidence"]["target_hashes"]),
            },
        )
        return marker.relative_to(self.root).as_posix()

    def _verify_committed(self, record: dict[str, Any]) -> None:
        marker_name = record.get("commit_marker")
        if not isinstance(marker_name, str) or not marker_name:
            raise TransactionError("committed transaction is missing commit marker evidence")
        marker = _safe_agent_path(self.root, marker_name, field="commit marker path")
        try:
            marker_record = read_object(marker)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise TransactionError(f"committed marker is unreadable: {exc}") from exc
        if (
            marker_record.get("operation_id") != record["operation_id"]
            or marker_record.get("operation_type") != record["operation_type"]
            or marker_record.get("idempotency_key") != record["idempotency_key"]
            or marker_record.get("status") != "COMMITTED"
            or marker_record.get("target_hashes") != record["evidence"].get("target_hashes")
        ):
            raise TransactionError("committed marker evidence is inconsistent")
        for target_path in record["target_files"]:
            expected_hash = record["evidence"].get("target_hashes", {}).get(target_path)
            if expected_hash is None or _sha256_file(_target_from_manifest(self.project_root, target_path)) != expected_hash:
                raise TransactionError(f"committed target hash verification failed: {target_path}")

    def _cleanup_staging(self) -> None:
        staging = self._staging_dir()
        if not staging.exists() and not staging.is_symlink():
            return
        if staging.is_symlink() or not _contained(staging.resolve(strict=False), self.root.resolve()):
            raise TransactionError("staging cleanup path is unsafe")
        shutil.rmtree(staging)
        _fsync_directory(staging.parent)

    def _mark_recovery_pending(self, record: dict[str, Any], reason: str, classification: str = "RECOVERY_PENDING") -> dict[str, Any]:
        record["status"] = "RECOVERY_PENDING"
        record["rollback_reason"] = reason
        record["evidence"]["classification"] = classification
        record["evidence"]["phase"] = "RECOVERY"
        record["evidence"].setdefault("errors", []).append(reason)
        self._save(record)
        _append_ledger(self.root, record)
        return record

    def _publish_target(self, staged_path: Path, target_path: Path) -> None:
        if not _contained(target_path.resolve(strict=False), self.project_root.resolve()):
            raise TransactionError("target path escapes project root")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = staged_path.read_bytes()
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target_path.name}.", suffix=".tmp", dir=target_path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target_path)
            _fsync_directory(target_path.parent)
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _commit_locked(self, record: dict[str, Any], *, recovered: bool = False) -> dict[str, Any]:
        if record["status"] == "COMMITTED":
            self._verify_committed(record)
            self._cleanup_staging()
            return record
        if record["status"] == "ROLLED_BACK":
            raise TransactionError("transaction has already been rolled back")
        if record["status"] == "RECOVERY_PENDING":
            raise TransactionError("transaction is recovery-pending and requires explicit reconciliation")
        if record["status"] == "PREPARED":
            record["status"] = "APPLYING"
            record["evidence"]["classification"] = "RECOVERED_APPLYING" if recovered else "APPLYING"
            record["evidence"]["phase"] = "APPLY"
            self._save(record)
            _append_ledger(self.root, record)
        try:
            staged_by_target = self._staged_by_target(record)
            for target_path in record["target_files"]:
                item = staged_by_target[target_path]
                target = _target_from_manifest(self.project_root, target_path)
                current_hash = _sha256_file(target)
                if current_hash not in {item["previous_hash"], item["staged_hash"]}:
                    return self._mark_recovery_pending(record, f"target changed unexpectedly: {target_path}", "TARGET_CONFLICT")
            for target_path in record["target_files"]:
                item = staged_by_target[target_path]
                target = _target_from_manifest(self.project_root, target_path)
                if _sha256_file(target) != item["staged_hash"]:
                    self._publish_target(_safe_agent_path(self.root, item["staged_path"], field="staged path"), target)
                item["target_hash"] = _sha256_file(target)
                record["evidence"]["target_hashes"][target_path] = item["target_hash"]
                self._save(record)
            for target_path in record["target_files"]:
                item = staged_by_target[target_path]
                if _sha256_file(_target_from_manifest(self.project_root, target_path)) != item["staged_hash"]:
                    return self._mark_recovery_pending(record, f"target hash verification failed: {target_path}", "TARGET_HASH_MISMATCH")
                record["evidence"]["target_hashes"][target_path] = item["staged_hash"]
            committed_at = utc_now()
            record["commit_marker"] = self._write_commit_marker(record, committed_at)
            record["committed_at"] = committed_at
            record["status"] = "COMMITTED"
            record["evidence"]["classification"] = "RECOVERED_COMMIT" if recovered else "COMMITTED"
            record["evidence"]["phase"] = "COMMIT"
            self._save(record)
            _append_ledger(self.root, record)
            try:
                self._cleanup_staging()
            except Exception as exc:
                record["evidence"].setdefault("errors", []).append(f"staging cleanup failed: {exc}")
                self._save(record)
                raise TransactionError(f"staging cleanup failed: {exc}") from exc
            return record
        except Exception as exc:
            if record["status"] == "APPLYING":
                record["evidence"]["phase"] = "APPLY"
                record["evidence"]["last_error"] = str(exc)
                record["evidence"].setdefault("errors", []).append(str(exc))
                try:
                    self._save(record)
                except Exception:
                    pass
            raise

    def commit(self) -> dict[str, Any]:
        with runtime_lock(self.project_root):
            return self._commit_locked(self._load_required())

    def _restore_previous(self, record: dict[str, Any]) -> None:
        staged_by_target = {item["target_path"]: item for item in record["staged_files"]}
        for target_path in record["target_files"]:
            item = staged_by_target.get(target_path)
            if item is None:
                continue
            target = _target_from_manifest(self.project_root, target_path)
            current_hash = _sha256_file(target)
            previous_hash = item["previous_hash"]
            staged_hash = item["staged_hash"]
            if current_hash == previous_hash:
                continue
            if current_hash != staged_hash:
                raise TransactionError(f"cannot safely roll back mixed target state: {target_path}")
            previous_relative = record["evidence"].get("previous_files", {}).get(target_path)
            if previous_hash is None:
                if target.exists() or target.is_symlink():
                    if target.is_symlink() or not _contained(target.resolve(strict=False), self.project_root.resolve()):
                        raise TransactionError(f"unsafe rollback target: {target_path}")
                    target.unlink()
            else:
                if not isinstance(previous_relative, str):
                    raise TransactionError(f"previous bytes are unavailable: {target_path}")
                backup = _safe_agent_path(self.root, previous_relative, field="previous backup path")
                if _sha256_file(backup) != previous_hash:
                    raise TransactionError(f"previous bytes are tampered: {target_path}")
                _write_bytes_atomic(target, backup.read_bytes())

    def rollback(self, reason: str) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("rollback reason must be a non-empty string")
        with runtime_lock(self.project_root):
            record = self._load_required()
            if record["status"] == "COMMITTED":
                raise TransactionError("committed transaction cannot be rolled back")
            if record["status"] == "ROLLED_BACK":
                return record
            try:
                self._restore_previous(record)
            except TransactionError as exc:
                return self._mark_recovery_pending(record, f"rollback unsafe: {exc}", "RECOVERY_PENDING")
            record["status"] = "ROLLED_BACK"
            record["rollback_reason"] = reason
            rollback_marker = _marker_path(self.root, self.operation_id, "rollback")
            _write_json_durable(
                rollback_marker,
                {
                    "operation_id": self.operation_id,
                    "idempotency_key": self.idempotency_key,
                    "status": "ROLLED_BACK",
                    "reason": reason,
                },
            )
            record["rollback_marker"] = rollback_marker.relative_to(self.root).as_posix()
            record["evidence"]["classification"] = "ROLLED_BACK"
            record["evidence"]["phase"] = "ROLLBACK"
            self._save(record)
            _append_ledger(self.root, record)
            try:
                self._cleanup_staging()
            except Exception as exc:
                record["evidence"].setdefault("errors", []).append(f"staging cleanup failed: {exc}")
                self._save(record)
                raise TransactionError(f"staging cleanup failed: {exc}") from exc
            return record


def _transaction_for_record(project: Path, record: dict[str, Any], manifest_path: Path) -> RuntimeTransaction:
    transaction = RuntimeTransaction(
        project,
        operation_type=record["operation_type"],
        idempotency_key=record["idempotency_key"],
        expected_revisions=record["expected_revisions"],
    )
    transaction.operation_id = record["operation_id"]
    transaction.manifest_path = manifest_path
    transaction._target_files = list(record["target_files"])
    return transaction


def _record_targets_are_safely_inferable(project: Path, record: dict[str, Any]) -> bool:
    by_target = {item["target_path"]: item for item in record["staged_files"]}
    for target_path in record["target_files"]:
        item = by_target.get(target_path)
        if item is None:
            return False
        current_hash = _sha256_file(_target_from_manifest(project, target_path))
        if current_hash not in {item["previous_hash"], item["staged_hash"]}:
            return False
    return True


def recover_transactions(project_root: str | Path) -> list[dict[str, object]]:
    """Verify and reconcile all durable transaction manifests under the runtime lock."""

    project = project_path(project_root)
    root = ensure_runtime_initialized(project)
    results: list[dict[str, object]] = []
    with runtime_lock(project):
        transaction_dir = root / "runtime" / "transactions"
        transaction_dir.mkdir(parents=True, exist_ok=True)
        manifests = [path for path in sorted(transaction_dir.glob("*.json")) if not path.name.endswith(".commit.json") and not path.name.endswith(".rollback.json")]
        for path in manifests:
            record = _read_manifest(path)
            transaction = _transaction_for_record(project, record, path)
            try:
                if record["status"] == "COMMITTED":
                    transaction._verify_committed(record)
                    transaction._cleanup_staging()
                elif record["status"] == "PREPARED":
                    if record["operation_type"] in EXTERNAL_OPERATION_TYPES and record["staged_files"]:
                        record = transaction._mark_recovery_pending(record, "external side effect outcome is ambiguous", "AMBIGUOUS_EXTERNAL_SIDE_EFFECT")
                    else:
                        record = transaction.rollback("recovered before apply phase")
                elif record["status"] == "APPLYING":
                    marker = _marker_path(root, record["operation_id"])
                    if marker.is_file():
                        transaction._verify_committed({**record, "status": "COMMITTED", "commit_marker": marker.relative_to(root).as_posix()})
                        record["status"] = "COMMITTED"
                        record["commit_marker"] = marker.relative_to(root).as_posix()
                        record["committed_at"] = read_object(marker).get("committed_at")
                        record["evidence"]["classification"] = "RECOVERED_COMMIT"
                        record["evidence"]["phase"] = "RECOVERY"
                        transaction._save(record)
                        _append_ledger(root, record)
                        transaction._cleanup_staging()
                    elif record["operation_type"] in EXTERNAL_OPERATION_TYPES:
                        record = transaction._mark_recovery_pending(record, "external side effect outcome is ambiguous", "AMBIGUOUS_EXTERNAL_SIDE_EFFECT")
                    else:
                        record = transaction._commit_locked(record, recovered=True)
                elif record["status"] == "RECOVERY_PENDING":
                    record["evidence"]["phase"] = "RECOVERY"
                    transaction._save(record)
                elif record["status"] == "ROLLED_BACK":
                    transaction._cleanup_staging()
            except Exception as exc:
                if record["status"] in {"COMMITTED", "ROLLED_BACK"}:
                    record = transaction._mark_recovery_pending(record, f"recovery evidence invalid: {exc}", "RECOVERY_PENDING")
                elif record["status"] == "APPLYING":
                    if _record_targets_are_safely_inferable(project, record):
                        record = transaction._mark_recovery_pending(record, str(exc), "RECOVERY_PENDING")
                    else:
                        record = transaction._mark_recovery_pending(record, str(exc), "RECOVERY_PENDING")
                else:
                    raise
            results.append(record)
    return results


__all__ = ["RuntimeTransaction", "TransactionError", "recover_transactions"]
