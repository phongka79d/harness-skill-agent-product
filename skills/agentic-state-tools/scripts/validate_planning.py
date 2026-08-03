"""Validate planning documents and their cross-document relationships."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runtime_utils import read_object, read_json
from validate_payload import validate


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    "master_plan": ROOT / "schemas/master-plan.schema.json",
    "sub_plans": ROOT / "schemas/sub-plan.schema.json",
    "batches": ROOT / "schemas/planning-batch.schema.json",
    "tasks": ROOT / "schemas/planning-task.schema.json",
    "decisions": ROOT / "schemas/decision.schema.json",
    "assumptions": ROOT / "schemas/assumption.schema.json",
    "risks": ROOT / "schemas/risk.schema.json",
    "change_requests": ROOT / "schemas/change-request.schema.json",
}

ID_FIELDS = {
    "master_plan": "plan_id",
    "sub_plans": "sub_plan_id",
    "batches": "batch_id",
    "tasks": "task_id",
    "decisions": "decision_id",
    "assumptions": "assumption_id",
    "risks": "risk_id",
    "change_requests": "change_request_id",
}


def documents(value: Any, key: str) -> list[dict[str, Any]]:
    if key == "master_plan":
        if not isinstance(value, dict):
            raise ValueError("master_plan must be an object")
        return [value]
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{key} must be an array of objects")
    return value


def add_schema_errors(errors: list[str], key: str, values: list[dict[str, Any]]) -> None:
    schema = read_json(SCHEMAS[key])
    for index, value in enumerate(values):
        for error in validate(value, schema, f"$.{key}[{index}]" if key != "master_plan" else "$.master_plan", base_path=SCHEMAS[key].resolve().parent):
            errors.append(error)


def index_documents(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
    index: dict[str, dict[str, Any]] = {}
    kinds: dict[str, str] = {}
    errors: list[str] = []
    for key, id_field in ID_FIELDS.items():
        for item in documents(manifest.get(key), key):
            identifier = item.get(id_field)
            if not isinstance(identifier, str) or not identifier.strip():
                continue
            if identifier in index:
                errors.append(f"duplicate planning ID: {identifier} ({kinds[identifier]} and {key})")
            else:
                index[identifier] = item
                kinds[identifier] = key
    return index, kinds, errors


def detect_cycles(nodes: set[str], edges: dict[str, list[str]], label: str, errors: list[str]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in visiting:
            cycle = " -> ".join(path[path.index(node):] + [node])
            errors.append(f"{label} dependency cycle: {cycle}")
            return
        if node in visited:
            return
        visiting.add(node)
        for dependency in edges.get(node, []):
            if dependency in nodes:
                visit(dependency, path + [dependency])
        visiting.remove(node)
        visited.add(node)

    for node in sorted(nodes):
        visit(node, [node])


def normalize_scope(path: str) -> str:
    value = path.replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    return value.rstrip("/") or "."


def scopes_overlap(left: str, right: str) -> bool:
    left = normalize_scope(left)
    right = normalize_scope(right)
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def validate_relationships(manifest: dict[str, Any], errors: list[str]) -> None:
    index, kinds, index_errors = index_documents(manifest)
    errors.extend(index_errors)
    master = manifest["master_plan"]
    master_id = master["plan_id"]
    sub_plans = documents(manifest.get("sub_plans"), "sub_plans")
    batches = documents(manifest.get("batches"), "batches")
    tasks = documents(manifest.get("tasks"), "tasks")
    decisions = documents(manifest.get("decisions"), "decisions")

    for sub_plan in sub_plans:
        if sub_plan.get("master_plan_id") != master_id:
            errors.append(f"sub-plan {sub_plan.get('sub_plan_id')} does not reference master plan {master_id}")
        for dependency in sub_plan.get("dependencies", []):
            if dependency not in {item.get("sub_plan_id") for item in sub_plans}:
                errors.append(f"missing sub-plan dependency: {dependency}")

    sub_plan_ids = {item.get("sub_plan_id") for item in sub_plans}
    batch_ids = {item.get("batch_id") for item in batches}
    task_ids = {item.get("task_id") for item in tasks}
    for batch in batches:
        if batch.get("sub_plan_id") not in sub_plan_ids:
            errors.append(f"batch {batch.get('batch_id')} references missing sub-plan: {batch.get('sub_plan_id')}")
        for dependency in batch.get("depends_on", []):
            if dependency not in batch_ids:
                errors.append(f"missing batch dependency: {dependency}")
        for task_id in batch.get("tasks", []):
            task = index.get(task_id)
            if task is None or kinds.get(task_id) != "tasks":
                errors.append(f"batch {batch.get('batch_id')} references missing task: {task_id}")
            elif task.get("batch_id") != batch.get("batch_id"):
                errors.append(f"task {task_id} is assigned to a different batch")

    task_edges: dict[str, list[str]] = {}
    for task in tasks:
        task_id = task.get("task_id")
        task_edges[task_id] = list(task.get("depends_on", []))
        if task.get("batch_id") not in batch_ids:
            errors.append(f"task {task_id} references missing batch: {task.get('batch_id')}")
        for dependency in task.get("depends_on", []):
            if dependency not in task_ids:
                errors.append(f"missing task dependency: {dependency}")
        if not task.get("acceptance_criteria"):
            errors.append(f"task {task_id} has no acceptance criteria")
        if not task.get("verification"):
            errors.append(f"task {task_id} has no verification plan")
    detect_cycles(task_ids, task_edges, "task", errors)
    detect_cycles(batch_ids, {item.get("batch_id"): list(item.get("depends_on", [])) for item in batches}, "batch", errors)

    requirements = master.get("requirements", [])
    requirement_ids = {item.get("requirement_id") for item in requirements if isinstance(item, dict)}
    traced = {requirement for task in tasks for requirement in task.get("requirement_ids", [])}
    for requirement in sorted(requirement_ids - traced):
        errors.append(f"untraceable requirement: {requirement}")

    accepted_decisions = {
        item.get("decision_id") for item in decisions if str(item.get("status", "")).upper() == "ACCEPTED"
    }
    for task in tasks:
        for decision_id in task.get("architecture_decisions", []):
            if decision_id not in accepted_decisions:
                errors.append(f"task {task.get('task_id')} requires unapproved architecture decision: {decision_id}")

    scoped_tasks = [(task.get("task_id"), scope) for task in tasks for scope in task.get("write_scope", [])]
    for index, (left_task, left_scope) in enumerate(scoped_tasks):
        for right_task, right_scope in scoped_tasks[index + 1:]:
            if left_task != right_task and scopes_overlap(left_scope, right_scope):
                errors.append(f"overlapping write scope: {left_task}:{left_scope} and {right_task}:{right_scope}")


def validate_manifest(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["planning input must be an object"]
    errors: list[str] = []
    try:
        for key in ID_FIELDS:
            add_schema_errors(errors, key, documents(value.get(key), key))
        if "master_plan" not in value:
            errors.append("master_plan is required")
        else:
            validate_relationships(value, errors)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        errors = validate_manifest(read_object(args.input))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PLANNING_INVALID: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"PLANNING_INVALID: {error}", file=sys.stderr)
        return 1
    print("PLANNING_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
