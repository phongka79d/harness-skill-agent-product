"""Validate, hash, install, and recheck planner-authored Markdown plan trees."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from runtime_utils import safe_child, sha256_json

PLAN_DOCS_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PLAN_DIR_RE = re.compile(r"^Plan-(?P<number>[1-9][0-9]*)$")
BATCH_FILE_RE = re.compile(r"^Batch-(?P<number>[1-9][0-9]*)\.md$")
TASK_RE = re.compile(r"(?m)^### Task (?P<id>[A-Za-z0-9][A-Za-z0-9._-]{0,63}):")
ACCEPTANCE_RE = re.compile(r"(?m)^\*\*Acceptance:\*\* (?P<ids>[^\r\n]+)\r?$")
ACCEPTANCE_ID_RE = re.compile(r"(?:^|;[ \t]*)([A-Za-z0-9][A-Za-z0-9._:-]{0,127}):")
STEP_RE = re.compile(r"(?m)^- \[ \] \*\*Step [1-9][0-9]*:")


def _real_directory(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} must be a real directory")
    return path.resolve()


def _read_markdown(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file() or path.suffix != ".md":
        raise ValueError(f"{label} must be a regular Markdown file")
    data = path.read_bytes()
    if not data.strip():
        raise ValueError(f"{label} must not be empty")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} must be UTF-8") from exc
    return data


def inspect_plan_docs(path: str | Path) -> dict[str, Any]:
    """Validate one physical plan hierarchy and return its stable tree digest."""
    unresolved = Path(path).expanduser()
    if unresolved.is_symlink():
        raise ValueError("plan docs root must not be a symbolic link")
    root = _real_directory(unresolved, "plan docs root")
    if PLAN_DOCS_DIR_RE.fullmatch(root.name) is None:
        raise ValueError("plan docs directory must be named <date>-<feature>")

    top_entries = {entry.name: entry for entry in root.iterdir()}
    if set(top_entries) != {"MasterPlan.md", "plans"}:
        raise ValueError("plan docs root must contain only MasterPlan.md and plans/")
    master = _read_markdown(top_entries["MasterPlan.md"], "MasterPlan.md")
    plans_root = _real_directory(top_entries["plans"], "plans")

    plan_dirs = list(plans_root.iterdir())
    if not plan_dirs:
        raise ValueError("plan docs must include at least one plans/Plan-N directory")
    if any(
        item.is_symlink() or PLAN_DIR_RE.fullmatch(item.name) is None
        for item in plan_dirs
    ):
        raise ValueError("plans/ may contain only real Plan-N directories")
    plan_dirs.sort(
        key=lambda item: int(PLAN_DIR_RE.fullmatch(item.name).group("number"))
    )

    files: list[dict[str, Any]] = []
    task_ids: list[str] = []
    acceptance_ids: list[str] = []
    acceptance_ids_by_task: dict[str, list[str]] = {}

    def record(file_path: Path, data: bytes) -> None:
        relative = file_path.relative_to(root).as_posix()
        files.append(
            {
                "path": relative,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    record(top_entries["MasterPlan.md"], master)
    master_text = master.decode("utf-8")
    for plan_dir in plan_dirs:
        if not plan_dir.is_dir():
            raise ValueError("plans/ may contain only real Plan-N directories")
        plan_root = _real_directory(plan_dir, plan_dir.name)
        plan_entries = {entry.name: entry for entry in plan_root.iterdir()}
        if set(plan_entries) != {"Plan.md", "batches"}:
            raise ValueError(f"{plan_dir.name} must contain only Plan.md and batches/")
        plan_data = _read_markdown(plan_entries["Plan.md"], f"{plan_dir.name}/Plan.md")
        record(plan_entries["Plan.md"], plan_data)
        if f"plans/{plan_dir.name}/Plan.md" not in master_text:
            raise ValueError(f"MasterPlan.md must link plans/{plan_dir.name}/Plan.md")

        batches_root = _real_directory(plan_entries["batches"], f"{plan_dir.name}/batches")
        batches = list(batches_root.iterdir())
        if not batches:
            raise ValueError(f"{plan_dir.name} must contain at least one Batch-N.md")
        if any(
            item.is_symlink() or BATCH_FILE_RE.fullmatch(item.name) is None
            for item in batches
        ):
            raise ValueError(f"{plan_dir.name}/batches may contain only Batch-N.md files")
        batches.sort(
            key=lambda item: int(BATCH_FILE_RE.fullmatch(item.name).group("number"))
        )
        plan_text = plan_data.decode("utf-8")
        for batch in batches:
            if not batch.is_file():
                raise ValueError(f"{plan_dir.name}/batches may contain only Batch-N.md files")
            batch_data = _read_markdown(batch, f"{plan_dir.name}/batches/{batch.name}")
            batch_text = batch_data.decode("utf-8")
            task_matches = list(TASK_RE.finditer(batch_text))
            if not task_matches:
                raise ValueError(f"{batch.name} must include at least one Task heading")
            for index, task_match in enumerate(task_matches):
                block_end = (
                    task_matches[index + 1].start()
                    if index + 1 < len(task_matches)
                    else len(batch_text)
                )
                task_block = batch_text[task_match.start() : block_end]
                task_id = task_match.group("id")
                task_acceptance = list(ACCEPTANCE_RE.finditer(task_block))
                if len(task_acceptance) != 1:
                    raise ValueError(f"Task {task_id} must include exactly one Acceptance line")
                task_acceptance_ids = ACCEPTANCE_ID_RE.findall(
                    task_acceptance[0].group("ids")
                )
                if not task_acceptance_ids:
                    raise ValueError(f"Task {task_id} must include stable Acceptance IDs")
                if STEP_RE.search(task_block) is None:
                    raise ValueError(f"Task {task_id} must include checkbox Steps")
                task_ids.append(task_id)
                acceptance_ids.extend(task_acceptance_ids)
                acceptance_ids_by_task[task_id] = task_acceptance_ids
            if f"batches/{batch.name}" not in plan_text:
                raise ValueError(f"{plan_dir.name}/Plan.md must link batches/{batch.name}")
            record(batch, batch_data)

    if len(task_ids) != len(set(task_ids)):
        raise ValueError("plan docs Task IDs must be unique")
    if not acceptance_ids or len(acceptance_ids) != len(set(acceptance_ids)):
        raise ValueError("plan docs Acceptance IDs must be non-empty and unique")
    files.sort(key=lambda item: item["path"])
    return {
        "directory_name": root.name,
        "plan_path": f".phongka/plan/{root.name}",
        "plan_docs_hash": sha256_json(files),
        "plan_task_ids": task_ids,
        "acceptance_ids": acceptance_ids,
        "acceptance_ids_by_task": acceptance_ids_by_task,
        "files": files,
    }


def install_plan_docs_atomic(
    runtime_root: str | Path,
    source: str | Path,
    *,
    expected_hash: str,
) -> tuple[Path, bool]:
    """Install a validated tree atomically; identical existing trees are idempotent."""
    runtime = Path(runtime_root).resolve()
    descriptor = inspect_plan_docs(source)
    if descriptor["plan_docs_hash"] != expected_hash:
        raise ValueError("plan docs hash does not match the reviewed manifest")
    target = safe_child(runtime, "plan", descriptor["directory_name"])
    if target.exists():
        if target.is_symlink() or not target.is_dir():
            raise ValueError("installed plan docs path must be a real directory")
        current = inspect_plan_docs(target)
        if current["plan_docs_hash"] != expected_hash:
            raise ValueError("installed plan docs differ from the reviewed manifest")
        return target, False

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".plan-docs-", dir=target.parent))
    source_root = Path(source).resolve()
    try:
        for item in descriptor["files"]:
            relative = Path(*item["path"].split("/"))
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = _read_markdown(source_root / relative, item["path"])
            if len(data) != item["size"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("plan docs changed while they were being installed")
            with destination.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return target, True


def remove_installed_plan_docs(runtime_root: str | Path, plan_path: str) -> None:
    """Rollback only a newly installed, validated runtime plan-doc path."""
    runtime = Path(runtime_root).resolve()
    prefix = ".phongka/plan/"
    if not isinstance(plan_path, str) or not plan_path.startswith(prefix):
        raise ValueError("plan_path is not a runtime plan-doc path")
    name = plan_path[len(prefix) :]
    if PLAN_DOCS_DIR_RE.fullmatch(name) is None:
        raise ValueError("plan_path directory name is invalid")
    target = safe_child(runtime, "plan", name)
    if target.exists():
        if target.is_symlink() or not target.is_dir():
            raise ValueError("plan docs rollback target must be a real directory")
        shutil.rmtree(target)
