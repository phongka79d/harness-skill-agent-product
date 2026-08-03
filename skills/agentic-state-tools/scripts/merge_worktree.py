"""Merge an isolated worktree with conflict fencing and guarded cleanup state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from worktree_manager import WorktreeError, WorktreeManager, _now, _run_git, _timestamp, _write_atomic


def _conflict_record(
    manager: WorktreeManager,
    entry: dict[str, Any],
    target_branch: str,
    output: str,
) -> dict[str, Any]:
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
    authorized: bool = False,
) -> dict[str, Any]:
    """Merge one clean source worktree into the checked-out target branch."""

    if not authorized:
        raise PermissionError("primary authorization is required to merge a worktree")
    manager = WorktreeManager(project_root, worktree_root)
    with manager.workspace_lock():
        entry = manager.get(task_id, revision)
        if entry.get("status") in {"STALE", "RECOVERY_PENDING", "ACCEPTED", "CANCELLED"}:
            raise WorktreeError(f"worktree is not mergeable in status {entry.get('status')}")
        isolation = manager.validate_isolation(task_id, revision)
        if isolation["branch"] != entry["branch"]:
            raise WorktreeError("source worktree branch does not match its mapping")
        source = Path(isolation["path"])
        current_branch = _run_git(manager.project_root, "branch", "--show-current")
        if current_branch.returncode or current_branch.stdout.strip() != target_branch:
            raise WorktreeError("target workspace must have the requested branch checked out")
        target_status = _run_git(manager.project_root, "status", "--porcelain", "--untracked-files=all")
        source_status = _run_git(source, "status", "--porcelain", "--untracked-files=all")
        if (
            target_status.returncode
            or target_status.stdout.strip()
            or source_status.returncode
            or source_status.stdout.strip()
        ):
            raise WorktreeError("merge requires clean target and source workspaces")
        target_head = _run_git(manager.project_root, "rev-parse", "HEAD")
        if target_head.returncode:
            detail = target_head.stderr.strip() or target_head.stdout.strip() or "unable to resolve target HEAD"
            raise WorktreeError(f"target workspace HEAD is invalid: {detail}")
        preview = _run_git(
            manager.project_root,
            "merge-tree",
            "--write-tree",
            target_head.stdout.strip(),
            entry["branch"],
        )
        if preview.returncode:
            output = (preview.stdout + "\n" + preview.stderr).strip()
            return _conflict_record(manager, entry, target_branch, output)
        merge = _run_git(manager.project_root, "merge", "--no-ff", "--no-edit", entry["branch"])
        if merge.returncode:
            output = (merge.stdout + "\n" + merge.stderr).strip()
            return _conflict_record(manager, entry, target_branch, output)
        return manager._set_entry_locked(task_id, revision, {"status": "MERGED", "merged_into": target_branch})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--worktree-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--revision", required=True, type=int)
    parser.add_argument("--target-branch", required=True)
    parser.add_argument("--authorized", action="store_true")
    args = parser.parse_args()
    try:
        result = merge_worktree(
            args.project_root,
            args.worktree_root,
            args.task_id,
            args.revision,
            args.target_branch,
            authorized=args.authorized,
        )
    except (OSError, ValueError, TypeError, WorktreeError, PermissionError) as exc:
        print(f"MERGE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
