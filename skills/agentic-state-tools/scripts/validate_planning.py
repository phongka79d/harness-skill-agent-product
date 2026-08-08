"""Validate an executable planning bundle, safe file map, and dependency graph."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from review_validation import validate_rubric_reference  # noqa: E402

RESERVED_ROOTS = {".phongka", ".agent"}
ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"


def _safe_repo_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty repo-relative path")
    raw = value.strip()
    if "\\" in raw:
        raise ValueError(f"{label} must use forward slashes")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must stay inside the project root")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts:
        raise ValueError(f"{label} must be a non-empty repo-relative path")
    if parts[0].lower() in RESERVED_ROOTS:
        raise ValueError(f"{label} must not target runtime state")
    normalized = PurePosixPath(*parts).as_posix()
    if normalized != raw:
        raise ValueError(f"{label} must be normalized: {normalized}")
    return normalized


def _dependency_graph(tasks: list[dict]) -> dict[str, list[str]]:
    ids = [task["id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("task IDs must be unique")
    known = set(ids)
    graph: dict[str, list[str]] = {}
    for task in tasks:
        task_id = task["id"]
        dependencies = task["dependencies"]
        unknown = sorted(set(dependencies) - known)
        if unknown:
            raise ValueError(f"task {task_id} has unknown dependencies: {', '.join(unknown)}")
        if task_id in dependencies:
            raise ValueError(f"task {task_id} cannot depend on itself")
        graph[task_id] = dependencies

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError(f"dependency cycle detected at task {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in graph[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in ids:
        visit(task_id)
    return graph


def _depends_on(graph: dict[str, list[str]], task_id: str, target: str) -> bool:
    pending = list(graph[task_id])
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current not in seen:
            seen.add(current)
            pending.extend(graph[current])
    return False


def _validate_file_map(value: dict, graph: dict[str, list[str]]) -> None:
    scope = [_safe_repo_path(item, f"scope[{index}]") for index, item in enumerate(value["scope"])]
    if len(scope) != len(set(scope)):
        raise ValueError("scope paths must be unique")
    scope_set = set(scope)
    owners: dict[str, list[str]] = {}
    for task in value["tasks"]:
        task_id = task["id"]
        files = [
            _safe_repo_path(item, f"task {task_id} files[{index}]")
            for index, item in enumerate(task["files"])
        ]
        if len(files) != len(set(files)):
            raise ValueError(f"task {task_id} file paths must be unique")
        outside = sorted(set(files) - scope_set)
        if outside:
            raise ValueError(
                f"task {task_id} references files outside plan scope: " + ", ".join(outside)
            )
        for file_path in files:
            owners.setdefault(file_path, []).append(task_id)

    for file_path, task_ids in sorted(owners.items()):
        for index, left in enumerate(task_ids):
            for right in task_ids[index + 1 :]:
                if not (_depends_on(graph, left, right) or _depends_on(graph, right, left)):
                    raise ValueError(
                        f"tasks {left} and {right} both modify {file_path} without dependency ordering"
                    )


def _acceptance_ids(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("v5 acceptance must be a non-empty array")
    result: list[str] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            identifier = item.strip()
        elif isinstance(item, dict):
            identifier = str(item.get("id", "")).strip()
            description = str(item.get("description", "")).strip()
            if not description:
                raise ValueError(f"acceptance[{index}] description must be non-empty")
            unknown = sorted(set(item) - {"id", "description"})
            if unknown:
                raise ValueError(
                    f"acceptance[{index}] has unsupported fields: {', '.join(unknown)}"
                )
        else:
            raise ValueError(f"acceptance[{index}] must be a string or object")
        if not identifier:
            raise ValueError(f"acceptance[{index}] ID must be non-empty")
        if re.fullmatch(ID_PATTERN, identifier) is None:
            raise ValueError(f"acceptance[{index}] ID is not normalized: {identifier}")
        result.append(identifier)
    if len(result) != len(set(result)):
        raise ValueError("v5 acceptance IDs must be unique")
    return result


def _validate_v5(value: dict) -> None:
    if value.get("schema_version") != 5:
        return
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("v5 plan tasks must be non-empty")
    declared = value.get("plan_task_ids")
    if not isinstance(declared, list) or not declared:
        raise ValueError("v5 plan_task_ids must be a non-empty array")
    declared_ids = [str(item).strip() for item in declared]
    if any(not item for item in declared_ids) or len(declared_ids) != len(set(declared_ids)):
        raise ValueError("v5 plan_task_ids must be unique non-empty IDs")
    task_ids: list[str] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError(f"task {index} must be an object")
        task_id = str(task.get("plan_task_id", task.get("id", ""))).strip()
        if not task_id:
            raise ValueError(f"task {index} must declare plan_task_id")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", task_id) is None:
            raise ValueError(f"task {index} plan_task_id is not normalized")
        task_ids.append(task_id)
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("v5 plan_task_id values must be unique")
    if set(task_ids) != set(declared_ids):
        raise ValueError("plan_task_ids must exactly match task plan_task_id values")
    acceptance_ids = _acceptance_ids(value.get("acceptance"))
    declared_acceptance = value.get("acceptance_ids")
    if not isinstance(declared_acceptance, list) or set(declared_acceptance) != set(acceptance_ids):
        raise ValueError("acceptance_ids must exactly match stable acceptance IDs")


def validate_plan(value: dict, *, require_v5: bool = False) -> None:
    validate_file(
        value,
        HERE.parents[1] / "schemas" / "planning-bundle.schema.json",
        "planning bundle",
    )
    if require_v5 and value.get("schema_version") != 5:
        raise ValueError("controlled plan gate requires schema_version 5; migrate v4 explicitly")
    validate_rubric_reference(
        "plan",
        value.get("review_rubric_id"),
        value.get("review_rubric_version"),
    )
    for task in value["tasks"]:
        validate_rubric_reference(
            "task",
            task.get("review_rubric_id"),
            task.get("review_rubric_version"),
        )
    graph = _dependency_graph(value["tasks"])
    _validate_file_map(value, graph)
    _validate_v5(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument(
        "--require-v5",
        "--controlled",
        action="store_true",
        help="require the v5 planning contract for a controlled gate",
    )
    args = parser.parse_args()
    try:
        value = json.loads(Path(args.input).read_text(encoding="utf-8"))
        validate_plan(value, require_v5=args.require_v5)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"PLAN_REJECTED: {exc}", file=sys.stderr)
        return 1
    print("PLAN_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
