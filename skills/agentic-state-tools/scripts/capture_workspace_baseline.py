"""Capture an identity-bound workspace baseline before implementation begins."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from capture_workspace import capture_workspace
from validate_payload import validate
from verification_contract import workspace_hash


BASELINE_STATUSES = {"CLEAN", "KNOWN_FAILURES_APPROVED", "BLOCKED"}
RESULT_STATUSES = {"PASS", "FAIL", "SKIPPED", "BLOCKED"}
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40,64}$")
SHELL_OPERATOR_TOKENS = {"&&", "||", ";", "|", ">", "<"}
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "workspace-baseline.schema.json"


class BaselineError(ValueError):
    """The requested baseline cannot be captured safely."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
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


def _git(root: Path, *arguments: str, timeout: int = 15) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def _git_required(root: Path, *arguments: str) -> str:
    code, stdout, stderr = _git(root, *arguments)
    if code:
        raise BaselineError(f"git {' '.join(arguments)} failed: {stderr.strip() or stdout.strip() or 'unknown error'}")
    value = stdout.strip()
    if not value:
        raise BaselineError(f"git {' '.join(arguments)} returned no output")
    return value


def _normalize_command(command: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(command, str):
        text = command.strip()
        if not text:
            raise BaselineError("approved commands must not be empty")
        try:
            parts = tuple(shlex.split(text, posix=True))
        except ValueError as exc:
            raise BaselineError(f"baseline command has invalid quoting: {exc}") from exc
    elif isinstance(command, (list, tuple)):
        if not command or any(not isinstance(part, str) or not part.strip() for part in command):
            raise BaselineError("command argument arrays must contain non-empty strings")
        parts = tuple(part.strip() for part in command)
    else:
        raise BaselineError("baseline commands must be strings or argument arrays")
    if not parts:
        raise BaselineError("baseline commands must contain an executable")
    if any(part in SHELL_OPERATOR_TOKENS for part in parts):
        raise BaselineError("shell operators are not allowed in baseline command arguments")
    return parts


def _command_text(parts: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _approved_command_set(commands: Sequence[str | Sequence[str]] | None) -> set[str] | None:
    if commands is None:
        return None
    return {_command_text(_normalize_command(command)) for command in commands}


def _check_approved_command(parts: Sequence[str], approved: set[str] | None) -> None:
    if approved is not None and _command_text(parts) not in approved:
        raise BaselineError(f"command is not in the approved project command set: {_command_text(parts)}")


def _run_command(parts: Sequence[str], cwd: Path, timeout_seconds: int) -> dict[str, Any]:
    command = _command_text(parts)
    try:
        result = subprocess.run(
            list(parts),
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        exit_code: int | None = result.returncode
        status = "PASS" if result.returncode == 0 else "FAIL"
    except subprocess.TimeoutExpired as exc:
        stdout = _as_text(exc.stdout)
        stderr = _as_text(exc.stderr) or f"command timed out after {timeout_seconds} seconds"
        exit_code = None
        status = "BLOCKED"
    except OSError as exc:
        stdout = ""
        stderr = str(exc)
        exit_code = None
        status = "BLOCKED"
    output = (stdout + ("\n" if stdout and stderr else "") + stderr).strip()
    return {
        "command": command,
        "exit_code": exit_code,
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "output": output or None,
        "output_digest": _digest(output),
        "failure_signature": _digest(f"{command}\n{exit_code}\n{output}") if status != "PASS" else None,
        "approved_known_failure": False,
        "recorded_at": _timestamp(),
    }


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _worktree_records(project: Path) -> list[dict[str, str]]:
    output = _git_required(project, "worktree", "list", "--porcelain")
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in output.splitlines():
        if line.startswith("worktree "):
            if current is not None:
                records.append(current)
            current = {"path": str(Path(line[9:]).expanduser().resolve())}
        elif current is not None and line.startswith("branch "):
            current["branch"] = line[7:].removeprefix("refs/heads/")
    if current is not None:
        records.append(current)
    return records


def _validate_identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise BaselineError(f"{field} must contain only letters, numbers, dot, underscore, or hyphen")
    return value


def _validate_non_empty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BaselineError(f"{field} must be a non-empty string")
    return value.strip()


def _resolve_identity(
    project_root: str | Path,
    *,
    worktree_path: str | Path | None,
    worktree_root: str | Path | None,
    expected_branch: str | None,
    expected_base: str | None,
) -> dict[str, Any]:
    project = Path(project_root).expanduser().resolve()
    detected_project = Path(_git_required(project, "rev-parse", "--show-toplevel")).resolve()
    if detected_project != project:
        raise BaselineError("project_root must be the top-level Git workspace")
    target = Path(worktree_path).expanduser().resolve() if worktree_path is not None else project
    if target.is_symlink() or not target.is_dir():
        raise BaselineError("worktree_path must be an existing, non-symlink directory")
    detected_target = Path(_git_required(target, "rev-parse", "--show-toplevel")).resolve()
    if detected_target != target:
        raise BaselineError("worktree_path is not the root of its Git worktree")
    records = _worktree_records(project)
    record = next((item for item in records if item.get("path") == str(target)), None)
    isolated = target != project
    if isolated and record is None:
        raise BaselineError("worktree_path is not registered by the project Git worktree")
    configured_root: Path | None = None
    if worktree_root is not None:
        configured_root = Path(worktree_root).expanduser().resolve()
        if configured_root == project or project in configured_root.parents:
            raise BaselineError("worktree_root must be outside the project workspace")
        try:
            target.relative_to(configured_root)
        except ValueError as exc:
            raise BaselineError("worktree_path is outside the configured worktree root") from exc
        if target == configured_root:
            raise BaselineError("worktree_path must not equal the configured worktree root")
    branch = _git_required(target, "branch", "--show-current")
    if expected_branch is not None and branch != expected_branch:
        raise BaselineError(f"worktree branch {branch} does not match expected branch {expected_branch}")
    head_commit = _git_required(target, "rev-parse", "HEAD")
    if expected_base is not None:
        if not COMMIT_PATTERN.fullmatch(expected_base) or head_commit.lower() != expected_base.lower():
            raise BaselineError("baseline base_commit does not match the current worktree HEAD")
    base_branch = _git_required(project, "branch", "--show-current")
    owner: str | None
    try:
        owner = target.owner()
    except (OSError, KeyError, NotImplementedError, ValueError):
        owner = None
    return {
        "project_root": project,
        "worktree_path": target,
        "worktree_root": configured_root,
        "branch": branch,
        "base_branch": base_branch or branch,
        "base_commit": head_commit,
        "head_commit": head_commit,
        "is_isolated": isolated,
        "ownership_verified": True,
        "owner": owner,
    }


def _approval_tokens(known_failures: Sequence[str | dict[str, Any]] | None) -> tuple[set[str], dict[str, str]]:
    tokens: set[str] = set()
    reasons: dict[str, str] = {}
    for item in known_failures or []:
        if isinstance(item, str) and item.strip():
            tokens.add(item.strip())
        elif isinstance(item, dict):
            reason = str(item.get("reason") or "approved existing baseline failure")
            for key in ("signature", "command", "failure_signature"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    token = value.strip()
                    tokens.add(token)
                    reasons[token] = reason
        else:
            raise BaselineError("known_failures approvals must be strings or objects")
    return tokens, reasons


def _approval_for(result: dict[str, Any], tokens: set[str], reasons: dict[str, str]) -> tuple[bool, str]:
    candidates = [
        result.get("failure_signature"),
        result.get("command"),
        f"{result.get('command')}|{result.get('exit_code')}",
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate in tokens:
            return True, reasons.get(candidate, "approved existing baseline failure")
    return False, "new baseline failure"


def _known_failure_record(result: dict[str, Any], approved: bool, reason: str) -> dict[str, Any]:
    return {
        "signature": result["failure_signature"] or _digest(result["command"]),
        "command": result["command"],
        "exit_code": result["exit_code"],
        "approved": approved,
        "reason": reason,
        "output_digest": result["output_digest"],
    }


def _validate_artifact(value: dict[str, Any]) -> None:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BaselineError("workspace baseline schema is unreadable") from exc
    errors = validate(value, schema, base_path=SCHEMA_PATH.parent)
    if errors:
        raise BaselineError("workspace baseline violates its schema: " + "; ".join(errors))


def capture_workspace_baseline(
    project_root: str | Path,
    *,
    task_id: str,
    run_id: str | None = None,
    worktree_path: str | Path | None = None,
    worktree_root: str | Path | None = None,
    branch: str | None = None,
    base_commit: str | None = None,
    setup_command: str | Sequence[str] | None = None,
    baseline_commands: Sequence[str | Sequence[str]] | None = None,
    known_failures: Sequence[str | dict[str, Any]] | None = None,
    approved_commands: Sequence[str | Sequence[str]] | None = None,
    profile_id: str | None = None,
    timeout_seconds: int = 300,
    baseline_id: str | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Capture baseline evidence and optionally persist it atomically.

    Commands are always executed without a shell. When ``approved_commands`` is
    supplied, every setup and verification command must exactly match one of
    those approved argument lists.
    """

    _validate_identifier(task_id, "task_id")
    run = _validate_non_empty(run_id or f"RUN-BASELINE-{uuid.uuid4().hex[:12]}", "run_id")
    if baseline_id is None:
        baseline_id = f"BASELINE-{task_id}-{uuid.uuid4().hex[:12]}"
    _validate_identifier(baseline_id, "baseline_id")
    if profile_id is not None:
        _validate_identifier(profile_id, "profile_id")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        raise BaselineError("timeout_seconds must be a positive integer")
    identity = _resolve_identity(
        project_root,
        worktree_path=worktree_path,
        worktree_root=worktree_root,
        expected_branch=branch,
        expected_base=base_commit,
    )
    project = identity["project_root"]
    target = identity["worktree_path"]
    approved = _approved_command_set(approved_commands)
    approval_tokens, approval_reasons = _approval_tokens(known_failures)
    setup_parts: tuple[str, ...] | None = None
    setup_result: dict[str, Any]
    if setup_command is None:
        setup_result = {
            "command": "NOT_RUN",
            "exit_code": 0,
            "status": "SKIPPED",
            "stdout": "",
            "stderr": "",
            "output": None,
            "output_digest": _digest(""),
            "failure_signature": None,
            "approved_known_failure": False,
            "recorded_at": _timestamp(),
        }
    else:
        setup_parts = _normalize_command(setup_command)
        _check_approved_command(setup_parts, approved)
        setup_result = _run_command(setup_parts, target, timeout_seconds)
        if setup_result["status"] != "PASS":
            is_approved, reason = _approval_for(setup_result, approval_tokens, approval_reasons)
            setup_result["approved_known_failure"] = is_approved
            setup_result["approval_reason"] = reason
    commands = list(baseline_commands or [])
    normalized_commands: list[tuple[str, ...]] = []
    for command in commands:
        parts = _normalize_command(command)
        _check_approved_command(parts, approved)
        normalized_commands.append(parts)
    baseline_results: list[dict[str, Any]] = []
    for parts in normalized_commands:
        result = _run_command(parts, target, timeout_seconds)
        if result["status"] != "PASS":
            is_approved, reason = _approval_for(result, approval_tokens, approval_reasons)
            result["approved_known_failure"] = is_approved
            result["approval_reason"] = reason
        baseline_results.append(result)

    current_branch = _git_required(target, "branch", "--show-current")
    current_head = _git_required(target, "rev-parse", "HEAD")
    blocking_reasons: list[str] = []
    if current_branch != identity["branch"]:
        blocking_reasons.append("worktree branch changed while capturing baseline")
    if current_head.lower() != identity["base_commit"].lower():
        blocking_reasons.append("worktree HEAD changed while capturing baseline")
    if not normalized_commands:
        blocking_reasons.append("no baseline verification commands were supplied")
    if setup_result["status"] in {"FAIL", "BLOCKED"} and not setup_result["approved_known_failure"]:
        blocking_reasons.append("dependency setup did not pass")
    for result in baseline_results:
        if result["status"] in {"FAIL", "BLOCKED"} and not result["approved_known_failure"]:
            blocking_reasons.append(f"baseline verification failed: {result['command']}")

    known_failure_records: list[dict[str, Any]] = []
    if setup_result["status"] in {"FAIL", "BLOCKED"}:
        known_failure_records.append(
            _known_failure_record(
                setup_result,
                bool(setup_result["approved_known_failure"]),
                str(setup_result.get("approval_reason") or "new dependency setup failure"),
            )
        )
    for result in baseline_results:
        if result["status"] in {"FAIL", "BLOCKED"}:
            known_failure_records.append(
                _known_failure_record(
                    result,
                    bool(result["approved_known_failure"]),
                    str(result.get("approval_reason") or "new baseline failure"),
                )
            )
    has_approved_failure = any(item["approved"] for item in known_failure_records)
    status = "BLOCKED" if blocking_reasons else ("KNOWN_FAILURES_APPROVED" if has_approved_failure else "CLEAN")
    snapshot = capture_workspace(target, expected_base=identity["base_commit"], expected_branch=identity["branch"], expected_worktree_path=target)
    if snapshot.get("mismatch"):
        blocking_reasons.extend(str(reason) for reason in snapshot.get("reasons", []) if reason)
        status = "BLOCKED"
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "baseline_id": baseline_id,
        "task_id": task_id,
        "run_id": run,
        "worktree_path": str(target),
        "worktree_root": str(identity["worktree_root"]) if identity["worktree_root"] is not None else None,
        "branch": identity["branch"],
        "base_branch": identity["base_branch"],
        "base_commit": identity["base_commit"],
        "head_commit": current_head,
        "workspace_hash": workspace_hash(target),
        "is_isolated": identity["is_isolated"],
        "ownership_verified": identity["ownership_verified"],
        "owner": identity["owner"],
        "setup_command": _command_text(setup_parts) if setup_parts is not None else "NOT_RUN",
        "setup_exit_code": setup_result["exit_code"],
        "setup_status": setup_result["status"],
        "setup_output": setup_result["output"],
        "setup_output_digest": setup_result["output_digest"],
        "setup_failure_signature": setup_result["failure_signature"],
        "baseline_commands": [_command_text(parts) for parts in normalized_commands],
        "baseline_results": baseline_results,
        "known_failures": known_failure_records,
        "approved_known_failures": sorted(approval_tokens),
        "profile_id": profile_id,
        "blocking_reasons": sorted(set(blocking_reasons)),
        "status": status if status in BASELINE_STATUSES else "BLOCKED",
        "captured_at": _timestamp(),
    }
    # Approval explanations are useful while running commands but are not part
    # of the canonical result schema; the durable record keeps only the
    # normalized known-failure contract above.
    for result in artifact["baseline_results"]:
        result.pop("approval_reason", None)
    _validate_artifact(artifact)
    if output_path is not None:
        _write_atomic(Path(output_path).expanduser().resolve(), artifact)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--worktree-path")
    parser.add_argument("--worktree-root")
    parser.add_argument("--branch")
    parser.add_argument("--base-commit")
    parser.add_argument("--setup-command")
    parser.add_argument("--baseline-command", action="append", default=[])
    parser.add_argument("--known-failure", action="append", default=[])
    parser.add_argument("--approved-command", action="append")
    parser.add_argument("--profile-id")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--baseline-id")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        project = Path(args.project_root).expanduser().resolve()
        output = args.output
        if output is None:
            output = project / ".agent" / "work" / args.task_id / "workspace-baseline.json"
        artifact = capture_workspace_baseline(
            project,
            task_id=args.task_id,
            run_id=args.run_id,
            worktree_path=args.worktree_path,
            worktree_root=args.worktree_root,
            branch=args.branch,
            base_commit=args.base_commit,
            setup_command=args.setup_command,
            baseline_commands=args.baseline_command,
            known_failures=args.known_failure,
            approved_commands=args.approved_command,
            profile_id=args.profile_id,
            timeout_seconds=args.timeout_seconds,
            baseline_id=args.baseline_id,
            output_path=output,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"BASELINE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if artifact.get("status") == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
