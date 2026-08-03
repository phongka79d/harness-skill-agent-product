"""Validate planning documents, ownership, traceability, and write conflicts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runtime_utils import read_object, read_json
from validate_payload import validate


ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT.parent / "agentic-configuration"
sys.path.insert(0, str(CONFIG_ROOT / "scripts"))

from load_config import load_config  # noqa: E402
from review_contract import validate_contract  # noqa: E402
from risk_flags import normalize_risk_flags  # noqa: E402


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

OWNER_ALIASES = {
    "implementer": "agent-executor",
    "task-reviewer": "agent-review",
    "batch-reviewer": "agent-batch-review",
    "runtime-recovery": "agent-runtime-recovery",
}
TASK_CAPABILITIES = {
    "backend": "repository_editing",
    "frontend": "repository_editing",
    "data": "repository_editing",
    "infrastructure": "repository_editing",
    "documentation": "repository_editing",
    "backend_change": "repository_editing",
    "frontend_change": "repository_editing",
    "data_change": "repository_editing",
    "testing": "testing",
    "review": "evidence_review",
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
        path = "$.master_plan" if key == "master_plan" else f"$.{key}[{index}]"
        errors.extend(validate(value, schema, path, base_path=SCHEMAS[key].resolve().parent))


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


def has_dependency_path(left: str, right: str, task_edges: dict[str, list[str]]) -> bool:
    """Return whether ``left`` transitively depends on ``right``."""
    if left == right:
        return False
    pending = list(task_edges.get(left, []))
    visited: set[str] = set()
    while pending:
        node = pending.pop()
        if node == right:
            return True
        if node in visited:
            continue
        visited.add(node)
        pending.extend(task_edges.get(node, []))
    return False


def _approval_records(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    value = manifest.get("approvals", manifest.get("persisted_approvals", []))
    if isinstance(value, dict):
        value = list(value.values())
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _shared_write_approved(left: dict[str, Any], right: dict[str, Any], approvals: list[dict[str, Any]]) -> bool:
    group = left.get("shared_write_group")
    approval_id = left.get("shared_write_approval_id")
    if not group or group != right.get("shared_write_group"):
        return False
    if str(left.get("execution_mode", "")).upper() != "SYNC" or str(right.get("execution_mode", "")).upper() != "SYNC":
        return False
    if not approval_id or approval_id != right.get("shared_write_approval_id"):
        return False
    return any(
        record.get("approval_id") == approval_id
        and str(record.get("decision", "")).upper() == "APPROVED"
        and (record.get("target_id") in {None, group} or record.get("target_type") in {None, "SHARED_WRITE"})
        for record in approvals
    )


def classify_scope_overlap(
    left: dict[str, Any],
    right: dict[str, Any],
    task_edges: dict[str, list[str]],
    approvals: list[dict[str, Any]] | None = None,
) -> str:
    """Classify one write intersection without considering read scopes."""
    left_id = str(left.get("task_id"))
    right_id = str(right.get("task_id"))
    if has_dependency_path(left_id, right_id, task_edges) or has_dependency_path(right_id, left_id, task_edges):
        return "SEQUENTIAL_OVERLAP"
    if _shared_write_approved(left, right, approvals or []):
        return "APPROVED_SHARED_WRITE"
    if left.get("shared_write_group") or right.get("shared_write_group"):
        return "INVALID_SHARED_WRITE_APPROVAL"
    return "CONFLICT"


def _is_deprecated(requirement: dict[str, Any]) -> bool:
    return bool(requirement.get("deprecated")) or str(requirement.get("status", "")).upper() in {"DEPRECATED", "RETIRED"}


def _requirement_records(master: dict[str, Any], errors: list[str]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    records: dict[str, dict[str, Any]] = {}
    deprecated: set[str] = set()
    for requirement in master.get("requirements", []):
        identifier = requirement.get("requirement_id") if isinstance(requirement, dict) else None
        if not isinstance(identifier, str) or not identifier.strip():
            continue
        if identifier in records:
            errors.append(f"duplicate requirement ID: {identifier}")
            continue
        records[identifier] = requirement
        if _is_deprecated(requirement):
            deprecated.add(identifier)
    return records, deprecated


def _task_acceptance_ids(task: dict[str, Any]) -> list[tuple[int, list[str]]]:
    result: list[tuple[int, list[str]]] = []
    for index, criterion in enumerate(task.get("acceptance_criteria", [])):
        if isinstance(criterion, dict):
            result.append((index, list(criterion.get("requirement_ids", []))))
    return result


def requirement_report(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Build sorted requirement trace rows for human and machine inspection."""
    master = manifest.get("master_plan", {})
    tasks = documents(manifest.get("tasks"), "tasks")
    rows: list[dict[str, Any]] = []
    for requirement in sorted(master.get("requirements", []), key=lambda item: str(item.get("requirement_id", ""))):
        identifier = requirement.get("requirement_id")
        task_ids = sorted({task.get("task_id") for task in tasks if identifier in task.get("requirement_ids", [])})
        criteria = sorted(
            f"{task.get('task_id')}[{index}]"
            for task in tasks
            for index, requirement_ids in _task_acceptance_ids(task)
            if identifier in requirement_ids
        )
        status = "DEPRECATED" if _is_deprecated(requirement) else ("TRACED" if task_ids or criteria else "UNTRACED")
        rows.append({"requirement": identifier, "tasks": task_ids, "acceptance_criteria": criteria, "status": status})
    return rows


def _validate_owners(tasks: list[dict[str, Any]], errors: list[str]) -> None:
    config = load_config()
    agents = config.get("agents", {})
    for task in tasks:
        task_id = task.get("task_id")
        owner = task.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            errors.append(f"task {task_id} requires an owner")
            continue
        owner_id = OWNER_ALIASES.get(owner, owner)
        agent = agents.get(owner_id)
        if not isinstance(agent, dict):
            errors.append(f"task {task_id} owner is unknown: {owner}")
            continue
        capability = TASK_CAPABILITIES.get(str(task.get("task_type", "")).lower())
        if capability is None:
            errors.append(f"task {task_id} has unknown task type: {task.get('task_type')}")
            continue
        capabilities = set(agent.get("capabilities", []))
        forbidden = set(agent.get("forbidden", []))
        if capability not in capabilities:
            errors.append(f"task {task_id} owner {owner} lacks capability: {capability}")
        if capability in forbidden:
            errors.append(f"task {task_id} owner {owner} is forbidden from capability: {capability}")


def _bundle_approved(manifest: dict[str, Any]) -> bool:
    values = [manifest.get("status"), manifest.get("approval_status"), manifest.get("plan_status"), manifest.get("master_plan", {}).get("status")]
    return any(str(value).upper() in {"APPROVED", "ACCEPTED"} for value in values if value is not None)


def _validate_requirements(master: dict[str, Any], tasks: list[dict[str, Any]], errors: list[str]) -> None:
    records, deprecated = _requirement_records(master, errors)
    known = set(records)
    traced: set[str] = set()
    for task in tasks:
        task_id = task.get("task_id")
        task_requirements = task.get("requirement_ids", [])
        for requirement_id in task_requirements:
            if requirement_id not in known:
                errors.append(f"task {task_id} references unknown requirement: {requirement_id}")
            elif requirement_id in deprecated:
                errors.append(f"task {task_id} references deprecated requirement: {requirement_id}")
            else:
                traced.add(requirement_id)
        for index, requirement_ids in _task_acceptance_ids(task):
            for requirement_id in requirement_ids:
                if requirement_id not in known:
                    errors.append(f"task {task_id} acceptance criterion {index} references unknown requirement: {requirement_id}")
                elif requirement_id in deprecated:
                    errors.append(f"task {task_id} acceptance criterion {index} references deprecated requirement: {requirement_id}")
                elif requirement_id not in task_requirements:
                    errors.append(f"task {task_id} acceptance criterion {index} is not traced by task requirement_ids")
                else:
                    traced.add(requirement_id)
    for requirement_id in sorted(known - deprecated - traced):
        errors.append(f"untraceable requirement: {requirement_id}")


def validate_relationships(manifest: dict[str, Any], errors: list[str]) -> None:
    index, kinds, index_errors = index_documents(manifest)
    errors.extend(index_errors)
    master = manifest["master_plan"]
    master_id = master["plan_id"]
    sub_plans = documents(manifest.get("sub_plans"), "sub_plans")
    batches = documents(manifest.get("batches"), "batches")
    tasks = documents(manifest.get("tasks"), "tasks")
    decisions = documents(manifest.get("decisions"), "decisions")

    _validate_owners(tasks, errors)
    _validate_requirements(master, tasks, errors)

    sub_plan_ids = {item.get("sub_plan_id") for item in sub_plans}
    batch_ids = {item.get("batch_id") for item in batches}
    task_ids = {item.get("task_id") for item in tasks}
    batches_by_sub_plan: dict[str, list[str]] = {}
    tasks_by_batch: dict[str, list[str]] = {}
    for sub_plan in sub_plans:
        sub_plan_id = sub_plan.get("sub_plan_id")
        if sub_plan.get("master_plan_id") != master_id:
            errors.append(f"sub-plan {sub_plan_id} does not reference master plan {master_id}")
        listed = sub_plan.get("batches", [])
        if len(listed) != len(set(listed)):
            errors.append(f"sub-plan {sub_plan_id} contains duplicate batch membership")
        for dependency in sub_plan.get("dependencies", []):
            if dependency not in sub_plan_ids:
                errors.append(f"missing sub-plan dependency: {dependency}")
    for batch in batches:
        batch_id = batch.get("batch_id")
        sub_plan_id = batch.get("sub_plan_id")
        batches_by_sub_plan.setdefault(sub_plan_id, []).append(batch_id)
        listed = batch.get("tasks", [])
        if len(listed) != len(set(listed)):
            errors.append(f"batch {batch_id} contains duplicate task membership")
        tasks_by_batch[batch_id] = list(listed)
        if sub_plan_id not in sub_plan_ids:
            errors.append(f"batch {batch_id} references missing sub-plan: {sub_plan_id}")
        for dependency in batch.get("depends_on", []):
            if dependency not in batch_ids:
                errors.append(f"missing batch dependency: {dependency}")
        for task_id in listed:
            task = index.get(task_id)
            if task is None or kinds.get(task_id) != "tasks":
                errors.append(f"batch {batch_id} references missing task: {task_id}")
            elif task.get("batch_id") != batch_id:
                errors.append(f"task {task_id} is assigned to a different batch")
    for sub_plan in sub_plans:
        sub_plan_id = sub_plan.get("sub_plan_id")
        listed = list(sub_plan.get("batches", []))
        reverse = batches_by_sub_plan.get(sub_plan_id, [])
        if set(listed) != set(reverse) or len(reverse) != len(set(reverse)):
            errors.append(f"sub-plan {sub_plan_id} and batch membership is not exact in both directions")
        for batch_id in listed:
            if batch_id not in batch_ids:
                errors.append(f"sub-plan {sub_plan_id} references missing batch: {batch_id}")

    task_edges: dict[str, list[str]] = {}
    for task in tasks:
        task_id = task.get("task_id")
        task_edges[task_id] = list(task.get("depends_on", []))
        batch_id = task.get("batch_id")
        if batch_id not in batch_ids:
            errors.append(f"task {task_id} references missing batch: {batch_id}")
        reverse = [candidate for candidate, task_ids_for_batch in tasks_by_batch.items() if task_id in task_ids_for_batch]
        if len(reverse) != 1 or reverse[0] != batch_id:
            errors.append(f"task {task_id} and batch membership is not exact in both directions")
        for dependency in task.get("depends_on", []):
            if dependency not in task_ids:
                errors.append(f"missing task dependency: {dependency}")
        if not task.get("acceptance_criteria"):
            errors.append(f"task {task_id} has no acceptance criteria")
        if not task.get("verification"):
            errors.append(f"task {task_id} has no verification plan")
        try:
            normalize_risk_flags(task.get("risk_flags", {}))
        except ValueError as exc:
            errors.append(f"task {task_id} risk_flags invalid: {exc}")
        if _bundle_approved(manifest) or str(task.get("status", "")).upper() in {"APPROVED", "ACCEPTED"}:
            try:
                validate_contract(task.get("review_contract"), review_type="task")
            except (TypeError, ValueError) as exc:
                errors.append(f"task {task_id} review_contract invalid: {exc}")
    detect_cycles(task_ids, task_edges, "task", errors)
    detect_cycles(batch_ids, {item.get("batch_id"): list(item.get("depends_on", [])) for item in batches}, "batch", errors)

    accepted_decisions = {item.get("decision_id") for item in decisions if str(item.get("status", "")).upper() == "ACCEPTED"}
    for task in tasks:
        for decision_id in task.get("architecture_decisions", []):
            if decision_id not in accepted_decisions:
                errors.append(f"task {task.get('task_id')} requires unapproved architecture decision: {decision_id}")

    approvals = _approval_records(manifest)
    for index, left in enumerate(tasks):
        for right in tasks[index + 1:]:
            for left_scope in left.get("write_scope", []):
                for right_scope in right.get("write_scope", []):
                    if scopes_overlap(left_scope, right_scope):
                        classification = classify_scope_overlap(left, right, task_edges, approvals)
                        if classification in {"CONFLICT", "INVALID_SHARED_WRITE_APPROVAL"}:
                            errors.append(f"{classification}: {left.get('task_id')}:{normalize_scope(left_scope)} and {right.get('task_id')}:{normalize_scope(right_scope)}")


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


def format_requirement_report(manifest: dict[str, Any]) -> str:
    lines = ["Requirement | Tasks | Acceptance criteria | Status"]
    for row in requirement_report(manifest):
        tasks = ",".join(row["tasks"]) or "-"
        criteria = ",".join(row["acceptance_criteria"]) or "-"
        lines.append(f"{row['requirement']} | {tasks} | {criteria} | {row['status']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--requirements-report", action="store_true")
    args = parser.parse_args()
    try:
        manifest = read_object(args.input)
        errors = validate_manifest(manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PLANNING_INVALID: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"PLANNING_INVALID: {error}", file=sys.stderr)
        return 1
    print("PLANNING_VALID")
    if args.requirements_report:
        print(format_requirement_report(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
