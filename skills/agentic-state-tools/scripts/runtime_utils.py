"""Shared, dependency-free helpers for agentic runtime state scripts."""

from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from state_machine import load_state_machine, event_status_map, status_event_map, transition_map


class RuntimeNotInitializedError(FileNotFoundError):
    """Raised when a mutating command targets a project without initialized runtime state."""


class RuntimeLockedError(RuntimeError):
    """Raised when another state mutation holds the runtime lock."""


_STATE_MACHINE = load_state_machine()
EVENT_TYPE_TO_STATUS = event_status_map(_STATE_MACHINE)
STATUS_TO_EVENT_TYPE = status_event_map(_STATE_MACHINE)
NON_STATE_EVENT_TYPES = set(_STATE_MACHINE["non_state_events"])
TERMINAL_STATUSES = set(_STATE_MACHINE["terminal_statuses"])

LOCK_DIRECTORIES = {
    "task": "tasks",
    "file": "files",
    "resource": "resources",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def project_path(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve()


def validate_identifier(value: Any, field: str = "identifier") -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ValueError(f"{field} must contain only letters, digits, dot, underscore, or hyphen")
    return value


def next_revision(payload: dict[str, Any], current: int) -> int:
    expected = payload.pop("expected_revision", current)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    if expected != current:
        raise ValueError(f"stale revision: expected {expected}, current {current}")
    return current + 1


def task_dependencies(task: dict[str, Any]) -> list[str]:
    """Read dependencies from either the legacy task shape or queue snapshots."""

    snapshot = task.get("dependency_snapshot")
    value = snapshot.get("depends_on", []) if isinstance(snapshot, dict) else task.get("depends_on", [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("task dependencies must be an array of strings")
    return sorted(set(value))


def task_write_scopes(task: dict[str, Any]) -> list[str]:
    """Read normalized write scopes from either a task or a queue snapshot."""

    snapshot = task.get("scope_snapshot")
    value = snapshot.get("write_scope", []) if isinstance(snapshot, dict) else task.get("write_scope", [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("task write_scope must be an array of strings")
    scopes: list[str] = []
    for item in value:
        normalized = item.replace("\\", "/").strip()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.rstrip("/") or "."
        if normalized not in scopes:
            scopes.append(normalized)
    return sorted(scopes)


def agent_path(project_root: str | Path) -> Path:
    return project_path(project_root) / ".agent"


def ensure_runtime_initialized(project_root: str | Path) -> Path:
    root = agent_path(project_root)
    required = (root / "runtime" / "state.json", root / "runtime" / "events.jsonl")
    if not all(path.is_file() for path in required):
        raise RuntimeNotInitializedError(
            f"runtime is not initialized at {root}; run init_runtime.py first"
        )
    return root


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # Windows does not reliably implement os.kill(pid, 0) as a liveness
        # probe. A signaled process handle is the authoritative check here.
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        access = 0x00100000 | 0x00001000  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
        handle = kernel32.OpenProcess(access, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            return error == 5  # Access denied: conservatively treat it as alive.
        try:
            result = kernel32.WaitForSingleObject(handle, 0)
            return result == 0x00000102  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def remove_dead_runtime_lock(lock_path: Path) -> bool:
    """Remove a lock only when its recorded owner process is definitely gone."""

    try:
        metadata = read_json(lock_path)
        pid = metadata.get("pid") if isinstance(metadata, dict) else None
        if not isinstance(pid, int) or process_is_alive(pid):
            return False
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
    return True


@contextmanager
def runtime_lock(project_root: str | Path) -> Iterator[Path]:
    """Acquire a short-lived exclusive lock for one runtime mutation."""

    root = ensure_runtime_initialized(project_root)
    lock_path = root / "locks" / "runtime-state.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    try:
        descriptor = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        if not remove_dead_runtime_lock(lock_path):
            raise RuntimeLockedError(f"runtime is busy: {lock_path}") from exc
        try:
            descriptor = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError as retry_exc:
            raise RuntimeLockedError(f"runtime is busy: {lock_path}") from retry_exc

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            json.dump({"pid": os.getpid(), "acquired_at": utc_now()}, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield root
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def read_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_object(path: str | Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def inspect_terminal_cleanup(root: Path, task_id: str) -> dict[str, Any]:
    """Inspect terminal cleanup evidence without deleting any artifact."""

    reasons: list[str] = []
    remaining_leases: list[str] = []
    remaining_locks: list[str] = []
    unresolved_operations: list[str] = []
    lease_path = root / "work" / task_id / "lease.json"
    if lease_path.is_file():
        try:
            read_object(lease_path)
            remaining_leases.append(str(lease_path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"MALFORMED_LEASE:{lease_path.name}:{exc}")
    for kind, directory in LOCK_DIRECTORIES.items():
        for lock_path in sorted((root / "locks" / directory).glob("*.json")):
            try:
                record = read_object(lock_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                reasons.append(f"MALFORMED_LOCK:{lock_path.name}:{exc}")
                continue
            owned = record.get("task_id") == task_id or (kind == "task" and record.get("key") == task_id)
            if owned:
                remaining_locks.append(str(lock_path))
    operations_path = root / "work" / task_id / "operations.jsonl"
    if operations_path.is_file():
        latest_operations: dict[str, dict[str, Any]] = {}
        try:
            for line_number, line in enumerate(operations_path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    operation = json.loads(line)
                except json.JSONDecodeError as exc:
                    reasons.append(f"MALFORMED_OPERATION:{line_number}:{exc}")
                    continue
                if not isinstance(operation, dict):
                    reasons.append(f"MALFORMED_OPERATION:{line_number}:record is not an object")
                    continue
                operation_id = operation.get("operation_id")
                if not isinstance(operation_id, str) or not operation_id:
                    reasons.append(f"MALFORMED_OPERATION:{line_number}:operation_id is missing")
                    continue
                latest_operations[operation_id] = operation
        except (OSError, UnicodeError) as exc:
            reasons.append(f"UNREADABLE_OPERATIONS:{exc}")
        unresolved_operations.extend(
            operation_id
            for operation_id, operation in latest_operations.items()
            if str(operation.get("status", "")).upper() in {"STARTED", "UNKNOWN"}
        )
    if remaining_leases:
        reasons.append("OWNED_LEASE_REMAINS")
    if remaining_locks:
        reasons.append("OWNED_LOCK_REMAINS")
    if unresolved_operations:
        reasons.append("UNRESOLVED_OPERATION_REMAINS")
    return {
        "task_id": task_id,
        "valid": not reasons,
        "classification": "CLEAN" if not reasons else "NEEDS_RECONCILIATION",
        "reasons": sorted(set(reasons)),
        "remaining_leases": remaining_leases,
        "remaining_locks": remaining_locks,
        "unresolved_operations": unresolved_operations,
    }


def assert_terminal_cleanup_safe(root: Path, task_id: str) -> dict[str, Any]:
    evidence = inspect_terminal_cleanup(root, task_id)
    preflight_reasons = [reason for reason in evidence["reasons"] if reason not in {"OWNED_LEASE_REMAINS", "OWNED_LOCK_REMAINS"}]
    if preflight_reasons:
        raise ValueError("terminal cleanup preflight NEEDS_RECONCILIATION: " + "; ".join(preflight_reasons))
    return evidence


def read_payload(path: str) -> Any:
    if path == "-":
        import sys

        return json.load(sys.stdin)
    return read_json(path)


def write_text_atomic(path: str | Path, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_json_atomic(path: str | Path, value: Any) -> None:
    write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_json_exclusive(path: str | Path, value: Any) -> None:
    """Create one JSON file without replacing an existing file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        raise


def lock_artifact_path(root: Path, kind: str, key: str) -> Path:
    directory = LOCK_DIRECTORIES.get(kind)
    if directory is None:
        raise ValueError(f"unsupported lock kind: {kind}")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("lock key must be a non-empty string")
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return root / "locks" / directory / f"{digest}.json"


def cleanup_task_runtime(root: Path, task_id: str) -> dict[str, list[dict[str, Any]]]:
    """Remove terminal task leases and owned locks; callers append evidence events."""

    removed_leases: list[dict[str, Any]] = []
    removed_locks: list[dict[str, Any]] = []
    lease_path = root / "work" / task_id / "lease.json"
    if lease_path.is_file():
        lease = read_object(lease_path)
        lease_path.unlink()
        removed_leases.append(lease)
    for kind, directory in LOCK_DIRECTORIES.items():
        for lock_path in sorted((root / "locks" / directory).glob("*.json")):
            record = read_object(lock_path)
            if record.get("task_id") != task_id and not (kind == "task" and record.get("key") == task_id):
                continue
            lock_path.unlink()
            removed_locks.append(record)
    return {"leases": removed_leases, "locks": removed_locks}


def lease_expiry(seconds: int) -> str:
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
        raise ValueError("lease_seconds must be a positive integer")
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def append_jsonl(path: str | Path, value: Any) -> None:
    """Append one durable JSONL record. The caller must hold runtime_lock()."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def set_task_status_in_state(state: dict[str, Any], task_id: str, status: str) -> None:
    """Keep task indexes consistent for every terminal or active status."""

    state.setdefault("task_statuses", {})[task_id] = status
    for key in ("running_tasks", "blocked_tasks", "completed_tasks"):
        if task_id in state.setdefault(key, []):
            state[key].remove(task_id)
    if status in {"RUNNING", "CHECKPOINTED", "RESUMING"}:
        state["running_tasks"].append(task_id)
    elif status in {"BLOCKED", "REPAIR_REQUIRED", "WAITING_DEPENDENCY", "WAITING_RESOURCE_LOCK", "STALE", "RECOVERY_PENDING", "DEFERRED", "ESCALATED", "ABORTED_UNSAFE"}:
        state["blocked_tasks"].append(task_id)
    elif status in {"COMPLETED", "ACCEPTED", "CANCELLED", "SUPERSEDED", "ARCHIVED"}:
        state["completed_tasks"].append(task_id)


def iter_events(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    events: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid event JSON at line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"event at line {line_number} must be an object")
            validate_event(value)
            events.append(value)
    return events


def validate_event(event: dict[str, Any]) -> None:
    for field in ("event_id", "timestamp", "type", "actor"):
        if not isinstance(event.get(field), str) or not event[field].strip():
            raise ValueError(f"event.{field} must be a non-empty string")
    if re.fullmatch(r"EVT-[0-9]{6,}", event["event_id"]) is None:
        raise ValueError("event.event_id must match EVT- followed by at least six digits")
    if event["type"] != event["type"].upper():
        raise ValueError("event.type must use uppercase canonical values")
    event_type = event["type"].upper()
    if event_type not in EVENT_TYPE_TO_STATUS and event_type not in NON_STATE_EVENT_TYPES:
        raise ValueError(f"unknown event type: {event['type']}")
    if "task_id" in event and not isinstance(event["task_id"], str):
        raise ValueError("event.task_id must be a string")
    if "run_id" in event and not isinstance(event["run_id"], str):
        raise ValueError("event.run_id must be a string")
    if "data" in event and not isinstance(event["data"], dict):
        raise ValueError("event.data must be an object")


def validate_event_preconditions(root: Path, event: dict[str, Any]) -> None:
    """Validate artifact-backed gates before an event becomes immutable history."""

    event_type = event.get("type")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if event_type == "REVIEW_CREATED":
        task_id = event.get("task_id")
        review_id = data.get("review_id")
        if not isinstance(task_id, str) or not isinstance(review_id, str) or not review_id.strip():
            raise ValueError("REVIEW_CREATED requires task_id and review_id evidence")
        review_path = root / "work" / task_id / "review.json"
        if not review_path.is_file() or read_object(review_path).get("review_id") != review_id:
            raise ValueError("REVIEW_CREATED requires a matching persisted review artifact")
        return
    if event_type == "BATCH_REVIEW_CREATED":
        batch_id = data.get("batch_id")
        review_id = data.get("review_id")
        if not isinstance(batch_id, str) or not isinstance(review_id, str) or not review_id.strip():
            raise ValueError("BATCH_REVIEW_CREATED requires batch_id and review_id evidence")
        review_path = root / "work" / batch_id / "review.json"
        if not review_path.is_file() or read_object(review_path).get("review_id") != review_id:
            raise ValueError("BATCH_REVIEW_CREATED requires a matching persisted batch review artifact")
        return
    if event_type == "CHECKPOINT_CREATED":
        task_id = event.get("task_id")
        checkpoint_id = data.get("checkpoint_id")
        if not isinstance(task_id, str) or not isinstance(checkpoint_id, str):
            raise ValueError("CHECKPOINT_CREATED requires task_id and checkpoint_id evidence")
        checkpoint_path = root / "work" / task_id / "checkpoint.json"
        if not checkpoint_path.is_file() or read_object(checkpoint_path).get("checkpoint_id") != checkpoint_id:
            raise ValueError("CHECKPOINT_CREATED requires a matching persisted checkpoint artifact")
        return
    if event_type == "APPROVAL_RECORDED":
        approval_id = data.get("approval_id")
        target_type = data.get("target_type")
        target_id = data.get("target_id")
        if not all(isinstance(item, str) and item.strip() for item in (approval_id, target_type, target_id)):
            raise ValueError("APPROVAL_RECORDED requires approval target evidence")
        approval_path = root / "approvals" / f"{target_type}-{target_id}.json"
        if not approval_path.is_file() or read_object(approval_path).get("approval_id") != approval_id:
            raise ValueError("APPROVAL_RECORDED requires a matching persisted approval artifact")
        return
    if event_type != "TASK_ACCEPTED":
        return
    task_id = event.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("TASK_ACCEPTED requires task_id")
    review_id = data.get("review_id")
    if not isinstance(review_id, str) or not review_id.strip():
        raise ValueError("TASK_ACCEPTED requires review_id evidence")
    review_path = root / "work" / task_id / "review.json"
    if not review_path.is_file():
        raise ValueError("TASK_ACCEPTED requires a persisted review artifact")
    review = read_object(review_path)
    if review.get("task_id") != task_id or review.get("review_id") != review_id:
        raise ValueError("TASK_ACCEPTED review identity does not match task")
    if str(review.get("verdict", "")).upper() != "PASS":
        raise ValueError("TASK_ACCEPTED requires a PASS review")
    task_state_path = root / "work" / task_id / "task-state.json"
    if not task_state_path.is_file():
        raise ValueError("TASK_ACCEPTED requires persisted task state")
    task_state = read_object(task_state_path)
    if str(task_state.get("status", "")).upper() != "ACCEPTED" or task_state.get("review_id") != review_id:
        raise ValueError("TASK_ACCEPTED task state is not linked to the passing review")


def next_event_id(events: list[dict[str, Any]]) -> str:
    highest = 0
    for event in events:
        event_id = event.get("event_id")
        match = re.fullmatch(r"EVT-([0-9]+)", event_id) if isinstance(event_id, str) else None
        if match:
            highest = max(highest, int(match.group(1)))
    return f"EVT-{highest + 1:06d}"


def validate_state_event_transition(state: dict[str, Any], event: dict[str, Any]) -> None:
    """Reject event replay that invents an impossible task status."""

    next_status = EVENT_TYPE_TO_STATUS.get(str(event.get("type", "")).upper())
    task_id = event.get("task_id")
    if next_status is None or not task_id:
        return
    statuses = state.get("task_statuses", {})
    current_status = statuses.get(task_id)
    if current_status is None:
        if next_status == "ACCEPTED":
            raise ValueError("TASK_ACCEPTED cannot be the first task state event")
        return
    current_status = str(current_status).upper()
    executor_targets = transition_map("executor").get(current_status, set())
    reviewer_targets = transition_map("reviewer").get(current_status, set())
    if next_status not in executor_targets and next_status not in reviewer_targets:
        raise ValueError(f"invalid replay transition: {current_status} -> {next_status}")


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Apply one valid event to the deterministic state snapshot."""

    validate_state_event_transition(state, event)

    next_state = dict(state)
    previous_revision = int(next_state.get("revision", 0))
    next_state["previous_revision"] = previous_revision
    next_state["revision"] = previous_revision + 1
    next_state["last_event_id"] = event["event_id"]
    next_state["updated_at"] = event["timestamp"]

    for key in ("running_tasks", "blocked_tasks", "completed_tasks"):
        next_state.setdefault(key, [])
    next_state.setdefault("task_statuses", {})

    task_id = event.get("task_id")
    status = EVENT_TYPE_TO_STATUS.get(event["type"].upper())
    if task_id and status:
        next_state["task_statuses"][task_id] = status
        set_task_status_in_state(next_state, task_id, status)

    return next_state


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "revision": 0,
        "previous_revision": None,
        "last_event_id": None,
        "updated_at": utc_now(),
        "running_tasks": [],
        "blocked_tasks": [],
        "completed_tasks": [],
        "task_statuses": {},
    }
