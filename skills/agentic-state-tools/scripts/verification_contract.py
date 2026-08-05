"""Shared identity, workspace, and policy checks for verification artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from capture_workspace import capture_workspace
from resolve_project_profile import resolve_profile
from runtime_utils import read_object, validate_identifier


HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PHASES = {"RED", "GREEN", "BROAD", "FOCUSED", "LINT", "TYPECHECK", "UNIT", "INTEGRATION", "BUILD", "PACKAGING", "REQUIREMENT_COVERAGE"}
STATUSES = {"PASS", "FAIL", "SKIPPED", "NOT_APPLICABLE", "NOT_RUN", "BLOCKED"}
STRICT_PROFILES = {"production", "high_risk", "high-risk"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_hash(value: Any, field: str = "workspace_hash") -> str:
    if not isinstance(value, str) or HASH_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 hash")
    return value


def normalize_relative_path(value: str, field: str = "path") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative path")
    normalized = value.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"{field} must be relative")
    parts = normalized.split("/")
    if not normalized or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{field} must not contain traversal")
    if normalized == ".agent" or normalized.startswith(".agent/"):
        raise ValueError(f"{field} must not target runtime artifacts")
    return "/".join(parts)


def normalize_relevant_files(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("relevant_files must be an array")
    normalized = [normalize_relative_path(item, "relevant_files") for item in value]
    return sorted(set(normalized))


def workspace_hash(project_root: str | Path, relevant_files: list[str] | None = None) -> str:
    """Hash Git state plus relevant file content while excluding .agent artifacts."""

    project = Path(project_root).expanduser().resolve()
    snapshot = capture_workspace(project)
    requested = normalize_relevant_files(relevant_files)
    changed = [
        item
        for item in snapshot.get("changed_files", [])
        if isinstance(item, str) and not item.startswith(".agent/") and item != ".agent"
    ]
    paths = sorted(set(requested) | set(changed))
    content: dict[str, str | None] = {}
    for relative in paths:
        target = project / relative
        if target.is_symlink() or not target.is_file():
            content[relative] = None
            continue
        content[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    material = {
        "snapshot": snapshot,
        "content_hashes": content,
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def load_task_state(root: Path, task_id: str) -> dict[str, Any]:
    validate_identifier(task_id, "task_id")
    path = root / "work" / task_id / "task-state.json"
    if not path.is_file():
        raise ValueError(f"task state does not exist for {task_id}")
    state = read_object(path)
    if state.get("task_id") != task_id:
        raise ValueError("task state task_id does not match evidence")
    return state


def validate_identity(payload: dict[str, Any], task_state: dict[str, Any], *, label: str) -> None:
    for field in ("run_id", "attempt_id"):
        supplied = payload.get(field)
        expected = task_state.get(field)
        if not isinstance(supplied, str) or not supplied.strip():
            raise ValueError(f"{label}.{field} is required")
        if not isinstance(expected, str) or not expected.strip():
            raise ValueError(f"task state {field} is required")
        if supplied != expected:
            raise ValueError(f"{label}.{field} does not match task identity")
    for field in ("task_revision", "plan_revision"):
        supplied = payload.get(field)
        if isinstance(supplied, bool) or not isinstance(supplied, int) or supplied < 1:
            raise ValueError(f"{label}.{field} must be a positive integer")
    if task_state.get("revision") is not None and payload["task_revision"] != task_state.get("revision"):
        raise ValueError(f"{label}.task_revision does not match current task state")
    if task_state.get("plan_revision") is not None and payload["plan_revision"] != task_state.get("plan_revision"):
        raise ValueError(f"{label}.plan_revision does not match current task state")


def profile_policy(profile_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = resolve_profile(profile_id)
    policy = profile.get("verification_policy")
    if not isinstance(policy, dict):
        raise ValueError(f"profile {profile_id} has no verification policy")
    return profile, policy


def is_strict_profile(profile_id: str) -> bool:
    return isinstance(profile_id, str) and profile_id in STRICT_PROFILES


def hidden_failure_output(evidence: dict[str, Any]) -> str | None:
    output = "\n".join(
        str(evidence.get(field, ""))
        for field in ("output", "stdout", "stderr", "summary")
        if evidence.get(field) is not None
    )
    if not output.strip():
        return None
    patterns = (
        r"\b[1-9][0-9]*\s+(?:failed|failure|failures|error|errors|skipped)\b",
        r"\b(?:failed|failure|failures|errors?|skipped|not run)\s*[:=]\s*[1-9][0-9]*\b",
        r"\b(?:test|tests|check|checks)\s+(?:failed|skipped|not run)\b",
    )
    for pattern in patterns:
        if re.search(pattern, output, flags=re.IGNORECASE):
            return output.strip()
    if re.search(r"\b(?:SKIPPED|NOT RUN)\b", output, flags=re.IGNORECASE) and not re.search(
        r"\b0\s+(?:skipped|not run)\b", output, flags=re.IGNORECASE
    ):
        return output.strip()
    return None
