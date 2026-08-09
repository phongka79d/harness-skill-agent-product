"""Initialize or safely rebind minimal runtime state to a workflow decision."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from load_config import load_config  # noqa: E402
from load_runtime_settings import ensure_runtime_settings  # noqa: E402
from plan_docs import install_plan_docs_atomic, remove_installed_plan_docs  # noqa: E402
from resolve_workflow import resolve_workflow  # noqa: E402
from render_checklist import render_checklist  # noqa: E402
from schema_validation import validate_file  # noqa: E402
from validate_state import validate_runtime  # noqa: E402
from runtime_utils import (  # noqa: E402
    append_event,
    read_json,
    restore_bytes_atomic,
    runtime_root,
    sha256_json,
    utc_now,
    validate_plan_binding_documents,
    write_json_atomic,
)

DECISION_SCHEMA = HERE.parents[1] / "schemas" / "workflow-decision.schema.json"
STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"


def _request_from_decision(decision: dict[str, Any]) -> dict[str, Any]:
    contract = decision["request_contract"]
    result = {
        "profile": decision["profile_id"],
        "task_route": decision["task_route"],
        "execution_preference": contract["execution_preference"],
        "estimated_files": contract["estimated_files"],
        "concerns": contract["concerns"],
        "risk_flags": contract["risk_flags"],
        "user_requested_review": contract["user_requested_review"],
        "delivery_action": contract["delivery_action"],
    }
    for key in ("plan_bundle_hash", "plan_review_hash", "plan_task_ids"):
        if key in contract:
            result[key] = contract[key]
    return result


def _empty_plan_binding(decision: dict[str, Any]) -> dict[str, Any]:
    gate = decision.get(
        "plan_gate",
        {"required": False, "schema_version": 5, "plan_bundle_hash": None, "plan_review_hash": None, "plan_task_ids": []},
    )
    return {
        "required": bool(gate.get("required", False)),
        "bound": False,
        "schema_version": 5,
        "plan_bundle_hash": gate.get("plan_bundle_hash"),
        "plan_review_hash": gate.get("plan_review_hash"),
        "plan_task_ids": list(gate.get("plan_task_ids", [])),
        "acceptance_ids": [],
        "plan_path": None,
        "plan_docs_hash": None,
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
    if decision["execution_depth"] == "controlled":
        plan_gate = decision.get("plan_gate")
        if not isinstance(plan_gate, dict) or plan_gate.get("required") is not True:
            raise ValueError("controlled workflow decision requires an affirmative plan_gate")
    config = load_config(config_path)
    if decision["config_hash"] != sha256_json(config):
        raise ValueError("workflow decision was created from a different configuration")
    expected = resolve_workflow(_request_from_decision(decision), config)
    if decision != expected:
        legacy_expected = copy.deepcopy(expected)
        if "plan_gate" not in decision:
            legacy_expected.pop("plan_gate", None)
            for key in ("plan_bundle_hash", "plan_review_hash", "plan_task_ids"):
                legacy_expected["request_contract"].pop(key, None)
        if {
            key: value for key, value in decision.items() if key != "decision_hash"
        } == {
            key: value for key, value in legacy_expected.items() if key != "decision_hash"
        }:
            expected = decision
        else:
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
        "plan_binding": _empty_plan_binding(decision),
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


def _persist_json_transaction(
    writes: list[tuple[Path, dict[str, Any]]],
    *,
    verify: Any | None = None,
) -> None:
    """Commit related runtime JSON artifacts or restore every prior byte value."""
    snapshots = [
        (path, path.read_bytes() if path.exists() else None)
        for path, _ in writes
    ]
    try:
        for path, value in writes:
            write_json_atomic(path, value)
        if verify is not None:
            verify()
    except Exception:
        rollback_errors: list[str] = []
        for path, previous in reversed(snapshots):
            try:
                restore_bytes_atomic(path, previous)
            except Exception as rollback_error:
                rollback_errors.append(f"{path.name}: {rollback_error}")
        if rollback_errors:
            raise ValueError(
                "runtime update failed and rollback failed: " + "; ".join(rollback_errors)
            )
        raise

def _persist_runtime_transaction(
    root: Path,
    writes: list[tuple[Path, dict[str, Any]]],
    *,
    plan_docs_source: str | None,
    plan_binding: dict[str, Any],
    verify: Any | None = None,
) -> None:
    installed_path: str | None = None
    installed_new = False
    if plan_docs_source is not None:
        expected_hash = plan_binding.get("plan_docs_hash")
        expected_path = plan_binding.get("plan_path")
        if not isinstance(expected_hash, str) or not isinstance(expected_path, str):
            raise ValueError("--plan-docs requires a hash-bound plan manifest and review")
        target, installed_new = install_plan_docs_atomic(
            root,
            plan_docs_source,
            expected_hash=expected_hash,
        )
        installed_path = f".phongka/plan/{target.name}"
        if installed_path != expected_path:
            if installed_new:
                remove_installed_plan_docs(root, installed_path)
            raise ValueError("--plan-docs directory does not match the reviewed plan_path")
    try:
        _persist_json_transaction(writes, verify=verify)
    except Exception:
        if installed_new and installed_path is not None:
            remove_installed_plan_docs(root, installed_path)
        raise






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
    parser.add_argument("--plan-manifest")
    parser.add_argument("--plan-review")
    parser.add_argument(
        "--plan-docs",
        help="planner-authored plan document tree (<date>-<feature> staging dir) to install",
    )
    parser.add_argument("--risk", action="append", default=[])
    args = parser.parse_args()
    try:
        binding = (
            _decision_binding(read_json(args.decision), args.config)
            if args.decision
            else _legacy_binding(args, args.config)
        )
        if bool(args.plan_manifest) != bool(args.plan_review):
            raise ValueError("--plan-manifest and --plan-review must be supplied together")
        if args.plan_docs and not args.plan_manifest:
            raise ValueError("--plan-docs requires --plan-manifest and --plan-review")
        if binding["execution_depth"] == "controlled" and (
            not args.plan_manifest or not args.plan_docs
        ):
            raise ValueError(
                "controlled runtime requires a v5 plan manifest, PASS plan review, and reviewed plan docs"
            )
        plan_documents: tuple[dict[str, Any], dict[str, Any]] | None = None
        if args.plan_manifest and args.plan_review:
            manifest = read_json(args.plan_manifest)
            review = read_json(args.plan_review)
            binding["plan_binding"] = validate_plan_binding_documents(
                manifest,
                review,
                expected_decision_hash=binding["workflow_decision_hash"],
                require_v5=binding["execution_depth"] == "controlled",
            )
            plan_documents = (manifest, review)
        root = runtime_root(args.project_root)
        plan_writes: list[tuple[Path, dict[str, Any]]] = []
        if plan_documents is not None:
            plan_dir = root / "plan"
            binding["plan_binding"]["manifest_path"] = ".phongka/plan/manifest.json"
            binding["plan_binding"]["review_path"] = ".phongka/plan/review.json"
            plan_writes = [
                (plan_dir / "manifest.json", plan_documents[0]),
                (plan_dir / "review.json", plan_documents[1]),
            ]
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
            if state["workflow_decision_hash"] == binding["workflow_decision_hash"]:
                if plan_documents is not None:
                    if state.get("plan_binding") == binding["plan_binding"]:
                        _persist_runtime_transaction(
                            root,
                            [],
                            plan_docs_source=args.plan_docs,
                            plan_binding=state["plan_binding"],
                            verify=lambda: validate_runtime(root, state),
                        )
                    else:
                        updated_state = copy.deepcopy(state)
                        updated_state["plan_binding"] = binding["plan_binding"]
                        updated_state["revision"] = int(updated_state["revision"]) + 1
                        updated_state["updated_at"] = utc_now()
                        validate_file(updated_state, STATE_SCHEMA, "state")
                        _persist_runtime_transaction(
                            root,
                            [*plan_writes, (state_path, updated_state)],
                            plan_docs_source=args.plan_docs,
                            plan_binding=updated_state["plan_binding"],
                            verify=lambda: validate_runtime(root, updated_state),
                        )
                        state = updated_state
                        append_event(
                            args.project_root,
                            "PLAN_BOUND",
                            {
                                "workflow_decision_hash": state["workflow_decision_hash"],
                                "plan_bundle_hash": state["plan_binding"]["plan_bundle_hash"],
                                "plan_review_hash": state["plan_binding"]["plan_review_hash"],
                                "plan_path": state["plan_binding"].get("plan_path"),
                            },
                        )
                ensure_runtime_settings(args.project_root, args.config)
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
            updated_state = copy.deepcopy(state)
            updated_state.update(binding)
            if binding["task_route"] in {"review", "delivery"}:
                updated_state["worktree_identity"] = None
            updated_state["schema_version"] = 8
            updated_state["revision"] = int(updated_state["revision"]) + 1
            updated_state["updated_at"] = utc_now()
            validate_file(updated_state, STATE_SCHEMA, "state")
            _persist_runtime_transaction(
                root,
                [*plan_writes, (state_path, updated_state)],
                plan_docs_source=args.plan_docs,
                plan_binding=updated_state["plan_binding"],
                verify=lambda: validate_runtime(root, updated_state),
            )
            state = updated_state
            ensure_runtime_settings(args.project_root, args.config)
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
            "plan_binding": binding["plan_binding"],
            "tasks": {},
            "updated_at": utc_now(),
        }
        validate_file(state, STATE_SCHEMA, "state")
        _persist_runtime_transaction(
            root,
            [*plan_writes, (state_path, state)],
            plan_docs_source=args.plan_docs,
            plan_binding=state["plan_binding"],
            verify=lambda: validate_runtime(root, state),
        )
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
