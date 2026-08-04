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


def capture_workspace(root: str | Path, *, expected_files: list[str] | None = None, expected_base: str | None = None) -> dict[str, Any]:
    project = Path(root).expanduser().resolve()
    expected = sorted({_normalize_path(item) for item in (expected_files or []) if isinstance(item, str) and item.strip()})
    status_code, status_output, status_error = _git(project, "status", "--porcelain=1", "--untracked-files=all")
    if status_code != 0:
        message = status_error.strip() or "Git workspace is unavailable"
        claims_git = bool(expected or expected_base)
        return {
            "workspace_status": "NOT_A_REPOSITORY" if "not a git repository" in message.lower() else "UNAVAILABLE",
            "base_commit": expected_base,
            "head_commit": None,
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
    parser.add_argument("--expected-file", action="append", default=[])
    args = parser.parse_args()
    try:
        print(json.dumps(capture_workspace(args.project_root, expected_files=args.expected_file, expected_base=args.expected_base), indent=2))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"WORKSPACE_CAPTURE_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
