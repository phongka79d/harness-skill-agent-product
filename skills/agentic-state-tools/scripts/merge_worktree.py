"""Merge an async worktree only with a current, persisted typed approval."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from authorization import AuthorizationError, authorize, require_persisted_approval
from runtime_utils import read_object, read_payload
from worktree_manager import WorktreeError, WorktreeManager, _now, _run_git, _timestamp, _write_atomic


ACTION_NAMES = {"WORKTREE_MERGE", "MERGE_WORKTREE"}
IDENTITY_FIELDS = ("run_id", "attempt_id", "dispatch_id")


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _runtime_root(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve() / ".agent"


def _read_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = read_object(path)
    return value if isinstance(value, dict) else None


def _queue_binding(queue: dict[str, Any], task_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    tasks = queue.get("tasks", [])
    dispatches = queue.get("dispatches", [])
    task_entry = next((item for item in tasks if isinstance(item, dict) and item.get("task_id") == task_id), None)
    dispatch = next((item for item in dispatches if isinstance(item, dict) and item.get("task_id") == task_id), None)
    if task_entry is None or dispatch is None:
        raise WorktreeError("async merge requires queue and dispatch identity")
    return task_entry, dispatch


def _load_merge_artifacts(project_root: str | Path, task_id: str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = _runtime_root(project_root)
    task_path = root / "work" / task_id / "task-state.json"
    if not task_path.is_file():
        raise WorktreeError(f"task state does not exist for {task_id}")
    task = read_object(task_path)
    if not isinstance(task, dict):
        raise WorktreeError("task state must be an object")
    queue = read_object(root / "runtime" / "queue.json")
    if not isinstance(queue, dict):
        raise WorktreeError("runtime queue must be an object")
    queue_entry, dispatch = _queue_binding(queue, task_id)
    review = _read_optional(root / "work" / task_id / "review.json") or {}
    return root, task, queue_entry, dispatch, review


def _batch_contract(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    batch_id = task.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise WorktreeError("async merge requires batch membership")
    path = root / "work" / batch_id / "batch-contract.json"
    contract = _read_optional(path)
    if contract is None:
        raise WorktreeError("current batch contract is missing")
    pins = contract.get("tasks")
    if not isinstance(pins, list):
        raise WorktreeError("batch contract task pins are missing")
    pin = next((item for item in pins if isinstance(item, dict) and item.get("task_id") == task.get("task_id")), None)
    if pin is None:
        raise WorktreeError("task is not a member of the current batch contract")
    if pin.get("task_revision") != task.get("revision"):
        raise WorktreeError("batch contract task revision is stale")
    return contract


def _validate_identity(task: dict[str, Any], queue_entry: dict[str, Any], dispatch: dict[str, Any], lease: dict[str, Any] | None) -> None:
    for field in IDENTITY_FIELDS:
        value = task.get(field)
        if not isinstance(value, str) or not value.strip():
            raise WorktreeError(f"task {field} is required for async merge")
        for artifact_name, artifact in (("queue", queue_entry), ("dispatch", dispatch), ("lease", lease)):
            if artifact is not None and artifact.get(field) != value:
                raise WorktreeError(f"{artifact_name} {field} does not match task state")

    for field in ("worktree_path", "branch_name", "base_commit", "plan_revision"):
        expected = task.get(field)
        if expected is None:
            continue
        for artifact_name, artifact in (("queue", queue_entry), ("dispatch", dispatch), ("lease", lease)):
            if artifact_name == "lease" and artifact is not None and field not in artifact:
                continue
            if artifact is not None and artifact.get(field) != expected:
                raise WorktreeError(f"{artifact_name} {field} does not match task state")

    input_hashes = task.get("input_artifact_hashes")
    if input_hashes is not None and not isinstance(input_hashes, dict):
        raise WorktreeError("task input_artifact_hashes must be an object")
    for artifact_name, artifact in (("queue", queue_entry), ("dispatch", dispatch)):
        if input_hashes is not None:
            candidate = artifact.get("input_artifact_hashes", artifact.get("input_hashes"))
            if candidate is not None and candidate != input_hashes:
                raise WorktreeError(f"{artifact_name} input artifact hashes do not match task state")


def _review_verdict(task: dict[str, Any], review: dict[str, Any]) -> str:
    verdict = task.get("review_verdict") or review.get("verdict")
    if str(verdict).upper() != "PASS":
        raise WorktreeError("async merge requires a PASS task review")
    return "PASS"


def _source_commit(manager: WorktreeManager, entry: dict[str, Any]) -> str:
    source = Path(str(entry.get("path", ""))).resolve()
    if not source.is_dir():
        raise WorktreeError("source worktree does not exist")
    branch = _run_git(source, "branch", "--show-current")
    if branch.returncode or branch.stdout.strip() != entry.get("branch"):
        raise WorktreeError("source worktree branch does not match its mapping")
    head = _run_git(source, "rev-parse", "HEAD")
    if head.returncode:
        raise WorktreeError("source worktree HEAD is invalid")
    return head.stdout.strip()


def _target_commit(manager: WorktreeManager, target_branch: str) -> str:
    current_branch = _run_git(manager.project_root, "branch", "--show-current")
    if current_branch.returncode or current_branch.stdout.strip() != target_branch:
        raise WorktreeError("target workspace must have the requested branch checked out")
    target_head = _run_git(manager.project_root, "rev-parse", "HEAD")
    if target_head.returncode:
        raise WorktreeError("target workspace HEAD is invalid")
    return target_head.stdout.strip()


def _dirty_paths(path: Path, *, ignore_runtime: bool = False) -> list[str]:
    result = _run_git(path, "status", "--porcelain", "--untracked-files=all")
    if result.returncode:
        raise WorktreeError("unable to inspect workspace status")
    paths: list[str] = []
    for line in result.stdout.splitlines():
        value = line[3:] if len(line) >= 4 else line
        if ignore_runtime and (value == ".agent" or value.startswith(".agent/")):
            continue
        paths.append(value)
    return paths


def _merge_snapshot(
    task: dict[str, Any],
    entry: dict[str, Any],
    queue_entry: dict[str, Any],
    dispatch: dict[str, Any],
    review: dict[str, Any],
    batch: dict[str, Any],
    *,
    target_branch: str,
    source_commit: str,
    target_commit: str,
    target_type: str = "WORKTREE",
    target_revision: int | None = None,
) -> dict[str, Any]:
    snapshot = {
        "target_type": target_type,
        "target_id": task["task_id"],
        "revision": target_revision if target_revision is not None else entry["revision"],
        "task_revision": task.get("revision"),
        "task_id": task["task_id"],
        "plan_id": task.get("plan_id"),
        "plan_revision": task.get("plan_revision"),
        "batch_id": task.get("batch_id"),
        "run_id": task.get("run_id"),
        "attempt_id": task.get("attempt_id"),
        "dispatch_id": task.get("dispatch_id"),
        "source_branch": entry.get("branch"),
        "worktree_path": entry.get("path"),
        "base_commit": entry.get("base_commit"),
        "source_commit": source_commit,
        "target_branch": target_branch,
        "target_commit": target_commit,
        "review_verdict": str(task.get("review_verdict") or review.get("verdict") or "").upper(),
        "batch_contract_hash": batch.get("contract_hash"),
        "input_artifact_hashes": task.get("input_artifact_hashes", {}),
        "output_artifact_hashes": task.get("output_artifact_hashes", {}),
        "dispatch_artifact_hashes": dispatch.get("artifact_hashes", {}),
        "queue_artifact_hashes": queue_entry.get("input_hashes", queue_entry.get("input_artifact_hashes", {})),
    }
    return snapshot


def build_merge_authorization_target(
    project_root: str | Path,
    worktree_root: str | Path,
    task_id: str,
    revision: int,
    target_branch: str,
) -> dict[str, Any]:
    """Build the immutable snapshot that a WORKTREE_MERGE approval must pin."""

    manager = WorktreeManager(project_root, worktree_root)
    entry = manager.get(task_id, revision)
    root, task, queue_entry, dispatch, review = _load_merge_artifacts(project_root, task_id)
    lease = _read_optional(root / "work" / task_id / "lease.json")
    _validate_identity(task, queue_entry, dispatch, lease)
    batch = _batch_contract(root, task)
    _review_verdict(task, review)
    if task.get("worktree_path") != entry.get("path") or task.get("branch_name") != entry.get("branch"):
        raise WorktreeError("task worktree metadata does not match the worktree registry")
    if task.get("base_commit") is not None and task.get("base_commit") != entry.get("base_commit"):
        raise WorktreeError("task base_commit does not match the worktree registry")
    source_commit = _source_commit(manager, entry)
    target_commit = _target_commit(manager, target_branch)
    snapshot = _merge_snapshot(
        task,
        entry,
        queue_entry,
        dispatch,
        review,
        batch,
        target_branch=target_branch,
        source_commit=source_commit,
        target_commit=target_commit,
    )
    return {
        "target_type": "WORKTREE",
        "target_id": task_id,
        "revision": revision,
        "target_hash": _canonical_hash(snapshot),
        "snapshot": snapshot,
    }


def _approval_target(
    approval: dict[str, Any],
    worktree_target: dict[str, Any],
    task: dict[str, Any],
    entry: dict[str, Any],
    queue_entry: dict[str, Any],
    dispatch: dict[str, Any],
    review: dict[str, Any],
    batch: dict[str, Any],
) -> dict[str, Any]:
    target_type = str(approval.get("target_type", "")).upper()
    if target_type == "WORKTREE":
        return {key: worktree_target[key] for key in ("target_type", "target_id", "revision", "target_hash")}
    if target_type == "TASK":
        snapshot = dict(worktree_target["snapshot"])
        snapshot["target_type"] = "TASK"
        snapshot["revision"] = task.get("revision")
        return {
            "target_type": "TASK",
            "target_id": task["task_id"],
            "revision": task["revision"],
            "target_hash": _canonical_hash(snapshot),
        }
    raise AuthorizationError("merge approval target_type must be WORKTREE or TASK")


def _actor_identity(actor: str | dict[str, str], actor_type: str | None) -> dict[str, str]:
    if isinstance(actor, dict):
        identity = dict(actor)
        if actor_type is not None and identity.get("actor_type") != actor_type:
            raise AuthorizationError("actor_type does not match actor identity")
        return identity
    if not isinstance(actor, str) or not actor.strip() or not isinstance(actor_type, str) or not actor_type.strip():
        raise AuthorizationError("merge requires a typed actor")
    return {"actor_id": actor, "actor_type": actor_type}


def _conflict_record(manager: WorktreeManager, entry: dict[str, Any], target_branch: str, output: str) -> dict[str, Any]:
    manager.recovery_root.mkdir(parents=True, exist_ok=True)
    artifact = manager.recovery_root / f"RECOVERY_PENDING-{entry['task_id']}-{entry['revision']}.json"
    record = {
        "schema_version": 1,
        "status": "RECOVERY_PENDING",
        "task_id": entry["task_id"],
        "revision": entry["revision"],
        "source_branch": entry["branch"],
        "target_branch": target_branch,
        "conflict_output": output,
        "batch_blocked": True,
        "created_at": _timestamp(_now()),
    }
    _write_atomic(artifact, record)
    return manager._set_entry_locked(
        entry["task_id"],
        entry["revision"],
        {"status": "RECOVERY_PENDING", "conflict_artifact": str(artifact)},
    )


def merge_worktree(
    project_root: str | Path,
    worktree_root: str | Path,
    task_id: str,
    revision: int,
    target_branch: str,
    *,
    approval: dict[str, Any] | None,
    actor: str | dict[str, str],
    actor_type: str | None = None,
) -> dict[str, Any]:
    """Merge one clean source worktree after validating its persisted approval."""

    if approval is None:
        raise PermissionError("a persisted typed merge approval is required")
    if not isinstance(approval, dict):
        raise AuthorizationError("merge approval must be an object")
    manager = WorktreeManager(project_root, worktree_root)
    actor_identity = _actor_identity(actor, actor_type)
    with manager.workspace_lock():
        entry = manager.get(task_id, revision)
        if entry.get("status") in {"STALE", "RECOVERY_PENDING", "ACCEPTED", "CANCELLED", "MERGED"}:
            raise WorktreeError(f"worktree is not mergeable in status {entry.get('status')}")
        target = build_merge_authorization_target(project_root, worktree_root, task_id, revision, target_branch)
        root, task, queue_entry, dispatch, review = _load_merge_artifacts(project_root, task_id)
        lease = _read_optional(root / "work" / task_id / "lease.json")
        batch = _batch_contract(root, task)
        _validate_identity(task, queue_entry, dispatch, lease)
        _review_verdict(task, review)
        if task.get("worktree_path") != entry.get("path") or task.get("branch_name") != entry.get("branch"):
            raise WorktreeError("task worktree metadata does not match the worktree registry")
        expected_target = _approval_target(approval, target, task, entry, queue_entry, dispatch, review, batch)
        target_type = expected_target["target_type"]
        require_persisted_approval(root, approval, target_type=target_type, target_id=task_id)
        action = str(approval.get("action", "")).upper()
        if action not in ACTION_NAMES:
            raise AuthorizationError("merge approval action must be WORKTREE_MERGE")
        approval_id = authorize(action, expected_target, approval, actor=actor_identity)
        if _dirty_paths(manager.project_root, ignore_runtime=True):
            raise WorktreeError("merge requires a clean target workspace")
        source = Path(str(entry["path"])).resolve()
        if _dirty_paths(source):
            raise WorktreeError("merge requires a clean source workspace")
        target_commit = expected_target["target_hash"]
        preview = _run_git(manager.project_root, "merge-tree", "--write-tree", target["snapshot"]["target_commit"], entry["branch"])
        if preview.returncode:
            output = (preview.stdout + "\n" + preview.stderr).strip()
            result = _conflict_record(manager, entry, target_branch, output)
            result.update({"approval_id": approval_id, "target_hash": target_commit, "classification": "CONFLICTED"})
            return result
        merge = _run_git(manager.project_root, "merge", "--no-ff", "--no-edit", entry["branch"])
        if merge.returncode:
            output = (merge.stdout + "\n" + merge.stderr).strip()
            result = _conflict_record(manager, entry, target_branch, output)
            result.update({"approval_id": approval_id, "target_hash": target_commit, "classification": "CONFLICTED"})
            return result
        result = manager._set_entry_locked(task_id, revision, {"status": "MERGED", "merged_into": target_branch})
        result.update({
            "approval_id": approval_id,
            "target_hash": target_commit,
            "source_commit": target["snapshot"]["source_commit"],
            "target_commit": target["snapshot"]["target_commit"],
        })
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--worktree-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--revision", required=True, type=int)
    parser.add_argument("--target-branch", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--actor-type", required=True, choices=("user", "primary_agent", "agent", "service"))
    args = parser.parse_args()
    try:
        result = merge_worktree(
            args.project_root,
            args.worktree_root,
            args.task_id,
            args.revision,
            args.target_branch,
            approval=read_payload(args.approval),
            actor=args.actor,
            actor_type=args.actor_type,
        )
    except (OSError, ValueError, TypeError, WorktreeError, PermissionError) as exc:
        print(f"MERGE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
