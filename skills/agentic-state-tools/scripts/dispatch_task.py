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

CONFIG_SKILL = Path(__file__).resolve().parents[2] / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))

from load_config import load_config, load_deployment_config, resolve_agent, validate_dispatch_selection  # noqa: E402


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
