"""Build a deterministic, read-only projection of the .agent runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


STATE_TOOLS_SCRIPTS = Path(__file__).resolve().parents[2] / "agentic-state-tools" / "scripts"
if str(STATE_TOOLS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(STATE_TOOLS_SCRIPTS))
from validate_payload import validate  # noqa: E402
from redaction import redact_value  # noqa: E402


DEFAULT_REDACT_KEYS = {
    "access_token",
    "authorization",
    "api_key",
    "password",
    "private_key",
    "secret",
    "token",
}
REDACTED = "[REDACTED]"
DEFAULT_STALE_AFTER_SECONDS = 3600
CONFIG_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/dashboard-config.schema.json"
SNAPSHOT_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/dashboard-snapshot.schema.json"


class DashboardError(ValueError):
    """Raised when dashboard inputs or the read-only boundary are invalid."""


def parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise DashboardError(f"{field} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DashboardError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise DashboardError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def relative_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def record_source(sources: dict[str, str], root: Path, path: Path, raw: bytes) -> None:
    sources[relative_path(root, path)] = hashlib.sha256(raw).hexdigest()


def diagnostic(diagnostics: list[dict[str, str]], code: str, path: str, detail: str) -> None:
    diagnostics.append({"code": code, "path": path, "detail": detail})


def read_json_object(
    root: Path,
    relative: str,
    sources: dict[str, str],
    diagnostics: list[dict[str, str]],
) -> dict[str, Any] | None:
    path = root / relative
    if not path.is_file():
        diagnostic(diagnostics, "MISSING_SOURCE", relative, "file is missing")
        return None
    try:
        raw = path.read_bytes()
        record_source(sources, root, path, raw)
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        diagnostic(diagnostics, "MALFORMED_SOURCE", relative, "invalid JSON")
        return None
    if not isinstance(value, dict):
        diagnostic(diagnostics, "INVALID_SOURCE_SHAPE", relative, "expected a JSON object")
        return None
    return value


def read_json_lines(
    root: Path,
    relative: str,
    sources: dict[str, str],
    diagnostics: list[dict[str, str]],
) -> list[dict[str, Any]]:
    path = root / relative
    if not path.is_file():
        diagnostic(diagnostics, "MISSING_SOURCE", relative, "file is missing")
        return []
    try:
        raw = path.read_bytes()
        record_source(sources, root, path, raw)
        lines = raw.decode("utf-8").splitlines()
    except (OSError, UnicodeError):
        diagnostic(diagnostics, "MALFORMED_SOURCE", relative, "file is unreadable")
        return []
    values: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            diagnostic(diagnostics, "MALFORMED_SOURCE", f"{relative}:{line_number}", "invalid JSON line")
            continue
        if not isinstance(value, dict):
            diagnostic(diagnostics, "INVALID_SOURCE_SHAPE", f"{relative}:{line_number}", "expected a JSON object")
            continue
        values.append(value)
    return values


def load_config(path: str | None) -> tuple[set[str], int, list[str]]:
    configured: list[str] = []
    stale_after_seconds = DEFAULT_STALE_AFTER_SECONDS
    if path:
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DashboardError(f"config is unreadable: {exc}") from exc
        schema = json.loads(CONFIG_SCHEMA.read_text(encoding="utf-8"))
        schema_errors = validate(value, schema)
        if schema_errors:
            raise DashboardError(f"config schema is invalid: {'; '.join(schema_errors)}")
        if not isinstance(value, dict):
            raise DashboardError("config must be a JSON object")
        unknown = sorted(set(value) - {"redact_keys", "stale_after_seconds"})
        if unknown:
            raise DashboardError(f"config has unknown fields: {', '.join(unknown)}")
        raw_keys = value.get("redact_keys", [])
        if not isinstance(raw_keys, list) or any(not isinstance(item, str) or not item.strip() for item in raw_keys):
            raise DashboardError("config.redact_keys must be an array of non-empty strings")
        configured = sorted({item.strip().casefold() for item in raw_keys})
        if "stale_after_seconds" in value:
            stale_after_seconds = value["stale_after_seconds"]
            if isinstance(stale_after_seconds, bool) or not isinstance(stale_after_seconds, int) or stale_after_seconds < 0:
                raise DashboardError("config.stale_after_seconds must be a non-negative integer")
    effective = sorted(DEFAULT_REDACT_KEYS | set(configured))
    return set(effective), stale_after_seconds, configured


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    try:
        schema = json.loads(SNAPSHOT_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DashboardError(f"snapshot schema is unreadable: {exc}") from exc
    errors = validate(snapshot, schema)
    if errors:
        raise DashboardError(f"snapshot schema is invalid: {'; '.join(errors)}")


def redact(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if str(key).casefold() in keys else redact(child, keys)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact(item, keys) for item in value]
    return value


def stale_reasons(value: dict[str, Any], as_of: datetime, threshold: int) -> list[str]:
    reasons: list[str] = []
    expires_at = value.get("expires_at")
    if expires_at is not None:
        try:
            if parse_timestamp(expires_at, "expires_at") <= as_of:
                reasons.append("EXPIRED")
        except DashboardError:
            reasons.append("INVALID_EXPIRY")
    timestamp = None
    for key in ("updated_at", "created_at", "inspected_at", "timestamp", "acquired_at"):
        if value.get(key) is not None:
            timestamp = value.get(key)
            break
    if timestamp is None:
        reasons.append("MISSING_TIMESTAMP")
    else:
        try:
            age = as_of - parse_timestamp(timestamp, key)
            if age > timedelta(seconds=threshold):
                reasons.append("OLDER_THAN_THRESHOLD")
        except DashboardError:
            reasons.append("INVALID_TIMESTAMP")
    return sorted(set(reasons))


def evidence(path: str, value: dict[str, Any], as_of: datetime, threshold: int, keys: set[str]) -> dict[str, Any]:
    reasons = stale_reasons(value, as_of, threshold)
    return {
        "path": path,
        "data": redact(value, keys),
        "stale": bool(reasons),
        "stale_reasons": reasons,
    }


def collect_files(root: Path, prefix: str, name: str) -> list[tuple[str, Path]]:
    base = root / prefix
    if not base.is_dir():
        return []
    return [(f"{prefix}/{path.name}/{name}", path / name) for path in sorted(base.iterdir()) if path.is_dir() and (path / name).is_file()]


def collect_dashboard(project_root: Path, as_of_value: str, config_path: str | None) -> dict[str, Any]:
    root = (project_root / ".agent").resolve()
    if not root.is_dir():
        raise DashboardError(".agent runtime is missing")
    as_of = parse_timestamp(as_of_value, "as_of")
    keys, threshold, configured = load_config(config_path)
    sources: dict[str, str] = {}
    diagnostics: list[dict[str, str]] = []

    state = read_json_object(root, "runtime/state.json", sources, diagnostics) or {}
    queue = read_json_object(root, "runtime/queue.json", sources, diagnostics) or {}
    events = read_json_lines(root, "runtime/events.jsonl", sources, diagnostics)
    state_item = evidence("runtime/state.json", state, as_of, threshold, keys)
    queue_item = evidence("runtime/queue.json", queue, as_of, threshold, keys)

    task_items: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    lease_items: list[dict[str, Any]] = []
    for relative, path in collect_files(root, "work", "task-state.json"):
        value = read_json_object(root, relative, sources, diagnostics)
        if value is not None:
            task_items.append(evidence(relative, value, as_of, threshold, keys))
    for relative, path in collect_files(root, "work", "review.json"):
        value = read_json_object(root, relative, sources, diagnostics)
        if value is not None:
            review_items.append(evidence(relative, value, as_of, threshold, keys))
    for relative, path in collect_files(root, "work", "lease.json"):
        value = read_json_object(root, relative, sources, diagnostics)
        if value is not None:
            lease_items.append(evidence(relative, value, as_of, threshold, keys))

    lock_items: list[dict[str, Any]] = []
    for kind in ("tasks", "files", "resources"):
        directory = root / "locks" / kind
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            relative = relative_path(root, path)
            value = read_json_object(root, relative, sources, diagnostics)
            if value is not None:
                lock_items.append(evidence(relative, value, as_of, threshold, keys))

    recovery_items: list[dict[str, Any]] = []
    for path in sorted((root / "recovery").glob("*.json")) if (root / "recovery").is_dir() else []:
        relative = relative_path(root, path)
        value = read_json_object(root, relative, sources, diagnostics)
        if value is not None:
            recovery_items.append(evidence(relative, value, as_of, threshold, keys))

    event_items = [
        {
            "path": f"runtime/events.jsonl:{index}",
            "data": redact(event, keys),
            "stale": bool(stale_reasons(event, as_of, threshold)),
            "stale_reasons": stale_reasons(event, as_of, threshold),
        }
        for index, event in enumerate(events, start=1)
    ]
    queue_tasks = queue.get("tasks", []) if isinstance(queue.get("tasks"), list) else []
    queue_dispatches = queue.get("dispatches", []) if isinstance(queue.get("dispatches"), list) else []
    queue_task_items = [
        evidence(f"runtime/queue.json:tasks[{index}]", value, as_of, threshold, keys)
        for index, value in enumerate(queue_tasks)
        if isinstance(value, dict)
    ]
    queue_dispatch_items = [
        evidence(f"runtime/queue.json:dispatches[{index}]", value, as_of, threshold, keys)
        for index, value in enumerate(queue_dispatches)
        if isinstance(value, dict)
    ]
    events_view = {"items": event_items, "count": len(event_items)}
    snapshot = {
        "schema_version": 1,
        "as_of": as_of.isoformat().replace("+00:00", "Z"),
        "stale_after_seconds": threshold,
        "source": {
            "runtime_revision": state.get("revision", 0) if isinstance(state.get("revision", 0), int) and not isinstance(state.get("revision", 0), bool) else 0,
            "files": [{"path": path, "sha256": digest} for path, digest in sorted(sources.items())],
        },
        "redaction": {
            "configured_keys": configured,
            "effective_keys": sorted(keys),
            "replacement": REDACTED,
        },
        "views": {
            "queue": {"queue": queue_item, "tasks": queue_task_items, "dispatches": queue_dispatch_items, "task_states": task_items},
            "state_history": {"snapshot": state_item, "events": event_items},
            "reviews": {"items": review_items},
            "locks": {"items": lock_items},
            "leases": {"items": lease_items},
            "recovery": {"items": recovery_items},
            "events": events_view,
        },
        "diagnostics": sorted(diagnostics, key=lambda item: (item["code"], item["path"], item["detail"])),
    }
    snapshot = redact_value(snapshot)
    validate_snapshot(snapshot)
    return snapshot


def write_external(path: Path, content: str, runtime_root: Path) -> None:
    target = path.resolve()
    if target == runtime_root or runtime_root in target.parents:
        raise DashboardError("output must be outside .agent")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--config")
    parser.add_argument("--as-of")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        project_root = Path(args.project_root).resolve()
        as_of = args.as_of or utc_now()
        snapshot = collect_dashboard(project_root, as_of, args.config)
        content = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            write_external(Path(args.output), content, (project_root / ".agent").resolve())
        print(content, end="")
        return 0
    except (DashboardError, OSError, TypeError, ValueError) as exc:
        print(f"DASHBOARD_REJECTED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
