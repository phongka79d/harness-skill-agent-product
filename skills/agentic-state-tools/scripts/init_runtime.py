"""Initialize or safely rebind minimal runtime state to a workflow decision."""
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
from load_runtime_settings import ensure_runtime_settings  # noqa: E402
from resolve_workflow import resolve_workflow  # noqa: E402
from render_checklist import render_checklist  # noqa: E402
from schema_validation import validate_file  # noqa: E402
from validate_state import validate_runtime  # noqa: E402
from runtime_utils import (  # noqa: E402
    append_event,
    read_json,
    runtime_root,
    sha256_json,
    utc_now,
    write_json_atomic,
)

DECISION_SCHEMA = HERE.parents[1] / "schemas" / "workflow-decision.schema.json"
STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"


def _request_from_decision(decision: dict[str, Any]) -> dict[str, Any]:
    contract = decision["request_contract"]
    return {
        "profile": decision["profile_id"],
        "task_route": decision["task_route"],
        "execution_preference": contract["execution_preference"],
        "estimated_files": contract["estimated_files"],
        "concerns": contract["concerns"],
        "risk_flags": contract["risk_flags"],
        "user_requested_review": contract["user_requested_review"],
        "delivery_action": contract["delivery_action"],
    }


def _decision_binding(
    decision: dict[str, Any], config_path: str | Path | None = None
) -> dict[str, Any]:
    validate_file(decision, DECISION_SCHEMA, "workflow decision")
    expected_hash = sha256_json(
        {key: value for key, value in decision.items() if key != "decision_hash"}
    )
    if decision["decision_hash"] != expected_hash:
        raise ValueError("workflow decision hash does not match its content")
    if decision["state_mode"] == "off":
        raise ValueError("workflow decision has state_mode off")
    config = load_config(config_path)
    if decision["config_hash"] != sha256_json(config):
        raise ValueError("workflow decision was created from a different configuration")
    expected = resolve_workflow(_request_from_decision(decision), config)
    if decision != expected:
        raise ValueError("workflow decision does not match the current configuration policy")
    return {
        "profile_id": decision["profile_id"],
        "profile_hash": decision["profile_hash"],
        "workflow_decision_hash": decision["decision_hash"],
        "config_hash": decision["config_hash"],
        "task_route": decision["task_route"],
        "execution_depth": decision["execution_depth"],
        "request_contract": decision["request_contract"],
        "approval": decision["approval"],
        "delivery": decision["delivery"],
        "evidence_requirements": decision["evidence_requirements"],
        "subagent_plan": decision["subagent_plan"],
        "worktree": decision["worktree"],
        "required_skills": decision["required_skills"],
        "optional_skills": decision["optional_skills"],
        "stages": decision["stages"],
    }


def _legacy_binding(
    args: argparse.Namespace, config_path: str | Path | None = None
) -> dict[str, Any]:
    execution_depth = args.execution_depth
    if args.workflow_mode:
        execution_depth = "controlled" if args.workflow_mode == "high_risk" else "standard"
    task_route = args.task_route.strip()
    profile_id = args.profile_id.strip()
    if not task_route or not profile_id:
        raise ValueError("task_route and profile_id must be non-empty")
    if args.profile_hash or args.workflow_decision_hash:
        raise ValueError("legacy derived hashes are no longer accepted; resolve a decision instead")
    config = load_config(config_path)
    request = {
        "profile": profile_id,
        "task_route": task_route,
        "execution_preference": execution_depth,
        "estimated_files": 0,
        "concerns": 1,
        "risk_flags": args.risk,
        "user_requested_review": False,
        "delivery_action": "none",
    }
    return _decision_binding(resolve_workflow(request, config), config_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--decision", help="resolved workflow decision JSON")
    parser.add_argument("--task-route", default="general_change")
    parser.add_argument(
        "--execution-depth",
        choices=["focused", "standard", "controlled"],
        default="standard",
    )
    parser.add_argument(
        "--workflow-mode",
        choices=["standard", "high_risk"],
        help="legacy v2.1 alias",
    )
    parser.add_argument("--profile-id", default="personal")
    parser.add_argument("--profile-hash")
    parser.add_argument("--workflow-decision-hash")
    parser.add_argument("--project-id")
    parser.add_argument("--config")
    parser.add_argument("--risk", action="append", default=[])
    args = parser.parse_args()
    try:
        binding = (
            _decision_binding(read_json(args.decision), args.config)
            if args.decision
            else _legacy_binding(args, args.config)
        )
        root = runtime_root(args.project_root)
        state_path = root / "state.json"
        project_id = (args.project_id or Path(args.project_root).resolve().name).strip()
        if not project_id:
            raise ValueError("project_id must be non-empty")

        if state_path.exists():
            state = read_json(state_path)
            validate_file(state, STATE_SCHEMA, "state")
            validate_runtime(root, state)
            if state["project_id"] != project_id:
                raise ValueError("existing runtime belongs to another project_id")
            ensure_runtime_settings(args.project_root, args.config)
            if state["workflow_decision_hash"] == binding["workflow_decision_hash"]:
                try:
                    render_checklist(args.project_root)
                except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                    print(f"CHECKLIST_WARNING: {exc}", file=sys.stderr)
                print("RUNTIME_EXISTS")
                return 0
            if state["active_task_id"] is not None:
                raise ValueError(
                    "active task is bound to another workflow decision; finish or cancel it before rebinding"
                )
            if state.get("worktree_identity") is not None and binding["task_route"] not in {
                "review",
                "delivery",
            }:
                raise ValueError(
                    "worktree is still bound; reconcile or explicitly clean it before rebinding"
                )
            state.update(binding)
            if binding["task_route"] in {"review", "delivery"}:
                state["worktree_identity"] = None
            state["schema_version"] = 8
            state["revision"] = int(state["revision"]) + 1
            state["updated_at"] = utc_now()
            write_json_atomic(state_path, state)
            try:
                render_checklist(args.project_root)
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                print(f"CHECKLIST_WARNING: {exc}", file=sys.stderr)
            append_event(
                args.project_root,
                "RUNTIME_REBOUND",
                {
                    "project_id": project_id,
                    "task_route": state["task_route"],
                    "execution_depth": state["execution_depth"],
                    "workflow_decision_hash": state["workflow_decision_hash"],
                },
            )
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0

        state = {
            "schema_version": 8,
            "project_id": project_id,
            "revision": 1,
            **binding,
            "status": "IDLE",
            "active_task_id": None,
            "worktree_identity": None,
            "tasks": {},
            "updated_at": utc_now(),
        }
        validate_file(state, STATE_SCHEMA, "state")
        write_json_atomic(state_path, state)
        (root / "tasks").mkdir(parents=True, exist_ok=True)
        (root / "artifacts").mkdir(parents=True, exist_ok=True)
        ensure_runtime_settings(args.project_root, args.config)
        try:
            render_checklist(args.project_root)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            print(f"CHECKLIST_WARNING: {exc}", file=sys.stderr)
        append_event(
            args.project_root,
            "RUNTIME_INITIALIZED",
            {
                "project_id": project_id,
                "task_route": state["task_route"],
                "execution_depth": state["execution_depth"],
                "workflow_decision_hash": state["workflow_decision_hash"],
            },
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"RUNTIME_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
