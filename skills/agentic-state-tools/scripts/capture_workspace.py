"""Capture normalized Git workspace evidence for checkpoints and recovery."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _git(root: Path, *arguments: str) -> tuple[int, str, str]:
    try:
        result = subprocess.run(["git", "-C", str(root), *arguments], text=True, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def _normalize_path(value: str) -> str:
    value = value.replace("\\", "/").strip().strip('"')
    while value.startswith("./"):
        value = value[2:]
    return value


def _git_identity(root: Path) -> dict[str, Any]:
    """Return branch/worktree identity without changing the workspace."""

    top_code, top_output, _ = _git(root, "rev-parse", "--show-toplevel")
    branch_code, branch_output, _ = _git(root, "branch", "--show-current")
    list_code, list_output, _ = _git(root, "worktree", "list", "--porcelain")
    project_root = Path(top_output.strip()).expanduser().resolve() if top_code == 0 and top_output.strip() else None
    branch = branch_output.strip() if branch_code == 0 else ""
    worktree_paths: list[Path] = []
    if list_code == 0:
        for line in list_output.splitlines():
            if line.startswith("worktree "):
                worktree_paths.append(Path(line[9:]).expanduser().resolve())
    main_worktree = worktree_paths[0] if worktree_paths else project_root
    return {
        "project_root": str(project_root) if project_root is not None else None,
        "branch": branch or None,
        "worktree_path": str(project_root) if project_root is not None else str(root),
        "main_worktree_path": str(main_worktree) if main_worktree is not None else None,
        "is_isolated": project_root is not None and main_worktree is not None and project_root != main_worktree,
        "worktree_registered": project_root is not None and project_root in worktree_paths,
    }


def parse_porcelain(output: str) -> dict[str, list[str]]:
    if not isinstance(output, str):
        raise ValueError("Git status output must be text")
    staged: set[str] = set()
    unstaged: set[str] = set()
    untracked: set[str] = set()
    for line in output.splitlines():
        if not line:
            continue
        if len(line) < 3 or line[2] != " ":
            raise ValueError(f"malformed Git status line: {line!r}")
        status = line[:2]
        path = line[3:].strip()
        if not path:
            raise ValueError("malformed Git status line has no path")
        if " -> " in path:
            path = path.split(" -> ")[-1]
        path = _normalize_path(path)
        if path == ".agent" or path.startswith(".agent/"):
            continue
        if status == "??":
            untracked.add(path)
            continue
        if status[0] not in " MADRCU?!" or status[1] not in " MADRCU?!":
            raise ValueError(f"malformed Git status code: {status!r}")
        if status[0] != " ":
            staged.add(path)
        if status[1] != " ":
            unstaged.add(path)
    return {"staged_paths": sorted(staged), "unstaged_paths": sorted(unstaged), "untracked_paths": sorted(untracked)}


def capture_workspace(
    root: str | Path,
    *,
    expected_files: list[str] | None = None,
    expected_base: str | None = None,
    expected_branch: str | None = None,
    expected_worktree_path: str | Path | None = None,
) -> dict[str, Any]:
    project = Path(root).expanduser().resolve()
    identity = _git_identity(project)
    expected = sorted({_normalize_path(item) for item in (expected_files or []) if isinstance(item, str) and item.strip()})
    status_code, status_output, status_error = _git(project, "status", "--porcelain=1", "--untracked-files=all")
    if status_code != 0:
        message = status_error.strip() or "Git workspace is unavailable"
        claims_git = bool(expected or expected_base)
        return {
            "workspace_status": "NOT_A_REPOSITORY" if "not a git repository" in message.lower() else "UNAVAILABLE",
            "base_commit": expected_base,
            "head_commit": None,
            **identity,
            "staged_paths": [],
            "unstaged_paths": [],
            "untracked_paths": [],
            "changed_files": [],
            "expected_files": expected,
            "missing_files": expected,
            "unexpected_files": [],
            "mismatch": claims_git,
            "reasons": [message] + (["checkpoint claims Git evidence"] if claims_git else []),
        }
    parsed = parse_porcelain(status_output)
    head_code, head_output, head_error = _git(project, "rev-parse", "HEAD")
    head = head_output.strip()
    if head_code != 0 or not head or "\n" in head:
        raise ValueError(f"malformed Git HEAD output: {head_error.strip() or head_output!r}")
    changed = sorted(set(parsed["staged_paths"] + parsed["unstaged_paths"] + parsed["untracked_paths"]))
    unexpected = sorted(set(changed) - set(expected)) if expected else []
    filesystem_missing = sorted(
        path
        for path in expected
        if not (project / path).is_file() or (project / path).is_symlink()
    )
    missing = sorted(
        {
            *set(expected) - set(changed),
            *filesystem_missing,
        }
    )
    reasons: list[str] = []
    base = expected_base or head
    if expected_base and head != expected_base:
        reasons.append(f"workspace HEAD {head} does not match checkpoint base_commit {expected_base}")
    if expected_branch and identity.get("branch") != expected_branch:
        reasons.append(f"workspace branch {identity.get('branch') or '<detached>'} does not match expected branch {expected_branch}")
    if expected_worktree_path is not None:
        expected_worktree = str(Path(expected_worktree_path).expanduser().resolve())
        if identity.get("worktree_path") != expected_worktree:
            reasons.append(
                f"workspace path {identity.get('worktree_path')} does not match expected worktree path {expected_worktree}"
            )
    if identity.get("project_root") is None or not identity.get("worktree_registered"):
        reasons.append("workspace Git worktree identity could not be verified")
    if unexpected:
        reasons.append(f"workspace has unrecorded changed files: {', '.join(unexpected)}")
    if missing:
        reasons.append(f"checkpoint files are not changed in workspace: {', '.join(missing)}")
    if filesystem_missing:
        reasons.append(f"checkpoint files are missing on filesystem: {', '.join(filesystem_missing)}")
    return {
        "workspace_status": "CHANGED" if changed else "CLEAN",
        "base_commit": base,
        "head_commit": head,
        **identity,
        **parsed,
        "changed_files": changed,
        "expected_files": expected,
        "missing_files": missing,
        "unexpected_files": unexpected,
        "mismatch": bool(reasons),
        "reasons": reasons or ["Git workspace agrees with checkpoint evidence"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--expected-base")
    parser.add_argument("--expected-branch")
    parser.add_argument("--expected-worktree-path")
    parser.add_argument("--expected-file", action="append", default=[])
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                capture_workspace(
                    args.project_root,
                    expected_files=args.expected_file,
                    expected_base=args.expected_base,
                    expected_branch=args.expected_branch,
                    expected_worktree_path=args.expected_worktree_path,
                ),
                indent=2,
            )
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"WORKSPACE_CAPTURE_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
