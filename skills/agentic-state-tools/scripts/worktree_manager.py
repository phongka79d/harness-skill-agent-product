"""Create and validate isolated Git worktrees for asynchronous tasks."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from runtime_utils import process_is_alive
from validate_payload import validate
from write_artifact import write_validated


class WorktreeError(ValueError):
    """The requested worktree operation is unsafe or invalid."""


class WorkspaceBusy(WorktreeError):
    """Another worktree operation owns the workspace lock."""


class StaleMetadata(WorktreeError):
    """A persisted mapping no longer describes a live worktree."""


class CleanupBlocked(WorktreeError):
    """Cleanup would discard an active lease or uncommitted changes."""


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "worktree.schema.json"
ISOLATION_PROOF_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "isolation-proof.schema.json"
DELIVERY_DECISION_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "delivery-decision.schema.json"
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
BASELINE_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
BASELINE_STATUSES = {"CLEAN", "KNOWN_FAILURES_APPROVED", "BLOCKED"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _run_git(cwd: Path, *arguments: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorktreeError(f"git command failed: git {' '.join(arguments)}") from exc
    return result


def _require_git(cwd: Path, *arguments: str) -> str:
    result = _run_git(cwd, *arguments)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise WorktreeError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout.strip()


def _worktree_records(project_root: Path) -> list[dict[str, str]]:
    output = _require_git(project_root, "worktree", "list", "--porcelain")
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in output.splitlines():
        if line.startswith("worktree "):
            if current is not None:
                records.append(current)
            current = {"path": str(Path(line[9:]).resolve())}
        elif current is not None and line.startswith("branch "):
            current["branch"] = line[7:].removeprefix("refs/heads/")
    if current is not None:
        records.append(current)
    return records


def _validate_task_revision(task_id: str, revision: int) -> None:
    if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
        raise WorktreeError("task_id must contain only letters, numbers, dot, underscore, or hyphen")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise WorktreeError("revision must be a positive integer")


def _baseline_updates(entry: dict[str, Any], baseline: dict[str, Any], baseline_path: str | Path | None = None) -> dict[str, Any]:
    """Validate and project a baseline artifact onto a worktree registry entry."""

    if not isinstance(baseline, dict):
        raise WorktreeError("workspace baseline must be an object")
    status = baseline.get("status")
    if status not in BASELINE_STATUSES:
        raise WorktreeError("workspace baseline has an unsupported status")
    if status == "BLOCKED":
        raise WorktreeError("a BLOCKED workspace baseline cannot authorize implementation")
    if baseline.get("task_id") != entry.get("task_id"):
        raise WorktreeError("workspace baseline task identity does not match the worktree")
    baseline_path_value = baseline.get("worktree_path")
    if (
        not isinstance(baseline_path_value, str)
        or Path(baseline_path_value).expanduser().is_symlink()
        or Path(baseline_path_value).expanduser().resolve() != Path(str(entry.get("path"))).expanduser().resolve()
    ):
        raise WorktreeError("workspace baseline worktree path does not match the registry")
    for baseline_field, entry_field in (("branch", "branch"), ("base_commit", "base_commit")):
        if baseline.get(baseline_field) != entry.get(entry_field):
            raise WorktreeError(f"workspace baseline {baseline_field} does not match the registry")
    baseline_id = baseline.get("baseline_id")
    run_id = baseline.get("run_id")
    workspace_hash = baseline.get("workspace_hash")
    captured_at = baseline.get("captured_at")
    if not isinstance(baseline_id, str) or not baseline_id.strip():
        raise WorktreeError("workspace baseline baseline_id is required")
    if not isinstance(run_id, str) or not run_id.strip():
        raise WorktreeError("workspace baseline run_id is required")
    if not isinstance(workspace_hash, str) or BASELINE_HASH_PATTERN.fullmatch(workspace_hash) is None:
        raise WorktreeError("workspace baseline workspace_hash must be a lowercase SHA-256 hash")
    if not isinstance(captured_at, str) or not captured_at.strip():
        raise WorktreeError("workspace baseline captured_at is required")
    updates: dict[str, Any] = {
        "baseline_id": baseline_id,
        "baseline_run_id": run_id,
        "baseline_branch": baseline.get("branch"),
        "baseline_base_commit": baseline.get("base_commit"),
        "baseline_workspace_hash": workspace_hash,
        "baseline_status": status,
        "baseline_captured_at": captured_at,
    }
    if baseline_path is not None:
        updates["baseline_path"] = str(Path(baseline_path).expanduser().resolve())
    return updates


def _delivery_cleanup_context(project_root: Path, entry: dict[str, Any]) -> tuple[Path, dict[str, Any]] | None:
    """Load a finalizer decision when a worktree is being cleaned."""

    decision_path = project_root / ".agent" / "work" / str(entry.get("task_id")) / "delivery-decision.json"
    if not decision_path.is_file():
        if entry.get("baseline_id"):
            raise CleanupBlocked("worktree baseline requires a persisted delivery decision before cleanup")
        return None
    if decision_path.is_symlink():
        raise CleanupBlocked("delivery decision must not be a symlink")
    try:
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CleanupBlocked("delivery decision is unreadable") from exc
    if not isinstance(decision, dict) or decision.get("task_id") != entry.get("task_id"):
        raise CleanupBlocked("delivery decision task identity does not match the worktree")
    if decision.get("status") not in {"RECORDED", "COMPLETED"}:
        raise CleanupBlocked("delivery decision is not recorded as a successful decision")
    if decision.get("outcome") not in {"MERGE_LOCAL", "DISCARD_BRANCH_AND_WORKTREE"}:
        raise CleanupBlocked("delivery outcome does not authorize worktree cleanup")
    if decision.get("branch_name") != entry.get("branch") or decision.get("base_commit") != entry.get("base_commit"):
        raise CleanupBlocked("delivery decision branch or base commit does not match the worktree")
    try:
        decision_path_value = Path(str(decision["worktree_path"])).expanduser().resolve()
        entry_path = Path(str(entry["path"])).expanduser().resolve()
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise CleanupBlocked("delivery decision worktree path is invalid") from exc
    if decision_path_value != entry_path:
        raise CleanupBlocked("delivery decision worktree path does not match the registry")
    cleanup = decision.get("cleanup")
    if not isinstance(cleanup, dict) or cleanup.get("requested") is not True or cleanup.get("identity_proven") is not True:
        raise CleanupBlocked("delivery decision does not request identity-proven cleanup")
    if cleanup.get("status") not in {"PENDING", "CLEANED"}:
        raise CleanupBlocked("delivery decision cleanup is not pending or completed")
    approval = decision.get("approval")
    if not isinstance(approval, dict) or approval.get("decision") != "APPROVED":
        raise CleanupBlocked("delivery cleanup requires an approved decision")
    if decision.get("outcome") == "DISCARD_BRANCH_AND_WORKTREE" and approval.get("actor_type") != "user":
        raise CleanupBlocked("discard cleanup requires a user approval")
    return decision_path, decision


def _persist_cleanup_evidence(project_root: Path, decision_path: Path, decision: dict[str, Any], entry: dict[str, Any]) -> None:
    cleanup = dict(decision["cleanup"])
    cleanup.update(
        {
            "status": "CLEANED",
            "operation_id": f"CLEANUP-{entry['task_id']}-{entry['revision']}",
            "recorded_at": _timestamp(_now()),
        }
    )
    updated = dict(decision)
    updated["cleanup"] = cleanup
    current_revision = int(updated.get("revision", 1))
    updated["previous_revision"] = current_revision
    updated["revision"] = current_revision + 1
    relative = decision_path.resolve().relative_to((project_root / ".agent").resolve()).as_posix()
    write_validated(str(project_root), relative, updated, DELIVERY_DECISION_SCHEMA_PATH)


class WorktreeManager:
    """Own the registry, lock, and guarded Git operations for one workspace."""

    def __init__(self, project_root: str | Path, configured_root: str | Path, *, lease_seconds: int = 3600) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds <= 0:
            raise WorktreeError("lease_seconds must be a positive integer")
        detected_root = Path(_require_git(self.project_root, "rev-parse", "--show-toplevel")).resolve()
        if detected_root != self.project_root:
            raise WorktreeError("project_root must be the top-level Git workspace")
        root = Path(configured_root).expanduser()
        self.configured_root = (self.project_root / root if not root.is_absolute() else root).resolve()
        if self.configured_root == self.project_root or self.project_root in self.configured_root.parents:
            raise WorktreeError("configured worktree root must be outside the project workspace")
        self.configured_root.mkdir(parents=True, exist_ok=True)
        self.worktree_root = self.configured_root / "worktrees"
        self.metadata_path = self.configured_root / ".worktree-state.json"
        self.lock_path = self.configured_root / ".workspace.lock"
        self.recovery_root = self.configured_root / "recovery"
        self.lease_seconds = lease_seconds

    @property
    def schema_path(self) -> Path:
        return SCHEMA_PATH

    def _empty_state(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "project_root": str(self.project_root),
            "worktree_root": str(self.worktree_root),
            "entries": {},
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.metadata_path.exists():
            return self._empty_state()
        try:
            value = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WorktreeError("worktree metadata is unreadable") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("project_root") != str(self.project_root):
            raise WorktreeError("worktree metadata has an invalid workspace binding")
        if value.get("worktree_root") != str(self.worktree_root) or not isinstance(value.get("entries"), dict):
            raise WorktreeError("worktree metadata has an invalid registry")
        self._validate_state(value)
        return value

    @staticmethod
    def _validate_state(state: dict[str, Any]) -> None:
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WorktreeError("worktree schema is unreadable") from exc
        errors = validate(state, schema, base_path=SCHEMA_PATH.parent)
        if errors:
            raise WorktreeError("worktree metadata violates its schema: " + "; ".join(errors))

    def _save_state(self, state: dict[str, Any]) -> None:
        self._validate_state(state)
        _write_atomic(self.metadata_path, state)

    @staticmethod
    def _key(task_id: str, revision: int) -> str:
        return f"{task_id}@{revision}"

    @staticmethod
    def _slug(task_id: str) -> str:
        return task_id.lower().replace("_", "-")

    def _lease(self, expires_at: datetime | None = None) -> dict[str, str]:
        expires = expires_at or (_now() + timedelta(seconds=self.lease_seconds))
        return {"expires_at": _timestamp(expires)}

    @staticmethod
    def _lease_live(entry: dict[str, Any], now: datetime | None = None) -> bool:
        lease = entry.get("lease")
        if lease is None:
            return False
        try:
            return _parse_timestamp(str(lease["expires_at"])) > (now or _now())
        except (KeyError, TypeError, ValueError):
            raise WorktreeError("worktree lease metadata is invalid")

    def _entry_is_live(self, entry: dict[str, Any]) -> bool:
        path = Path(str(entry.get("path", ""))).resolve()
        branch = str(entry.get("branch", ""))
        return path.is_dir() and any(record.get("path") == str(path) and record.get("branch") == branch for record in _worktree_records(self.project_root))

    def _unique_names(self, task_id: str, revision: int, entries: dict[str, Any]) -> tuple[Path, str]:
        digest = uuid.uuid5(uuid.NAMESPACE_URL, f"{self.project_root}:{task_id}:{revision}").hex[:10]
        stem = f"task-{self._slug(task_id)}-r{revision}-{digest}"
        used_paths = {str(Path(item.get("path", "")).resolve()) for item in entries.values() if isinstance(item, dict)}
        used_branches = {str(item.get("branch", "")) for item in entries.values() if isinstance(item, dict)}
        suffix = ""
        counter = 0
        while True:
            path = (self.worktree_root / f"{stem}{suffix}").resolve()
            branch = f"async/{self._slug(task_id)}/r{revision}-{digest}{suffix}"
            if str(path) not in used_paths and branch not in used_branches and not path.exists() and not _run_git(self.project_root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
                return path, branch
            counter += 1
            suffix = f"-g{counter}"

    @contextmanager
    def workspace_lock(self) -> Iterator[None]:
        self.configured_root.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(str(self.lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError as exc:
            if not self._reclaim_stale_lock():
                raise WorkspaceBusy("worktree workspace lock is held") from exc
            try:
                descriptor = os.open(str(self.lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except FileExistsError as retry_exc:
                raise WorkspaceBusy("worktree workspace lock is held") from retry_exc
        try:
            acquired_at = _now()
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    {
                        "pid": os.getpid(),
                        "acquired_at": _timestamp(acquired_at),
                        "expires_at": _timestamp(acquired_at + timedelta(seconds=self.lease_seconds)),
                    },
                    handle,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            yield
        finally:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def _reclaim_stale_lock(self) -> bool:
        """Remove a workspace lock only after proving its owner is dead and stale."""

        try:
            metadata = json.loads(self.lock_path.read_text(encoding="utf-8"))
            pid = metadata.get("pid") if isinstance(metadata, dict) else None
            if isinstance(pid, bool) or not isinstance(pid, int) or process_is_alive(pid):
                return False
            now = _now()
            expires_at = metadata.get("expires_at")
            acquired_at = metadata.get("acquired_at")
            if isinstance(expires_at, str):
                stale = _parse_timestamp(expires_at) <= now
            elif isinstance(acquired_at, str):
                stale = _parse_timestamp(acquired_at) + timedelta(seconds=self.lease_seconds) <= now
            else:
                stale = False
            if not stale:
                return False
        except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
            return False
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            return True
        return True

    def create(
        self,
        task_id: str,
        revision: int,
        *,
        base_ref: str = "HEAD",
        baseline: dict[str, Any] | None = None,
        baseline_path: str | Path | None = None,
    ) -> dict[str, Any]:
        _validate_task_revision(task_id, revision)
        with self.workspace_lock():
            state = self._load_state()
            key = self._key(task_id, revision)
            existing = state["entries"].get(key)
            if isinstance(existing, dict):
                if existing.get("status") == "STALE":
                    pass
                elif self._entry_is_live(existing):
                    if baseline is None:
                        return copy.deepcopy(existing)
                    updates = _baseline_updates(existing, baseline, baseline_path)
                    existing.update(updates)
                    existing["updated_at"] = _timestamp(_now())
                    state["entries"][key] = existing
                    self._save_state(state)
                    return copy.deepcopy(existing)
                elif self._lease_live(existing):
                    raise StaleMetadata("live lease points to missing or mismatched worktree")
                else:
                    raise StaleMetadata("stale metadata requires explicit reclaim")
            base_commit = _require_git(self.project_root, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
            path, branch = self._unique_names(task_id, revision, state["entries"])
            path.parent.mkdir(parents=True, exist_ok=True)
            result = _run_git(self.project_root, "worktree", "add", "-b", branch, str(path), base_ref)
            if result.returncode:
                detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
                raise WorktreeError(f"git worktree add failed: {detail}")
            old = existing if isinstance(existing, dict) else None
            entry = {
                "task_id": task_id,
                "revision": revision,
                "path": str(path),
                "branch": branch,
                "base_commit": base_commit,
                "status": "ACTIVE",
                "lease": self._lease(),
                "created_at": _timestamp(_now()),
                "updated_at": _timestamp(_now()),
            }
            if old is not None:
                entry["reclaimed_from"] = old.get("branch")
            if baseline is not None:
                entry.update(_baseline_updates(entry, baseline, baseline_path))
            state["entries"][key] = entry
            self._save_state(state)
            return copy.deepcopy(entry)

    def get(self, task_id: str, revision: int) -> dict[str, Any]:
        _validate_task_revision(task_id, revision)
        entry = self._load_state()["entries"].get(self._key(task_id, revision))
        if not isinstance(entry, dict):
            raise WorktreeError(f"worktree mapping does not exist: {task_id}@{revision}")
        return copy.deepcopy(entry)

    def validate_isolation(self, task_id: str, revision: int, *, require_baseline: bool = False) -> dict[str, Any]:
        entry = self.get(task_id, revision)
        if entry.get("status") in {"STALE", "RECOVERY_PENDING"} or not self._entry_is_live(entry):
            raise StaleMetadata("worktree isolation is not currently valid")
        if not self._lease_live(entry):
            raise StaleMetadata("worktree lease has expired")
        if require_baseline and entry.get("baseline_status") not in {"CLEAN", "KNOWN_FAILURES_APPROVED"}:
            raise StaleMetadata("worktree baseline evidence is missing or not approved")
        proof = {
            "validated_by": "worktree_manager",
            "project_root": str(self.project_root),
            "metadata_path": str(self.metadata_path),
            "task_id": task_id,
            "revision": revision,
            "path": entry["path"],
            "branch": entry["branch"],
        }
        if entry.get("baseline_id"):
            proof.update(
                {
                    "baseline_id": entry["baseline_id"],
                    "baseline_workspace_hash": entry.get("baseline_workspace_hash"),
                    "baseline_status": entry.get("baseline_status"),
                    "baseline_captured_at": entry.get("baseline_captured_at"),
                }
            )
        return proof

    def attach_baseline(
        self,
        task_id: str,
        revision: int,
        baseline: dict[str, Any],
        *,
        baseline_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Bind a captured baseline to an existing live worktree atomically."""

        _validate_task_revision(task_id, revision)
        with self.workspace_lock():
            state = self._load_state()
            key = self._key(task_id, revision)
            entry = state["entries"].get(key)
            if not isinstance(entry, dict):
                raise WorktreeError(f"worktree mapping does not exist: {task_id}@{revision}")
            if not self._entry_is_live(entry):
                raise StaleMetadata("cannot attach a baseline to a non-live worktree")
            entry.update(_baseline_updates(entry, baseline, baseline_path))
            entry["updated_at"] = _timestamp(_now())
            state["entries"][key] = entry
            self._save_state(state)
            return copy.deepcopy(entry)

    def reclaim(self, task_id: str, revision: int, *, authorized: bool = False) -> dict[str, Any]:
        if not authorized:
            raise PermissionError("primary authorization is required to reclaim stale metadata")
        _validate_task_revision(task_id, revision)
        with self.workspace_lock():
            state = self._load_state()
            key = self._key(task_id, revision)
            entry = state["entries"].get(key)
            if not isinstance(entry, dict):
                raise WorktreeError(f"worktree mapping does not exist: {task_id}@{revision}")
            if self._entry_is_live(entry):
                raise WorktreeError("cannot reclaim a live worktree")
            if self._lease_live(entry):
                raise WorktreeError("cannot reclaim metadata with a live lease")
            entry["status"] = "STALE"
            entry["stale_at"] = _timestamp(_now())
            entry["updated_at"] = _timestamp(_now())
            entry["stale_reason"] = "mapping no longer matches Git worktree state"
            state["entries"][key] = entry
            self._save_state(state)
            return copy.deepcopy(entry)

    def set_status(self, task_id: str, revision: int, status: str) -> dict[str, Any]:
        if status not in {"ACTIVE", "ACCEPTED", "CANCELLED", "RECOVERY_PENDING", "MERGED"}:
            raise WorktreeError("unsupported worktree status")
        with self.workspace_lock():
            state = self._load_state()
            key = self._key(task_id, revision)
            entry = state["entries"].get(key)
            if not isinstance(entry, dict):
                raise WorktreeError(f"worktree mapping does not exist: {task_id}@{revision}")
            entry["status"] = status
            entry["updated_at"] = _timestamp(_now())
            self._save_state(state)
            return copy.deepcopy(entry)

    def release_lease(self, task_id: str, revision: int) -> dict[str, Any]:
        with self.workspace_lock():
            state = self._load_state()
            entry = state["entries"].get(self._key(task_id, revision))
            if not isinstance(entry, dict):
                raise WorktreeError(f"worktree mapping does not exist: {task_id}@{revision}")
            entry["lease"] = None
            entry["updated_at"] = _timestamp(_now())
            self._save_state(state)
            return copy.deepcopy(entry)

    def _set_entry_locked(self, task_id: str, revision: int, updates: dict[str, Any]) -> dict[str, Any]:
        state = self._load_state()
        entry = state["entries"].get(self._key(task_id, revision))
        if not isinstance(entry, dict):
            raise WorktreeError(f"worktree mapping does not exist: {task_id}@{revision}")
        entry.update(updates)
        entry["updated_at"] = _timestamp(_now())
        state["entries"][self._key(task_id, revision)] = entry
        self._save_state(state)
        return copy.deepcopy(entry)

    def cleanup(self, task_id: str, revision: int) -> dict[str, Any]:
        with self.workspace_lock():
            state = self._load_state()
            entry = state["entries"].get(self._key(task_id, revision))
            if not isinstance(entry, dict):
                raise WorktreeError(f"worktree mapping does not exist: {task_id}@{revision}")
            if entry.get("status") not in {"ACCEPTED", "CANCELLED", "MERGED"}:
                raise CleanupBlocked("cleanup requires an accepted or cancelled task")
            if self._lease_live(entry):
                raise CleanupBlocked("cleanup is blocked by an active lease")
            plan_revision = entry.get("plan_revision")
            superseding_revision = entry.get("superseding_plan_revision") or entry.get("superseded_by_plan_revision") or entry.get("current_plan_revision")
            if isinstance(plan_revision, int) and isinstance(superseding_revision, int) and superseding_revision > plan_revision:
                raise CleanupBlocked("cleanup is blocked by a superseding plan revision")
            delivery_context = _delivery_cleanup_context(self.project_root, entry)
            path = Path(str(entry["path"])).expanduser().resolve()
            try:
                path.relative_to(self.worktree_root)
            except ValueError as exc:
                raise CleanupBlocked("cleanup path is outside configured worktree root") from exc
            if path.exists():
                changes = _require_git(path, "status", "--porcelain", "--untracked-files=all")
                unmerged = _require_git(path, "ls-files", "-u")
                if changes or unmerged:
                    raise CleanupBlocked("cleanup would discard uncommitted or unmerged changes")
                branch_head = _require_git(path, "rev-parse", "HEAD")
                reconciled = _run_git(self.project_root, "merge-base", "--is-ancestor", branch_head, "HEAD")
                if reconciled.returncode:
                    raise CleanupBlocked("cleanup is blocked by a branch commit not reconciled into the target")
                result = _run_git(self.project_root, "worktree", "remove", str(path))
                if result.returncode:
                    detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
                    raise CleanupBlocked(f"git worktree remove refused cleanup: {detail}")
            if delivery_context is not None:
                try:
                    _persist_cleanup_evidence(self.project_root, delivery_context[0], delivery_context[1], entry)
                except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise CleanupBlocked("worktree cleanup completed but delivery evidence could not be persisted") from exc
            entry["cleaned_at"] = _timestamp(_now())
            entry["updated_at"] = _timestamp(_now())
            state["entries"][self._key(task_id, revision)] = entry
            self._save_state(state)
            return copy.deepcopy(entry)


def validate_canonical_isolation_proof(task: dict[str, Any], proof: Any) -> bool:
    """Validate the exact proof contract used by async execution resolution."""

    if not isinstance(task, dict) or not isinstance(proof, dict):
        return False
    try:
        schema = json.loads(ISOLATION_PROOF_SCHEMA_PATH.read_text(encoding="utf-8"))
        errors = validate(proof, schema, base_path=ISOLATION_PROOF_SCHEMA_PATH.parent)
        if errors:
            return False
        _parse_timestamp(proof["active_conflicts_checked_at"])
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if proof.get("baseline_status") == "BLOCKED":
        return False
    if proof.get("baseline_id") is not None and any(
        proof.get(field) is None
        for field in ("baseline_workspace_hash", "baseline_status", "baseline_captured_at")
    ):
        return False
    for field in (
        "task_id",
        "run_id",
        "worktree_path",
        "branch_name",
        "plan_revision",
        "write_scope_hash",
        "baseline_id",
        "baseline_workspace_hash",
        "baseline_status",
        "baseline_captured_at",
    ):
        if field in task and task.get(field) is not None and task.get(field) != proof.get(field):
            return False
    if task.get("baseline_required") is True:
        if proof.get("baseline_id") is None or proof.get("baseline_status") not in {"CLEAN", "KNOWN_FAILURES_APPROVED"}:
            return False
    return True


def validate_isolation_proof(task: dict[str, Any], proof: Any) -> bool:
    """Accept canonical proofs and retain compatibility with manager-issued proofs."""

    if validate_canonical_isolation_proof(task, proof):
        return True

    if not isinstance(task, dict) or not isinstance(proof, dict):
        return False
    if proof.get("validated_by") != "worktree_manager" or proof.get("task_id") != task.get("task_id") or proof.get("revision") != task.get("revision"):
        return False
    try:
        metadata_path = Path(str(proof["metadata_path"])).expanduser().resolve()
        state = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            return False
        manager = WorktreeManager(proof["project_root"], Path(state["worktree_root"]).parent)
        manager._validate_state(state)
        entry = state["entries"][f"{proof['task_id']}@{proof['revision']}"]
        if entry.get("path") != proof.get("path") or entry.get("branch") != proof.get("branch"):
            return False
        for field in ("baseline_id", "baseline_workspace_hash", "baseline_status", "baseline_captured_at"):
            if field in proof and proof.get(field) != entry.get(field):
                return False
        if proof.get("baseline_status") == "BLOCKED":
            return False
        if task.get("baseline_required") is True and entry.get("baseline_status") not in {"CLEAN", "KNOWN_FAILURES_APPROVED"}:
            return False
        if entry.get("status") in {"STALE", "RECOVERY_PENDING"} or not manager._entry_is_live(entry) or not manager._lease_live(entry):
            return False
        return True
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, WorktreeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--worktree-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--revision", required=True, type=int)
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--baseline")
    parser.add_argument("--baseline-path")
    parser.add_argument("--reclaim", action="store_true")
    parser.add_argument("--authorized", action="store_true")
    args = parser.parse_args()
    try:
        manager = WorktreeManager(args.project_root, args.worktree_root)
        if args.reclaim:
            result = manager.reclaim(args.task_id, args.revision, authorized=args.authorized)
        else:
            baseline = None
            if args.baseline:
                baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
            result = manager.create(
                args.task_id,
                args.revision,
                base_ref=args.base_ref,
                baseline=baseline,
                baseline_path=args.baseline_path,
            )
    except (OSError, ValueError, TypeError, WorktreeError, PermissionError) as exc:
        print(f"WORKTREE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
