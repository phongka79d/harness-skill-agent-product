"""Write a validated handoff.json artifact with an execution receipt."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from load_config import load_config  # noqa: E402
from schema_validation import validate_file  # noqa: E402

from artifact_writer import (  # noqa: E402
    ensure_task_binding,
    load_and_validate,
    persist_artifact,
)
from runtime_utils import read_json, sha256_json  # noqa: E402

DECISION_SCHEMA = HERE.parents[1] / "schemas" / "workflow-decision.schema.json"


def _validate_receipt(
    project_root: str,
    payload: dict[str, Any],
    decision_path: str | None,
    config_path: str | None,
) -> None:
    receipt = payload["execution_receipt"]
    if receipt["status"] != payload["status"]:
        raise ValueError("execution receipt status must match handoff status")
    if not receipt["evidence"].strip():
        raise ValueError("execution receipt evidence must not be empty")
    task = ensure_task_binding(project_root, payload["task_id"])
    if receipt["task_id"] != payload["task_id"] or task["task_id"] != payload["task_id"]:
        raise ValueError("execution receipt task_id does not match the handoff task")
    stages = task.get("stages")
    if decision_path:
        stages = read_json(decision_path).get("stages")
    if not isinstance(stages, list):
        stages = []
    owners = {str(item.get("id")): str(item.get("owner")) for item in stages if isinstance(item, dict)}
    expected_owner = owners.get(str(receipt.get("stage")))
    if expected_owner is None:
        raise ValueError("execution receipt stage is not present in the resolved workflow")
    if receipt.get("role") != expected_owner:
        raise ValueError("execution receipt role does not own the recorded stage")
    plan_binding = task.get("plan_task_id")
    if plan_binding is not None and receipt.get("plan_task_id") != plan_binding:
        raise ValueError("execution receipt plan_task_id does not match the task")
    if receipt["outcome"] == "BLOCKED" and payload["status"] != "BLOCKED":
        raise ValueError("BLOCKED outcome requires a BLOCKED handoff")
    if receipt["status"] == "BLOCKED" and receipt["outcome"] != "BLOCKED":
        raise ValueError("BLOCKED receipt status requires a BLOCKED outcome")
    if receipt["attempt"] > receipt["max_attempts"]:
        raise ValueError("execution attempt exceeds the recorded limit")
    if receipt["repair_rounds"] > receipt["max_repair_rounds"]:
        raise ValueError("repair rounds exceed the recorded limit")

    if not decision_path:
        if receipt["workflow_decision_hash"] != task["workflow_decision_hash"]:
            raise ValueError("execution receipt is not bound to the active workflow decision")
        return
    decision = read_json(decision_path)
    validate_file(decision, DECISION_SCHEMA, "workflow decision")
    expected_hash = sha256_json(
        {key: value for key, value in decision.items() if key != "decision_hash"}
    )
    if decision["decision_hash"] != expected_hash:
        raise ValueError("workflow decision hash does not match its content")
    config = load_config(config_path)
    if decision["config_hash"] != sha256_json(config):
        raise ValueError("workflow decision was created from a different configuration")
    if receipt["workflow_decision_hash"] != decision["decision_hash"]:
        raise ValueError("execution receipt workflow_decision_hash does not match the decision")
    if task["workflow_decision_hash"] != decision["decision_hash"]:
        raise ValueError("handoff decision does not match the active task")
    contract = decision["execution_contract"]
    depth = decision["execution_depth"]
    workflow_limit = config["workflow"][f"{depth}_max_repair_cycles"]
    policy_limit = config["subagent_policy"]["depths"][depth]["max_repair_rounds"]
    if workflow_limit != policy_limit:
        raise ValueError("repair limit sources diverge in central configuration")
    if receipt["max_attempts"] != contract["dispatch"]["max_total"]:
        raise ValueError("receipt max_attempts does not match the dispatch contract")
    if receipt["max_repair_rounds"] != contract["repair"]["max_repair_rounds"] or receipt["max_repair_rounds"] != workflow_limit:
        raise ValueError("receipt max_repair_rounds does not match the repair contract")
    fallback_values = contract["receipt"]["fallback_values"]
    if receipt["outcome"] not in fallback_values:
        raise ValueError("execution receipt outcome is not allowed by the decision")
    if receipt["outcome"] == "SYNTHESIZED FALLBACK" and not contract["dispatch"]["synthesized_fallback"]:
        raise ValueError("synthesized fallback is not allowed by the decision")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        result = load_and_validate(args.input, "handoff.schema.json", "handoff.json")
        _validate_receipt(args.project_root, result, args.decision, args.config)
        result = persist_artifact(args.project_root, result, "handoff.json", "HANDOFF_WRITTEN")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ARTIFACT_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
