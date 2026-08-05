"""Validate and record a dispatch decision without spawning an agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime_utils import read_payload, write_json_atomic
from dispatch_contract import validate_dispatch_schema
from dispatch_transaction import persist_dispatch
from review_contract import validate_contract
from risk_flags import normalize_risk_flags
from resolve_skill_route import resolve_skill_route, validate_skill_route

CONFIG_SKILL = Path(__file__).resolve().parents[2] / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))

from load_config import load_config, load_deployment_config, resolve_agent, validate_dispatch_selection  # noqa: E402


def _dispatch_skill_route(result: dict[str, object], config: dict[str, object]) -> dict[str, object]:
    """Resolve routing before persistence while keeping legacy dispatch inputs valid."""
    nested_task = result.get("planning_task", result.get("task"))
    task = nested_task if isinstance(nested_task, dict) else {}
    contract = task.get("review_contract") if isinstance(task, dict) else None
    if not isinstance(contract, dict):
        contract = result.get("review_contract") if isinstance(result.get("review_contract"), dict) else {}
    raw_risk = result.get("risk_flags", task.get("risk_flags", contract.get("risk_flags", {})))
    risk_flags = normalize_risk_flags(raw_risk)
    current_state = result.get("current_state", result.get("task_state", result.get("task_status", result.get("planning_status", "UNSPECIFIED"))))
    if not isinstance(current_state, str) or not current_state.strip():
        current_state = "UNSPECIFIED"
    task_type = result.get("task_type", task.get("task_type", contract.get("task_type", "standard")))
    profile = result.get("project_profile", contract.get("project_profile", contract.get("profile_id", "personal")))
    intent = result.get("intent_classification", result.get("intent", "unspecified"))
    repair = bool(result.get("repair")) or str(current_state).upper() in {"REPAIR_REQUIRED", "FAILED", "BLOCKED"} or bool(result.get("investigation_id"))
    requested_role = result.get("requested_role", result.get("agent_role"))
    route_config = config.get("skill_routing", {})
    if not isinstance(route_config, dict):
        raise ValueError("skill_routing must be an object")
    configured = route_config.get("available_skills", [])
    if not isinstance(configured, list):
        raise ValueError("skill_routing.available_skills must be an array")
    context = {
        "intent_classification": intent,
        "current_state": current_state,
        "task_type": task_type,
        "repair": repair,
        "risk_flags": risk_flags,
        "project_profile": profile,
        "requested_role": requested_role,
    }
    supplied = result.get("skill_route")
    if supplied is None:
        # Legacy dispatches receive the same deterministic route and load its full chain.
        return resolve_skill_route(context, configured_skills=configured, config=config)
    supplied_route = validate_skill_route(supplied, configured_skills=configured)
    expected = resolve_skill_route(
        context,
        configured_skills=configured,
        loaded_skills=supplied_route["loaded_skills"],
        config=config,
    )
    for field in ("intent_classification", "task_type", "current_state", "risk_flags", "project_profile", "requested_role", "applicable_skills", "required_skills", "routing_policy_version"):
        if supplied_route.get(field) != expected.get(field):
            raise ValueError(f"skill_route.{field} does not match deterministic routing")
    return supplied_route


def normalize_dispatch(
    value: object,
    config: dict[str, object],
    deployment: dict[str, object] | None = None,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("dispatch must be an object")
    validate_dispatch_schema(value)
    result = dict(value)
    if "risk_flags" in result:
        result["risk_flags"] = normalize_risk_flags(result["risk_flags"])
    for field in ("planning_task", "task"):
        nested_task = result.get(field)
        if nested_task is None:
            continue
        if not isinstance(nested_task, dict):
            raise ValueError(f"dispatch.{field} must be an object")
        normalized_task = dict(nested_task)
        if "risk_flags" in normalized_task:
            normalized_task["risk_flags"] = normalize_risk_flags(normalized_task["risk_flags"])
        if "review_contract" in normalized_task:
            normalized_task["review_contract"] = validate_contract(normalized_task["review_contract"], review_type="task")
        result[field] = normalized_task
    planned_task = result.get("planning_task", result.get("task"))
    approved = bool(result.get("approved")) or str(
        result.get("task_status", result.get("planning_status", result.get("approval_status", "")))
    ).upper() in {"APPROVED", "ACCEPTED"}
    if planned_task is not None:
        owner = planned_task.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("dispatch planning task requires an owner")
        if approved:
            validate_contract(planned_task.get("review_contract"), review_type="task")
    if approved:
        owner = result.get("task_owner", result.get("owner"))
        if planned_task is None and (not isinstance(owner, str) or not owner.strip()):
            raise ValueError("approved dispatch requires a task owner")
        validate_contract(result.get("review_contract"), review_type="task")
    elif "review_contract" in result:
        validate_contract(result["review_contract"], review_type="task")
    for field in ("dispatch_id", "task_id", "agent_role", "selected_owner", "selected_model"):
        if not isinstance(result.get(field), str) or not str(result[field]).strip():
            raise ValueError(f"dispatch.{field} must be a non-empty string")
    model_reference = result.get("model_reference")
    expected_reference = f"agents.{result['agent_role']}.model_ref"
    template = "${deployment.model_ids[" + expected_reference + "]}"
    if model_reference == expected_reference and result["selected_model"] == template:
        resolved = resolve_agent(config, result["agent_role"], deployment)
        result["selected_model"] = resolved["model_dispatch"]
    validate_dispatch_selection(result, config, deployment)
    mode = str(result.get("selected_mode", "")).upper()
    if mode not in {"ASYNC", "SYNC"}:
        raise ValueError("dispatch.selected_mode must be ASYNC or SYNC")
    result["selected_mode"] = mode
    if not isinstance(result.get("input_revisions"), dict):
        raise ValueError("dispatch.input_revisions must be an object")
    if not isinstance(result.get("approval_references"), list) or any(not isinstance(item, str) for item in result["approval_references"]):
        raise ValueError("dispatch.approval_references must be an array of strings")
    if not isinstance(result.get("evidence"), dict):
        raise ValueError("dispatch.evidence must be an object")
    architecture_owner = result["evidence"].get("architecture_owner")
    if architecture_owner is not None and architecture_owner != result["selected_owner"]:
        raise ValueError("dispatch cannot change architecture ownership")
    result["skill_route"] = _dispatch_skill_route(result, config)
    result["status"] = "RECORDED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    parser.add_argument("--deployment")
    args = parser.parse_args()
    try:
        config = load_config()
        deployment = load_deployment_config(args.deployment, config)
        result = normalize_dispatch(read_payload(args.input), config, deployment)
        result = persist_dispatch(args.project_root, result, config, deployment)
        if args.output:
            write_json_atomic(args.output, result)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"DISPATCH_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
