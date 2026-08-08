"""Small, argv-only Git worktree operations and identity validation."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


class WorktreeError(ValueError):
    def __init__(self, message: str, action: str = "INSPECT_WORKTREE") -> None:
        super().__init__(message)
        self.action = action


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(root), text=True, capture_output=True, check=False
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise WorktreeError(detail)
    return result.stdout.strip()


def repo_top_level(root: str | Path) -> Path:
    project = Path(root).expanduser().resolve()
    if not project.is_dir() or project.is_symlink():
        raise WorktreeError("project root must be a real directory", "INSPECT_WORKTREE_PATH")
    if _git(project, "rev-parse", "--is-inside-work-tree") != "true":
        raise WorktreeError("project root is not inside a Git worktree", "INSPECT_WORKTREE_PATH")
    top = Path(_git(project, "rev-parse", "--show-toplevel")).resolve()
    if top != project:
        raise WorktreeError("Git top-level does not equal project root", "INSPECT_WORKTREE_PATH")
    return top


def head(root: str | Path) -> str:
    return _git(Path(root).resolve(), "rev-parse", "HEAD")


def branch(root: str | Path) -> str:
    value = _git(Path(root).resolve(), "branch", "--show-current")
    if not value:
        raise WorktreeError("worktree is detached", "INSPECT_WORKTREE_BRANCH")
    return value


def is_dirty(root: str | Path) -> bool:
    output = _git(Path(root).resolve(), "status", "--porcelain=v1", "--untracked-files=all")
    for line in output.splitlines():
        path = line[3:].strip() if len(line) >= 3 else ""
        if path.replace("\\", "/").startswith(".phongka/"):
            continue
        return True
    return False


def _worktrees(root: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in _git(root, "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key in {"worktree", "HEAD", "branch"}:
            current[key] = value.strip()
    return records


def _identity_shape(identity: Any) -> dict[str, str]:
    if not isinstance(identity, dict):
        raise WorktreeError("worktree identity must be an object", "INSPECT_WORKTREE_IDENTITY")
    required = ("task_id", "path", "branch", "base_commit", "head_commit", "workflow_decision_hash", "repo_path")
    if any(not isinstance(identity.get(key), str) or not identity[key].strip() for key in required):
        raise WorktreeError("worktree identity is incomplete", "INSPECT_WORKTREE_IDENTITY")
    if identity["repo_path"] != "." or Path(identity["path"]).is_absolute() or ".." in Path(identity["path"]).parts:
        raise WorktreeError("worktree identity path is not project-relative", "INSPECT_WORKTREE_PATH")
    return {key: identity[key] for key in required}


def verify_identity(project_root: str | Path, identity: Any, *, allow_dirty: bool) -> dict[str, Any]:
    expected = _identity_shape(identity)
    root = repo_top_level(project_root)
    target = (root / expected["path"]).resolve()
    if not target.is_dir() or target.is_symlink():
        raise WorktreeError("bound worktree path is missing or not a real directory", "INSPECT_WORKTREE_PATH")
    if repo_top_level(target) != target:
        raise WorktreeError("bound path is not a Git worktree top-level", "INSPECT_WORKTREE_PATH")
    actual_branch = branch(target)
    if actual_branch != expected["branch"]:
        raise WorktreeError("bound worktree branch does not match identity", "INSPECT_WORKTREE_BRANCH")
    actual_head = head(target)
    if actual_head != expected["head_commit"]:
        raise WorktreeError("bound worktree HEAD does not match identity", "INSPECT_WORKTREE_HEAD")
    if not allow_dirty and is_dirty(target):
        raise WorktreeError("bound worktree is dirty", "RECONCILE_WORKTREE_DIRTY")
    return expected


def prepare_identity(project_root: str | Path, task_id: str, decision_hash: str) -> dict[str, str]:
    root = repo_top_level(project_root)
    base = head(root)
    target = (root / ".phongka" / "worktrees" / task_id).resolve()
    branch_name = f"phongka/task/{task_id}"
    if target.parent != (root / ".phongka" / "worktrees").resolve() or target.exists() or target.is_symlink():
        raise WorktreeError("worktree path collides with an existing path", "INSPECT_WORKTREE_PATH")
    if is_dirty(root):
        raise WorktreeError("base project worktree is dirty", "RECONCILE_BASE_DIRTY")
    records = _worktrees(root)
    if any(Path(item.get("worktree", "")).resolve() == target for item in records):
        raise WorktreeError("worktree path is already registered", "INSPECT_WORKTREE_PATH")
    if any(item.get("branch") == f"refs/heads/{branch_name}" for item in records):
        raise WorktreeError("worktree branch is already registered", "INSPECT_WORKTREE_BRANCH")
    try:
        _git(root, "show-ref", "--verify", f"refs/heads/{branch_name}")
    except WorktreeError:
        pass
    else:
        raise WorktreeError("worktree branch already exists", "INSPECT_WORKTREE_BRANCH")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise WorktreeError("worktree parent is not a real directory", "INSPECT_WORKTREE_PATH")
    _git(root, "worktree", "add", "-b", branch_name, str(target), base)
    identity = {
        "task_id": task_id,
        "path": target.relative_to(root).as_posix(),
        "branch": branch_name,
        "base_commit": base,
        "head_commit": base,
        "workflow_decision_hash": decision_hash,
        "repo_path": ".",
    }
    verify_identity(root, identity, allow_dirty=True)
    return identity
