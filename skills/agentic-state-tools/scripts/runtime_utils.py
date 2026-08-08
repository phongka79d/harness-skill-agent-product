"""Shared helpers for minimal project-local runtime state."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RESERVED_WORKSPACE_ROOTS = {".phongka", ".agent"}
REDACTED_VALUE = "[REDACTED]"
SECURITY_DEFAULTS = {
    "redact_environment_values": True,
    "redact_tokens": True,
    "forbid_secret_persistence": True,
}
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----[\s\S]*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.IGNORECASE,
)
BEARER_TOKEN_RE = re.compile(
    r"\bBearer[ \t]+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE
)
JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
KNOWN_API_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{12,}|"
    r"sk_(?:live|test)_[A-Za-z0-9_-]{12,}|"
    r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"AIza[0-9A-Za-z_-]{20,}|(?:AKIA|ASIA)[0-9A-Z]{16}|"
    r"npm_[A-Za-z0-9]{20,}|pypi-[A-Za-z0-9_-]{20,}"
    r")(?![A-Za-z0-9_-])"
)
ENV_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>(?:(?:\$(?:env|Env):|export[ \t]+))?)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:API[_-]?KEY|ACCESS[_-]?TOKEN|"
    r"CLIENT[_-]?SECRET|AUTH[_-]?TOKEN|PASSWORD|PASSWD|SECRET|TOKEN|CREDENTIALS?))"
    r"(?P<separator>[ \t]*=[ \t]*)(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"\b(?:api[_-]?key|access[_-]?token|client[_-]?secret)\b"
    r"[ \t]*[:=][ \t]*[^\s,;]+",
    re.IGNORECASE,
)
SENSITIVE_FIELD_NAMES = {
    "secret",
    "token",
    "password",
    "api_key",
    "private_key",
    "access_token",
    "client_secret",
}


class SecretPersistenceError(ValueError):
    """Raised without echoing the detected secret material."""


def _security_settings() -> dict[str, bool]:
    config_path = os.environ.get("AGENTIC_CONFIG_FILE")
    if config_path:
        path = Path(config_path).expanduser()
    else:
        path = Path(__file__).resolve().parents[2] / "agentic-configuration" / "config" / "agentic-config.json"
    settings = dict(SECURITY_DEFAULTS)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        security = config.get("security", {})
        if isinstance(security, dict):
            for name in settings:
                if name in security:
                    settings[name] = bool(security[name])
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        # Keep the persistence boundary fail-closed if configuration is unavailable.
        pass
    return settings


def _normalized_field_name(value: str) -> str:
    split_camel = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^A-Za-z0-9]+", "_", split_camel).strip("_").lower()


def _is_sensitive_field(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = _normalized_field_name(value)
    return any(
        normalized == name
        or normalized.startswith(name + "_")
        or normalized.endswith("_" + name)
        or ("_" + name + "_") in ("_" + normalized + "_")
        for name in SENSITIVE_FIELD_NAMES
    )


def _contains_private_key(value: Any) -> bool:
    if isinstance(value, str):
        return PRIVATE_KEY_RE.search(value) is not None
    if isinstance(value, dict):
        return any(_contains_private_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_private_key(item) for item in value)
    return False


def _reject_secret() -> None:
    raise SecretPersistenceError("secret-like value rejected at persistence boundary")


def _redact_or_reject(settings: dict[str, bool], setting: str) -> str | None:
    if settings[setting]:
        return REDACTED_VALUE
    if settings["forbid_secret_persistence"]:
        _reject_secret()
    return None


def _sanitize_string(value: str, settings: dict[str, bool]) -> str:
    if PRIVATE_KEY_RE.search(value):
        _reject_secret()
    result = value

    def replace_environment(match: re.Match[str]) -> str:
        replacement = _redact_or_reject(settings, "redact_environment_values")
        if replacement is None:
            return match.group(0)
        return (
            match.group("prefix")
            + match.group("name")
            + match.group("separator")
            + replacement
        )

    result = ENV_ASSIGNMENT_RE.sub(replace_environment, result)
    token_patterns = (BEARER_TOKEN_RE, JWT_RE, KNOWN_API_TOKEN_RE, SENSITIVE_ASSIGNMENT_RE)
    for pattern in token_patterns:
        if pattern.search(result) is None:
            continue
        replacement = _redact_or_reject(settings, "redact_tokens")
        if replacement is None:
            continue
        result = pattern.sub(replacement, result)
    return result


def sanitize_for_persistence(value: Any) -> Any:
    """Return a recursively safe value or reject it without exposing raw secrets."""
    settings = _security_settings()

    def sanitize(item: Any) -> Any:
        if isinstance(item, dict):
            sanitized: dict[Any, Any] = {}
            for key, child in item.items():
                if _is_sensitive_field(key):
                    if _contains_private_key(child):
                        _reject_secret()
                    replacement = _redact_or_reject(settings, "redact_tokens")
                    if replacement is not None:
                        sanitized[key] = replacement
                        continue
                sanitized[key] = sanitize(child)
            return sanitized
        if isinstance(item, list):
            return [sanitize(child) for child in item]
        if isinstance(item, str):
            return _sanitize_string(item, settings)
        return item

    return sanitize(value)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json_atomic(path: str | Path, value: Any) -> None:
    target = Path(path)
    safe_value = sanitize_for_persistence(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(safe_value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def restore_bytes_atomic(path: str | Path, data: bytes | None) -> None:
    """Restore one exact prior file value without exposing a partial write."""
    target = Path(path)
    if data is None:
        if target.exists():
            target.unlink()
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".restore.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _derived_plan_ids(bundle: dict[str, Any]) -> tuple[list[str], list[str]]:
    task_ids = [
        str(item.get("plan_task_id", item["id"])).strip()
        for item in bundle["tasks"]
    ]
    acceptance_ids = [
        str(item.get("id", "")).strip()
        if isinstance(item, dict)
        else str(item).strip()
        for item in bundle["acceptance"]
    ]
    return task_ids, acceptance_ids


def validate_plan_binding_documents(
    manifest: dict[str, Any],
    review: dict[str, Any],
    *,
    expected_decision_hash: str | None = None,
    require_v5: bool = False,
) -> dict[str, Any]:
    """Validate a complete plan/review contract before it binds runtime state."""
    schema_scripts = Path(__file__).resolve().parents[2] / "agentic-configuration" / "scripts"
    import sys

    if str(schema_scripts) not in sys.path:
        sys.path.insert(0, str(schema_scripts))
    from schema_validation import validate_file  # noqa: PLC0415
    from review_validation import validate_review_contract  # noqa: PLC0415
    from validate_planning import validate_plan  # noqa: PLC0415

    schema_root = Path(__file__).resolve().parents[1] / "schemas"
    if not isinstance(manifest, dict) or not isinstance(review, dict):
        raise ValueError("plan manifest and review must be JSON objects")
    validate_file(manifest, schema_root / "plan-manifest.schema.json", "plan manifest")
    validate_file(review, schema_root / "plan-review.schema.json", "plan review")

    bundle = manifest["bundle"]
    validate_plan(bundle, require_v5=require_v5)
    derived_task_ids, derived_acceptance_ids = _derived_plan_ids(bundle)
    if manifest["plan_task_ids"] != derived_task_ids:
        raise ValueError("plan manifest task IDs do not match the embedded v5 bundle")
    if manifest["acceptance_ids"] != derived_acceptance_ids:
        raise ValueError("plan manifest acceptance IDs do not match the embedded v5 bundle")
    if sha256_json(bundle) != manifest["plan_bundle_hash"]:
        raise ValueError("plan manifest bundle hash is stale")

    validate_review_contract(review, "plan")
    if review["plan_bundle_hash"] != manifest["plan_bundle_hash"]:
        raise ValueError("plan review is bound to another plan bundle")
    if review["acceptance_ids"] != manifest["acceptance_ids"]:
        raise ValueError("plan review acceptance IDs do not match the plan manifest")
    review_base = {key: value for key, value in review.items() if key != "plan_review_hash"}
    if sha256_json(review_base) != review["plan_review_hash"]:
        raise ValueError("plan review hash does not match its content")
    if review["outcome"] != "PASS":
        raise ValueError("current plan review must have PASS outcome")

    if expected_decision_hash is not None:
        if review.get("workflow_decision_hash") != expected_decision_hash:
            raise ValueError("plan review must be bound to the current workflow decision")
        manifest_decision_hash = manifest.get("workflow_decision_hash")
        if (
            manifest_decision_hash is not None
            and manifest_decision_hash != expected_decision_hash
        ):
            raise ValueError("plan manifest is bound to another workflow decision")
    return {
        "required": True,
        "bound": True,
        "schema_version": 5,
        "plan_bundle_hash": manifest["plan_bundle_hash"],
        "plan_review_hash": review["plan_review_hash"],
        "plan_task_ids": list(manifest["plan_task_ids"]),
        "acceptance_ids": list(manifest["acceptance_ids"]),
    }


def load_plan_binding(
    manifest_path: str | Path,
    review_path: str | Path,
    *,
    expected_decision_hash: str | None = None,
    require_v5: bool = False,
) -> dict[str, Any]:
    """Validate a manifest/review pair and return the persisted plan binding."""
    manifest = read_json(manifest_path)
    review = read_json(review_path)
    return validate_plan_binding_documents(
        manifest,
        review,
        expected_decision_hash=expected_decision_hash,
        require_v5=require_v5,
    )


def revalidate_plan_binding(
    project_root: str | Path,
    binding: dict[str, Any],
    *,
    expected_decision_hash: str | None = None,
    require_v5: bool = False,
) -> dict[str, Any]:
    """Re-read persisted manifest/review bytes and compare the recorded binding."""
    if not isinstance(binding, dict):
        raise ValueError("plan binding must be an object")
    if not binding.get("required"):
        return binding
    if not binding.get("bound"):
        raise ValueError("required plan binding is not bound")
    if binding.get("schema_version") != 5:
        raise ValueError("required plan binding must use schema version 5")
    manifest_path = binding.get("manifest_path")
    review_path = binding.get("review_path")
    if (
        manifest_path != ".phongka/plan/manifest.json"
        or review_path != ".phongka/plan/review.json"
    ):
        raise ValueError("required plan binding must reference persisted manifest and review artifacts")
    project = Path(project_root).resolve()
    current = load_plan_binding(
        project / manifest_path,
        project / review_path,
        expected_decision_hash=expected_decision_hash,
        require_v5=require_v5,
    )
    for key in (
        "plan_bundle_hash",
        "plan_review_hash",
        "plan_task_ids",
        "acceptance_ids",
    ):
        if current.get(key) != binding.get(key):
            raise ValueError(f"persisted plan binding changed: {key}")
    return binding


def write_text_atomic(path: str | Path, value: str) -> None:
    """Write a text artifact atomically inside the runtime boundary."""
    if not isinstance(value, str):
        raise TypeError("text artifact must be a string")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def runtime_root(project_root: str | Path) -> Path:
    project = Path(project_root).expanduser().resolve()
    root = project / ".phongka"
    if root.is_symlink():
        raise ValueError("runtime root must not be a symbolic link")
    return root


def safe_child(root: str | Path, *parts: str) -> Path:
    base = Path(root).resolve()
    target = base.joinpath(*parts).resolve()
    if target != base and base not in target.parents:
        raise ValueError("resolved path escapes its allowed root")
    return target


def validate_task_id(value: Any) -> str:
    task_id = str(value or "").strip()
    if TASK_ID_RE.fullmatch(task_id) is None:
        raise ValueError(
            "task_id must be 1-64 characters using letters, numbers, dot, underscore, or hyphen"
        )
    return task_id


def ensure_casefold_unique_task_ids(values: list[str], label: str = "task IDs") -> None:
    seen: dict[str, str] = {}
    for value in values:
        normalized = validate_task_id(value)
        key = normalized.casefold()
        previous = seen.get(key)
        if previous is not None and previous != normalized:
            raise ValueError(
                f"{label} collide case-insensitively: {previous}, {normalized}"
            )
        seen[key] = normalized


def task_state_path(root: str | Path, task_id: Any) -> Path:
    return safe_child(root, "tasks", f"{validate_task_id(task_id)}.json")


def task_artifact_path(root: str | Path, task_id: Any, filename: str) -> Path:
    if not filename or Path(filename).name != filename:
        raise ValueError("artifact filename must be a non-empty basename")
    return safe_child(root, "artifacts", validate_task_id(task_id), filename)


def normalize_workspace_path(
    project_root: str | Path, relative_path: Any
) -> tuple[Path, str]:
    root = Path(project_root).expanduser().resolve()
    raw = str(relative_path or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("workspace path must be a non-empty relative path")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError("workspace path must stay inside the project root")
    parts = tuple(part for part in pure.parts if part not in {"", "."})
    if not parts:
        raise ValueError("workspace path must be a non-empty relative path")
    if parts[0].lower() in RESERVED_WORKSPACE_ROOTS:
        raise ValueError("workspace evidence must not include runtime state")
    normalized = PurePosixPath(*parts).as_posix()
    return safe_child(root, *parts), normalized


def workspace_file(project_root: str | Path, relative_path: Any) -> Path:
    return normalize_workspace_path(project_root, relative_path)[0]


def resolve_workspace_context(
    project_root: str | Path,
    task_id: Any = None,
    supplied_identity: Any = None,
    *,
    allow_dirty: bool = True,
) -> tuple[Path, dict[str, Any] | None]:
    """Resolve artifact hashing to the bound worktree when controlled state requires it."""
    project = Path(project_root).expanduser().resolve()
    runtime = runtime_root(project)
    state_path = runtime / "state.json"
    state: dict[str, Any] | None = read_json(state_path) if state_path.is_file() else None
    state_identity = state.get("worktree_identity") if state else None
    task_identity = None
    task_decision_hash = None
    if task_id is not None and state:
        task_path = task_state_path(runtime, task_id)
        if task_path.is_file():
            task = read_json(task_path)
            task_identity = task.get("worktree_identity")
            task_decision_hash = task.get("workflow_decision_hash")
    identity = task_identity or state_identity
    if task_identity and state_identity and task_identity != state_identity:
        raise ValueError("runtime and task worktree identities disagree")
    enabled = bool(state and isinstance(state.get("worktree"), dict) and state["worktree"].get("enabled"))
    if enabled and identity is None:
        raise ValueError("controlled workspace is not bound to a worktree")
    if identity is not None:
        expected_decision_hash = task_decision_hash or state.get("workflow_decision_hash")
        if identity.get("workflow_decision_hash") != expected_decision_hash:
            raise ValueError("worktree identity is bound to another workflow decision")
        if task_id is not None and identity.get("task_id") != str(task_id):
            raise ValueError("worktree identity is bound to another task")
    if supplied_identity is not None and supplied_identity != identity:
        raise ValueError("workspace worktree identity is stale or mismatched")
    if identity is None:
        if supplied_identity is not None:
            raise ValueError("worktree identity is not allowed for an unbound runtime")
        return project, None
    from worktree import verify_identity  # noqa: PLC0415

    verified = verify_identity(project, identity, allow_dirty=allow_dirty)
    return project / verified["path"], verified


def bound_worktree_identity(project_root: str | Path, task_id: Any = None) -> dict[str, Any] | None:
    return resolve_workspace_context(project_root, task_id=task_id, allow_dirty=True)[1]


def normalize_scope_paths(project_root: str | Path, values: Any) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValueError("scope must contain at least one repo-relative file path")
    normalized: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"scope[{index}] must be a non-empty string")
        _, rel = normalize_workspace_path(project_root, value)
        normalized.append(rel)
    if len(normalized) != len(set(normalized)):
        raise ValueError("scope paths must be unique")
    return normalized


def fingerprint_file(project_root: str | Path, relative_path: Any) -> dict[str, Any]:
    path, normalized = normalize_workspace_path(project_root, relative_path)
    if not path.is_file():
        raise ValueError(f"workspace file is missing: {relative_path}")
    data = path.read_bytes()
    return {
        "path": normalized,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def verify_workspace_snapshot(
    project_root: str | Path,
    workspace: Any,
    task_id: Any = None,
    *,
    allow_dirty: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(workspace, dict):
        raise ValueError("workspace must be an object")
    files = workspace.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("workspace.files must contain at least one file")

    workspace_root, identity = resolve_workspace_context(
        project_root,
        task_id=task_id,
        supplied_identity=workspace.get("worktree"),
        allow_dirty=allow_dirty,
    )
    verified: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise ValueError(f"workspace.files[{index}] must be an object")
        current = fingerprint_file(workspace_root, item.get("path"))
        if current["path"] in seen:
            raise ValueError(f"duplicate workspace path: {current['path']}")
        seen.add(current["path"])
        if item.get("size") != current["size"] or item.get("sha256") != current["sha256"]:
            raise ValueError(f"workspace evidence is stale for: {current['path']}")
        verified.append(current)
    return verified


def require_scope_coverage(
    project_root: str | Path, task: dict[str, Any], workspace_files: Any
) -> None:
    scope = normalize_scope_paths(project_root, task.get("scope"))
    if not isinstance(workspace_files, list):
        raise ValueError("workspace files must be an array")
    observed = {
        normalize_workspace_path(project_root, item.get("path"))[1]
        for item in workspace_files
        if isinstance(item, dict)
    }
    missing = sorted(set(scope) - observed)
    if missing:
        raise ValueError("workspace evidence omits scoped files: " + ", ".join(missing))


def task_index_diff(root: str | Path, state: dict[str, Any]) -> dict[str, list[str]]:
    runtime = Path(root).resolve()
    expected_raw = state.get("tasks", {})
    if not isinstance(expected_raw, dict):
        raise ValueError("state.tasks must be an object")
    expected_ids = [validate_task_id(task_id) for task_id in expected_raw]
    ensure_casefold_unique_task_ids(expected_ids, "state task IDs")
    expected = set(expected_ids)
    tasks_dir = safe_child(runtime, "tasks")
    actual_ids: list[str] = []
    if tasks_dir.exists():
        if tasks_dir.is_symlink() or not tasks_dir.is_dir():
            raise ValueError("runtime tasks path must be a real directory")
        for path in tasks_dir.iterdir():
            if path.suffix != ".json":
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"task state must be a regular file: {path.name}")
            actual_ids.append(validate_task_id(path.stem))
    ensure_casefold_unique_task_ids(actual_ids, "task files")
    actual = set(actual_ids)
    return {
        "missing_files": sorted(expected - actual),
        "orphan_files": sorted(actual - expected),
    }


def require_task_index_consistent(root: str | Path, state: dict[str, Any]) -> None:
    if state.get("execution_depth") == "controlled":
        binding = state.get("plan_binding")
        if (
            not isinstance(binding, dict)
            or binding.get("required") is not True
            or binding.get("bound") is not True
        ):
            raise ValueError(
                "controlled runtime requires a bound v5 plan manifest and PASS review"
            )
        decision_hash = state.get("workflow_decision_hash")
        if not isinstance(decision_hash, str) or not decision_hash:
            raise ValueError("controlled runtime is missing its workflow decision hash")
        revalidate_plan_binding(
            Path(root).resolve().parent,
            binding,
            expected_decision_hash=decision_hash,
            require_v5=True,
        )
    diff = task_index_diff(root, state)
    problems: list[str] = []
    if diff["missing_files"]:
        problems.append("missing task files: " + ", ".join(diff["missing_files"]))
    if diff["orphan_files"]:
        problems.append("orphan task files: " + ", ".join(diff["orphan_files"]))
    if problems:
        raise ValueError("runtime task index is inconsistent; " + "; ".join(problems))


def refresh_checklist(project_root: str | Path) -> None:
    """Best-effort refresh of the human progress view without failing the caller."""
    try:
        from render_checklist import render_checklist  # noqa: PLC0415

        render_checklist(project_root)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        pass


def append_event(
    project_root: str | Path, event_type: str, payload: dict[str, Any]
) -> None:
    safe_payload = sanitize_for_persistence(payload)
    root = runtime_root(project_root)
    root.mkdir(parents=True, exist_ok=True)
    target = safe_child(root, "events.jsonl")
    event = {
        "schema_version": 2,
        "event_type": event_type,
        "recorded_at": utc_now(),
        "payload": safe_payload,
    }
    with target.open("a", encoding="utf-8") as handle:
        handle.write(canonical(event) + "\n")
