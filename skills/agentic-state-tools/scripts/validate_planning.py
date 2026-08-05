"""Validate planning documents, ownership, traceability, and write conflicts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from runtime_utils import read_object, read_json, validate_identifier
from validate_payload import validate


ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT.parent / "agentic-configuration"
sys.path.insert(0, str(CONFIG_ROOT / "scripts"))

from load_config import load_config  # noqa: E402
from authorization import require_persisted_approval  # noqa: E402
from review_contract import validate_contract  # noqa: E402
from risk_flags import normalize_risk_flags  # noqa: E402
from validate_no_placeholders import find_placeholders  # noqa: E402


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
APPROVAL_SCHEMA = ROOT / "schemas/approval.schema.json"

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


_EXACT_PATH_FORBIDDEN = re.compile(r"(^/|^[A-Za-z]:[\\/]|\.\.|[*?\[\]])")
_HIDDEN_ARCHITECTURE = re.compile(
    r"\b(?:choose|select|pick|decide)\s+(?:an?\s+|the\s+)?"
    r"(?:architecture|database|framework|library|protocol|interface|design)\b|"
    r"\b(?:design|architect)\s+(?:an?\s+|the\s+)?"
    r"(?:new\s+)?(?:architecture|api|protocol|system)\b|"
    r"\bintroduce\s+(?:an?\s+|the\s+)?(?:new\s+)?(?:architecture|framework|protocol)\b",
    re.IGNORECASE,
)
_COMMAND_PREFIX = re.compile(
    r"^(?:python(?:\s|$)|py\s|pytest\b|(?:python|py)\s+-m\s|"
    r"npm\b|pnpm\b|yarn\b|cargo\b|go\b|make\b|dotnet\b|"
    r"bash\b|pwsh\b|powershell\b|git\s+(?:diff|status|check)|"
    r"[A-Za-z]:\\|\./|\.\\)",
    re.IGNORECASE,
)


def _is_executable_task(task: dict[str, Any]) -> bool:
    return task.get("contract_mode") == "executable" or task.get("strict") is True


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        return None
    return [item.strip() for item in value]


def _normalize_repo_path(value: str) -> str:
    return normalize_scope(value).replace("\\", "/")


def _valid_exact_path(value: str) -> bool:
    normalized = _normalize_repo_path(value)
    return bool(normalized and normalized != "." and not normalized.endswith("/") and not _EXACT_PATH_FORBIDDEN.search(normalized))


def _scope_contains(scope: str, path: str) -> bool:
    normalized_scope = _normalize_repo_path(scope)
    normalized_path = _normalize_repo_path(path)
    return normalized_scope == "." or normalized_path == normalized_scope or normalized_path.startswith(normalized_scope + "/")


def _expected_result_is_present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, dict) and isinstance(value.get("result"), str) and bool(value["result"].strip())


def _validate_executable_task(task: dict[str, Any], decisions: list[dict[str, Any]], errors: list[str]) -> None:
    task_id = str(task.get("task_id"))
    required = (
        "prerequisite_decisions", "exact_paths", "relevant_symbols", "allowed_files", "forbidden_files",
        "dependency_ids", "implementation_steps", "validation_mode", "validation_steps", "red_required",
        "expected_green", "verification_commands", "acceptance_criteria_ids", "handoff_expectations",
        "file_responsibility_map",
    )
    for field in required:
        if field not in task:
            errors.append(f"executable task {task_id} requires field: {field}")

    placeholder_errors = find_placeholders(task)
    errors.extend(f"task {task_id} {finding}" for finding in placeholder_errors)

    exact_paths = _string_list(task.get("exact_paths")) or []
    allowed_files = _string_list(task.get("allowed_files")) or []
    forbidden_files = _string_list(task.get("forbidden_files")) or []
    dependency_ids = _string_list(task.get("dependency_ids")) or []
    depends_on = _string_list(task.get("depends_on")) or []
    implementation_steps = _string_list(task.get("implementation_steps")) or []
    validation_steps = _string_list(task.get("validation_steps")) or []
    verification_commands = _string_list(task.get("verification_commands")) or []
    acceptance_ids = _string_list(task.get("acceptance_criteria_ids")) or []
    handoff = _string_list(task.get("handoff_expectations")) or []

    for field, values in (("exact_paths", exact_paths), ("allowed_files", allowed_files), ("forbidden_files", forbidden_files)):
        for path in values:
            if not _valid_exact_path(path):
                errors.append(f"executable task {task_id} {field} contains a non-exact repository path: {path}")
    if set(exact_paths) - set(allowed_files):
        missing = sorted(set(exact_paths) - set(allowed_files))
        errors.append(f"executable task {task_id} exact_paths are not all allowed_files: {', '.join(missing)}")
    forbidden_overlap = sorted(set(forbidden_files) & (set(exact_paths) | set(allowed_files)))
    if forbidden_overlap:
        errors.append(f"executable task {task_id} allowed and forbidden files overlap: {', '.join(forbidden_overlap)}")
    if sorted(dependency_ids) != sorted(depends_on):
        errors.append(f"executable task {task_id} dependency_ids must exactly match depends_on")
    if len(exact_paths) > 32 or len(implementation_steps) > 20:
        errors.append(f"executable task {task_id} exceeds the bounded one-attempt task size")

    write_scope = task.get("write_scope", [])
    if isinstance(write_scope, list):
        for path in exact_paths:
            if not any(isinstance(scope, str) and _scope_contains(scope, path) for scope in write_scope):
                errors.append(f"executable task {task_id} exact path is outside write_scope: {path}")
    else:
        errors.append(f"executable task {task_id} write_scope must be an array")

    criterion_ids = [item.get("criterion_id") for item in task.get("acceptance_criteria", []) if isinstance(item, dict)]
    if len(criterion_ids) != len(set(criterion_ids)):
        errors.append(f"executable task {task_id} has duplicate acceptance criterion IDs")
    if sorted(acceptance_ids) != sorted(str(item) for item in criterion_ids):
        errors.append(f"executable task {task_id} acceptance_criteria_ids must exactly match acceptance criteria")

    validation_mode = task.get("validation_mode")
    red_required = task.get("red_required")
    if validation_mode not in {"TDD", "ALTERNATIVE"}:
        errors.append(f"executable task {task_id} validation_mode must be TDD or ALTERNATIVE")
    if not isinstance(red_required, bool):
        errors.append(f"executable task {task_id} red_required must be boolean")
    elif validation_mode == "TDD" and not red_required:
        errors.append(f"executable task {task_id} TDD validation requires red_required=true")
    if red_required and not _expected_result_is_present(task.get("expected_red")):
        errors.append(f"executable task {task_id} requires an expected_red result")
    if not _expected_result_is_present(task.get("expected_green")):
        errors.append(f"executable task {task_id} requires an expected_green result")
    if not verification_commands:
        errors.append(f"executable task {task_id} requires exact verification commands")
    for command in verification_commands:
        if not _COMMAND_PREFIX.search(command.strip()):
            errors.append(f"executable task {task_id} verification command is not executable: {command}")
    if validation_steps and not any(_COMMAND_PREFIX.search(step.strip()) for step in validation_steps):
        errors.append(f"executable task {task_id} validation_steps contain no runnable command or explicit test action")

    risk_flags = task.get("risk_flags", {})
    risk_active = isinstance(risk_flags, dict) and any(bool(value) for value in risk_flags.values())
    if risk_active and (
        not isinstance(task.get("rollback_recovery_note"), str)
        or not task["rollback_recovery_note"].strip()
    ):
        errors.append(f"executable task {task_id} requires rollback_recovery_note when risk_flags are active")

    architecture_decision_ids = {item.get("decision_id") for item in decisions if isinstance(item, dict)}
    accepted_decision_ids = {
        item.get("decision_id") for item in decisions
        if isinstance(item, dict) and str(item.get("status", "")).upper() == "ACCEPTED"
    }
    for decision_id in task.get("prerequisite_decisions", []):
        if decision_id not in architecture_decision_ids:
            errors.append(f"executable task {task_id} references unknown prerequisite decision: {decision_id}")
        elif decision_id not in accepted_decision_ids:
            errors.append(f"executable task {task_id} requires unapproved prerequisite decision: {decision_id}")

    if not task.get("architecture_decisions") and _HIDDEN_ARCHITECTURE.search(
        " ".join([str(task.get("objective", "")), *implementation_steps])
    ):
        errors.append(f"executable task {task_id} contains a hidden architecture decision")

    responsibility_map = task.get("file_responsibility_map", [])
    map_paths: set[str] = set()
    relevant_symbols = set(_string_list(task.get("relevant_symbols")) or [])
    if isinstance(responsibility_map, list):
        for entry in responsibility_map:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if isinstance(path, str):
                normalized = _normalize_repo_path(path)
                map_paths.add(normalized)
                if normalized not in {_normalize_repo_path(item) for item in exact_paths}:
                    errors.append(f"executable task {task_id} responsibility map path is not in exact_paths: {path}")
            for symbol in entry.get("symbols", []):
                if symbol not in relevant_symbols:
                    errors.append(f"executable task {task_id} responsibility symbol is not listed in relevant_symbols: {symbol}")
                if isinstance(symbol, str) and "::" in symbol and _normalize_repo_path(symbol.split("::", 1)[0]) != _normalize_repo_path(str(path)):
                    errors.append(f"executable task {task_id} symbol/interface path is inconsistent: {symbol}")
    if map_paths != {_normalize_repo_path(item) for item in exact_paths}:
        errors.append(f"executable task {task_id} file_responsibility_map must cover every exact_path exactly once")

    for reference in relevant_symbols:
        if "::" in reference:
            path, symbol = reference.split("::", 1)
            if not path or not symbol or _normalize_repo_path(path) not in map_paths:
                errors.append(f"executable task {task_id} relevant symbol/interface is not mapped: {reference}")


def _validate_executable_cross_task_ownership(tasks: list[dict[str, Any]], errors: list[str]) -> None:
    paths: dict[str, tuple[str, str]] = {}
    symbols: dict[str, tuple[str, str, str]] = {}
    for task in tasks:
        if not _is_executable_task(task):
            continue
        task_id = str(task.get("task_id"))
        for entry in task.get("file_responsibility_map", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                continue
            path = _normalize_repo_path(entry["path"])
            owner = str(entry.get("owner", ""))
            previous = paths.get(path)
            if previous:
                errors.append(
                    f"executable task scope overlap: {task_id}:{path} already owned by {previous[1]} in {previous[0]}"
                )
            else:
                paths[path] = (task_id, owner)
            for symbol in entry.get("symbols", []):
                if not isinstance(symbol, str):
                    continue
                key = symbol if "::" in symbol else f"{path}::{symbol}"
                previous_symbol = symbols.get(key)
                if previous_symbol and previous_symbol[1] != owner:
                    errors.append(
                        f"executable task symbol/interface ownership conflict: {key} belongs to "
                        f"{previous_symbol[1]} in {previous_symbol[0]} and {owner} in {task_id}"
                    )
                elif not previous_symbol:
                    symbols[key] = (task_id, owner, path)


def _approval_records(manifest: dict[str, Any], approval_root: str | Path | None = None, groups: set[str] | None = None) -> list[dict[str, Any]]:
    if approval_root is None:
        return []
    root = Path(approval_root).expanduser().resolve()
    records: list[dict[str, Any]] = []
    approval_schema = read_json(APPROVAL_SCHEMA)
    for group in sorted(groups or set()):
        validate_identifier(group, "shared_write_group")
        path = root / "approvals" / f"SHARED_WRITE-{group}.json"
        if not path.is_file():
            continue
        approval = read_object(path)
        schema_errors = validate(approval, approval_schema, base_path=APPROVAL_SCHEMA.resolve().parent)
        if schema_errors:
            raise ValueError("shared-write approval schema validation failed: " + "; ".join(schema_errors))
        require_persisted_approval(root, approval, target_type="SHARED_WRITE", target_id=group)
        records.append(approval)
    return records


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
        and record.get("target_type") == "SHARED_WRITE"
        and record.get("target_id") == group
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
    if left.get("shared_write_group") or right.get("shared_write_group"):
        if _shared_write_approved(left, right, approvals or []):
            return "APPROVED_SHARED_WRITE"
        return "INVALID_SHARED_WRITE_APPROVAL"
    if has_dependency_path(left_id, right_id, task_edges) or has_dependency_path(right_id, left_id, task_edges):
        return "SEQUENTIAL_OVERLAP"
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


def _task_acceptance_ids(task: dict[str, Any]) -> list[tuple[str, list[str]]]:
    result: list[tuple[str, list[str]]] = []
    for index, criterion in enumerate(task.get("acceptance_criteria", [])):
        if isinstance(criterion, dict):
            criterion_id = criterion.get("criterion_id", index)
            result.append((str(criterion_id), list(criterion.get("requirement_ids", []))))
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
            f"{task.get('task_id')}[{criterion_id}]"
            for task in tasks
            for criterion_id, requirement_ids in _task_acceptance_ids(task)
            if identifier in requirement_ids
        )
        status = "DEPRECATED" if _is_deprecated(requirement) else ("TRACED" if task_ids or criteria else "UNTRACED")
        rows.append({"requirement": identifier, "tasks": task_ids, "acceptance_criteria": criteria, "status": status})
    return rows


def _validate_owners(tasks: list[dict[str, Any]], errors: list[str]) -> None:
    config = load_config()
    agents = config.get("agents", {})
    planning = config.get("planning")
    if not isinstance(planning, dict):
        errors.append("central planning policy is missing from agentic configuration")
        return
    aliases = planning.get("owner_aliases")
    task_capabilities = planning.get("task_type_capabilities")
    if not isinstance(aliases, dict) or not isinstance(task_capabilities, dict):
        errors.append("central planning policy must define owner_aliases and task_type_capabilities")
        return
    for task in tasks:
        task_id = task.get("task_id")
        owner = task.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            errors.append(f"task {task_id} requires an owner")
            continue
        owner_id = aliases.get(owner, owner)
        agent = agents.get(owner_id)
        if not isinstance(agent, dict):
            errors.append(f"task {task_id} owner is unknown: {owner}")
            continue
        capability = task_capabilities.get(str(task.get("task_type", "")).lower())
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
        for criterion_id, requirement_ids in _task_acceptance_ids(task):
            for requirement_id in requirement_ids:
                if requirement_id not in known:
                    errors.append(f"task {task_id} acceptance criterion {criterion_id} references unknown requirement: {requirement_id}")
                elif requirement_id in deprecated:
                    errors.append(f"task {task_id} acceptance criterion {criterion_id} references deprecated requirement: {requirement_id}")
                elif requirement_id not in task_requirements:
                    errors.append(f"task {task_id} acceptance criterion {criterion_id} is not traced by task requirement_ids")
                else:
                    traced.add(requirement_id)
    for requirement_id in sorted(known - deprecated - traced):
        errors.append(f"untraceable requirement: {requirement_id}")


def validate_relationships(manifest: dict[str, Any], errors: list[str], approval_root: str | Path | None = None) -> None:
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
        criterion_ids = {item.get("criterion_id") for item in task.get("acceptance_criteria", []) if isinstance(item, dict)}
        verification_cases = task.get("verification_cases", [])
        if verification_cases:
            case_ids: set[str] = set()
            for case in verification_cases:
                case_id = case.get("verification_case_id") if isinstance(case, dict) else None
                if case_id in case_ids:
                    errors.append(f"task {task_id} has duplicate verification case: {case_id}")
                if isinstance(case_id, str):
                    case_ids.add(case_id)
                mapped = case.get("acceptance_criterion_ids", []) if isinstance(case, dict) else []
                unknown = sorted(set(mapped) - criterion_ids) if isinstance(mapped, list) else []
                if unknown:
                    errors.append(
                        f"task {task_id} verification case {case_id} references unknown acceptance criteria: {', '.join(unknown)}"
                    )
                if isinstance(case, dict) and case.get("red_required") is True and not case.get("red_command"):
                    errors.append(f"task {task_id} verification case {case_id} requires a RED command")
                if isinstance(case, dict) and not case.get("green_command"):
                    errors.append(f"task {task_id} verification case {case_id} requires a GREEN command")
        for exception in task.get("verification_exceptions", []):
            if not isinstance(exception, dict):
                continue
            if not exception.get("expires_at") and not exception.get("follow_up"):
                errors.append(
                    f"task {task_id} verification exception {exception.get('exception_id')} requires expires_at or follow_up"
                )
        try:
            normalize_risk_flags(task.get("risk_flags", {}))
        except ValueError as exc:
            errors.append(f"task {task_id} risk_flags invalid: {exc}")
        if _bundle_approved(manifest) or str(task.get("status", "")).upper() in {"APPROVED", "ACCEPTED"}:
            try:
                validate_contract(task.get("review_contract"), review_type="task")
            except (TypeError, ValueError) as exc:
                errors.append(f"task {task_id} review_contract invalid: {exc}")
        if _is_executable_task(task):
            _validate_executable_task(task, decisions, errors)
    _validate_executable_cross_task_ownership(tasks, errors)
    detect_cycles(task_ids, task_edges, "task", errors)
    detect_cycles(batch_ids, {item.get("batch_id"): list(item.get("depends_on", [])) for item in batches}, "batch", errors)

    accepted_decisions = {item.get("decision_id") for item in decisions if str(item.get("status", "")).upper() == "ACCEPTED"}
    for task in tasks:
        for decision_id in task.get("architecture_decisions", []):
            if decision_id not in accepted_decisions:
                errors.append(f"task {task.get('task_id')} requires unapproved architecture decision: {decision_id}")

    shared_groups = {
        task.get("shared_write_group")
        for task in tasks
        if isinstance(task.get("shared_write_group"), str) and task.get("shared_write_group").strip()
    }
    approvals = _approval_records(manifest, approval_root, shared_groups)
    for index, left in enumerate(tasks):
        for right in tasks[index + 1:]:
            for left_scope in left.get("write_scope", []):
                for right_scope in right.get("write_scope", []):
                    if scopes_overlap(left_scope, right_scope):
                        classification = classify_scope_overlap(left, right, task_edges, approvals)
                        if classification in {"CONFLICT", "INVALID_SHARED_WRITE_APPROVAL"}:
                            errors.append(f"{classification}: {left.get('task_id')}:{normalize_scope(left_scope)} and {right.get('task_id')}:{normalize_scope(right_scope)}")


def validate_manifest(value: Any, approval_root: str | Path | None = None) -> list[str]:
    if not isinstance(value, dict):
        return ["planning input must be an object"]
    errors: list[str] = []
    try:
        for key in ID_FIELDS:
            add_schema_errors(errors, key, documents(value.get(key), key))
        if "master_plan" not in value:
            errors.append("master_plan is required")
        else:
            validate_relationships(value, errors, approval_root)
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
    parser.add_argument("--approval-root")
    parser.add_argument("--requirements-report", action="store_true")
    args = parser.parse_args()
    try:
        manifest = read_object(args.input)
        errors = validate_manifest(manifest, args.approval_root)
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
