"""Record a delivery decision only after required current evidence passes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from runtime_utils import (  # noqa: E402
    append_event,
    read_json,
    refresh_checklist,
    require_scope_coverage,
    revalidate_plan_binding,
    require_task_index_consistent,
    runtime_root,
    safe_child,
    sha256_json,
    task_artifact_path,
    task_state_path,
    validate_task_id,
    verify_workspace_snapshot,
    write_json_atomic,
)

STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"
TASK_SCHEMA = HERE.parents[1] / "schemas" / "task-state.schema.json"
VERIFICATION_SCHEMA = HERE.parents[1] / "schemas" / "verification-evidence.schema.json"
CLAIM_SCHEMA = HERE.parents[1] / "schemas" / "completion-claim.schema.json"
COMPLETION_GATE_SCHEMA = HERE.parents[1] / "schemas" / "completion-gate.schema.json"
REVIEW_SCHEMA = HERE.parents[1] / "schemas" / "review.schema.json"
BATCH_REVIEW_SCHEMA = HERE.parents[1] / "schemas" / "batch-review.schema.json"
DELIVERY_SCHEMA = HERE.parents[1] / "schemas" / "delivery-decision.schema.json"
INPUT_FIELDS = {
    "schema_version",
    "task_ids",
    "action",
    "outcome",
    "summary",
    "approval_reference",
    "cleanup",
}


def _load_task(root: Path, state: dict[str, Any], task_id: str) -> dict[str, Any]:
    path = task_state_path(root, task_id)
    if not path.is_file():
        raise ValueError(f"task state is missing: {task_id}")
    task = read_json(path)
    validate_file(task, TASK_SCHEMA, f"task {task_id}")
    if task["task_id"] != task_id:
        raise ValueError(f"task id mismatch: {task_id}")
    if task_id not in state["tasks"]:
        raise ValueError(f"task is missing from runtime index: {task_id}")
    summary = state["tasks"][task_id]
    for field in ("status", "status_revision", "work_revision", "summary"):
        if task[field] != summary.get(field):
            raise ValueError(f"runtime task summary mismatch for {task_id}: {field}")
    return task


def _select_tasks(root: Path, state: dict[str, Any], supplied_ids: object) -> list[dict[str, Any]]:
    if supplied_ids is not None:
        if not isinstance(supplied_ids, list) or not supplied_ids:
            raise ValueError("task_ids must be a non-empty array when supplied")
        task_ids = [validate_task_id(item) for item in supplied_ids]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task_ids must be unique")
    else:
        task_ids = []
        for task_id in sorted(state.get("tasks", {})):
            task = _load_task(root, state, validate_task_id(task_id))
            if task["workflow_decision_hash"] == state["workflow_decision_hash"] and task["status"] != "CANCELLED":
                task_ids.append(task_id)
        if not task_ids:
            raise ValueError(
                "no tasks are bound to the current decision; supply task_ids for a standalone review or delivery route"
            )

    tasks = [_load_task(root, state, task_id) for task_id in sorted(task_ids)]
    cross_decision_allowed = state["task_route"] in {"review", "delivery"}
    if not cross_decision_allowed:
        mismatched = [
            task["task_id"]
            for task in tasks
            if task["workflow_decision_hash"] != state["workflow_decision_hash"]
        ]
        if mismatched:
            raise ValueError(
                "source-editing delivery may include only tasks bound to the current decision: "
                + ", ".join(mismatched)
            )
    incomplete = [
        task["task_id"] for task in tasks if task["status"] not in {"COMPLETED", "ACCEPTED"}
    ]
    if incomplete:
        raise ValueError("delivery requires completed or accepted tasks: " + ", ".join(incomplete))
    return tasks


def _require_acceptance_mapping(claim: dict[str, Any], verification: dict[str, Any], task_id: str) -> None:
    claim_ids = [str(item["id"]).strip() for item in claim["acceptance"]]
    check_ids = [str(item["name"]).strip() for item in verification["checks"]]
    if any(not item for item in claim_ids + check_ids):
        raise ValueError(f"acceptance and verification IDs must not be blank: {task_id}")
    if len(claim_ids) != len(set(claim_ids)) or len(check_ids) != len(set(check_ids)):
        raise ValueError(f"acceptance and verification IDs must be unique: {task_id}")
    if set(claim_ids) != set(check_ids):
        raise ValueError(f"completion claim no longer maps to current verification checks: {task_id}")
    if any(item["status"] != "PASS" or not item["evidence"].strip() for item in claim["acceptance"]):
        raise ValueError(f"completion claim contains non-passing acceptance evidence: {task_id}")
    if claim["verification_status"] != verification["status"]:
        raise ValueError(f"completion claim verification status is stale: {task_id}")


def _require_verification(project_root: str, root: Path, task: dict[str, Any]) -> None:
    task_id = task["task_id"]
    verification_path = task_artifact_path(root, task_id, "verification.json")
    claim_path = task_artifact_path(root, task_id, "completion-claim.json")
    gate_path = task_artifact_path(root, task_id, "completion-gate.json")
    if not verification_path.is_file():
        raise ValueError(f"verification artifact is missing: {task_id}")
    if not claim_path.is_file():
        raise ValueError(f"persisted completion claim is missing: {task_id}")
    if not gate_path.is_file():
        raise ValueError(f"passing completion gate is missing: {task_id}")

    verification = read_json(verification_path)
    validate_file(verification, VERIFICATION_SCHEMA, f"verification {task_id}")
    if verification["task_id"] != task_id:
        raise ValueError(f"verification is bound to another task: {task_id}")
    if verification["work_revision"] != task["work_revision"]:
        raise ValueError(f"verification is stale for task: {task_id}")
    if verification["workflow_decision_hash"] != task["workflow_decision_hash"]:
        raise ValueError(f"verification is bound to another decision: {task_id}")
    if verification["status"] != "PASS":
        raise ValueError(f"verification did not pass: {task_id}")
    verified_files = verify_workspace_snapshot(project_root, verification["workspace"], task_id)
    require_scope_coverage(project_root, task, verified_files)

    state = read_json(root / "state.json")
    plan_binding = state.get("plan_binding", {})
    if isinstance(plan_binding, dict) and plan_binding.get("required"):
        revalidate_plan_binding(project_root, plan_binding, expected_decision_hash=task["workflow_decision_hash"])
        if not plan_binding.get("bound"):
            raise ValueError(f"plan review gate is missing: {task_id}")
        if task.get("plan_task_id") not in plan_binding.get("plan_task_ids", []):
            raise ValueError(f"task plan_task_id is not bound: {task_id}")
        for artifact, label in ((verification, "verification"),):
            if artifact.get("plan_task_id") != task.get("plan_task_id"):
                raise ValueError(f"{label} plan_task_id is stale: {task_id}")
            if artifact.get("plan_bundle_hash") != task.get("plan_bundle_hash"):
                raise ValueError(f"{label} plan bundle hash is stale: {task_id}")
            if artifact.get("plan_review_hash") != task.get("plan_review_hash"):
                raise ValueError(f"{label} plan review hash is stale: {task_id}")
        if set(verification.get("acceptance_ids", [])) != set(plan_binding.get("acceptance_ids", [])):
            raise ValueError(f"verification acceptance IDs are stale: {task_id}")

    claim = read_json(claim_path)
    validate_file(claim, CLAIM_SCHEMA, f"completion claim {task_id}")
    if claim["task_id"] != task_id or claim["work_revision"] != task["work_revision"]:
        raise ValueError(f"completion claim is stale or mismatched: {task_id}")
    _require_acceptance_mapping(claim, verification, task_id)
    if isinstance(plan_binding, dict) and plan_binding.get("required"):
        for label, artifact in (("completion claim", claim),):
            if artifact.get("plan_task_id") != task.get("plan_task_id"):
                raise ValueError(f"{label} plan_task_id is stale: {task_id}")
            if artifact.get("plan_bundle_hash") != task.get("plan_bundle_hash"):
                raise ValueError(f"{label} plan bundle hash is stale: {task_id}")
            if artifact.get("plan_review_hash") != task.get("plan_review_hash"):
                raise ValueError(f"{label} plan review hash is stale: {task_id}")
        if set(claim.get("acceptance_ids", [])) != set(plan_binding.get("acceptance_ids", [])):
            raise ValueError(f"completion claim acceptance IDs are stale: {task_id}")

    gate = read_json(gate_path)
    validate_file(gate, COMPLETION_GATE_SCHEMA, f"completion gate {task_id}")
    if (
        gate["task_id"] != task_id
        or gate["work_revision"] != task["work_revision"]
        or gate["workflow_decision_hash"] != task["workflow_decision_hash"]
        or gate["status"] != "PASS"
        or gate["claim_hash"] != sha256_json(claim)
    ):
        raise ValueError(f"completion gate is stale or mismatched: {task_id}")
    if isinstance(plan_binding, dict) and plan_binding.get("required"):
        if (
            gate.get("plan_task_id") != task.get("plan_task_id")
            or gate.get("plan_bundle_hash") != task.get("plan_bundle_hash")
            or gate.get("plan_review_hash") != task.get("plan_review_hash")
            or set(gate.get("acceptance_ids", [])) != set(plan_binding.get("acceptance_ids", []))
        ):
            raise ValueError(f"completion gate plan binding is stale: {task_id}")


def _require_review(project_root: str, root: Path, task: dict[str, Any]) -> None:
    task_id = task["task_id"]
    path = task_artifact_path(root, task_id, "review.json")
    if not path.is_file():
        raise ValueError(f"required review artifact is missing: {task_id}")
    review = read_json(path)
    validate_file(review, REVIEW_SCHEMA, f"review {task_id}")
    if (
        review["task_id"] != task_id
        or review["work_revision"] != task["work_revision"]
        or review["workflow_decision_hash"] != task["workflow_decision_hash"]
    ):
        raise ValueError(f"review is stale or mismatched: {task_id}")
    if review["outcome"] != "PASS":
        raise ValueError(f"review did not pass: {task_id}")
    verified_files = verify_workspace_snapshot(project_root, review["workspace"], task_id)
    require_scope_coverage(project_root, task, verified_files)


def _require_worktree_cleanup(root: Path, task: dict[str, Any]) -> None:
    task_id = task["task_id"]
    if task.get("worktree_identity") is None:
        return
    path = task_artifact_path(root, task_id, "worktree-cleanup.json")
    if not path.is_file():
        raise ValueError(f"worktree cleanup decision is missing: {task_id}")
    cleanup = read_json(path)
    validate_file(cleanup, HERE.parents[1] / "schemas" / "worktree-cleanup.schema.json", f"worktree cleanup {task_id}")
    if cleanup["task_id"] != task_id:
        raise ValueError(f"worktree cleanup is bound to another task: {task_id}")
    if cleanup["worktree"] != task["worktree_identity"]:
        raise ValueError(f"worktree cleanup does not match the task identity: {task_id}")


def _task_bindings(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "task_id": task["task_id"],
            "work_revision": task["work_revision"],
            "workflow_decision_hash": task["workflow_decision_hash"],
        }
        for task in sorted(tasks, key=lambda item: item["task_id"])
    ]


def _require_batch_review(
    project_root: str, root: Path, state: dict[str, Any], tasks: list[dict[str, Any]]
) -> None:
    path = safe_child(root, "batch-review.json")
    if not path.is_file():
        raise ValueError("required batch-review artifact is missing")
    review = read_json(path)
    validate_file(review, BATCH_REVIEW_SCHEMA, "batch review")
    if review["workflow_decision_hash"] != state["workflow_decision_hash"]:
        raise ValueError("batch review is bound to another delivery decision")
    if review["outcome"] != "PASS":
        raise ValueError("batch review did not pass")
    expected = [
        {
            "task_id": item["task_id"],
            "work_revision": item["work_revision"],
            "task_workflow_decision_hash": item["workflow_decision_hash"],
        }
        for item in _task_bindings(tasks)
    ]
    actual = sorted(review["tasks"], key=lambda item: item["task_id"])
    if actual != expected:
        raise ValueError("batch review task bindings are stale or incomplete")
    verified_files = verify_workspace_snapshot(project_root, review["workspace"], tasks[0]["task_id"])
    for task in tasks:
        require_scope_coverage(project_root, task, verified_files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        supplied = read_json(args.input)
        unknown = sorted(set(supplied) - INPUT_FIELDS)
        if unknown:
            raise ValueError("caller must not supply derived delivery fields: " + ", ".join(unknown))
        if supplied.get("schema_version") not in {3, 4}:
            raise ValueError("delivery input schema_version must be 3 or 4")
        root = runtime_root(args.project_root)
        state = read_json(root / "state.json")
        validate_file(state, STATE_SCHEMA, "state")
        require_task_index_consistent(root, state)
        if state["status"] != "IDLE" or state["active_task_id"] is not None:
            raise ValueError("delivery is blocked while a task is active")
        expected = state["delivery"]
        if expected["action"] == "none":
            raise ValueError("current workflow decision has no delivery action")

        action = str(supplied.get("action", "")).strip()
        outcome = str(supplied.get("outcome", "")).strip()
        cleanup = str(supplied.get("cleanup", "")).strip()
        summary = str(supplied.get("summary", "")).strip()
        approval_reference = supplied.get("approval_reference")
        if approval_reference is not None:
            approval_reference = str(approval_reference).strip() or None
        if action != expected["action"]:
            raise ValueError(f"delivery action conflicts with workflow decision: expected {expected['action']}")
        if outcome != expected["outcome"]:
            raise ValueError(f"delivery outcome conflicts with workflow decision: expected {expected['outcome']}")
        if cleanup != expected["cleanup"]:
            raise ValueError(f"cleanup conflicts with workflow decision: expected {expected['cleanup']}")
        if not summary:
            raise ValueError("delivery summary must be non-empty")

        tasks = _select_tasks(root, state, supplied.get("task_ids"))
        requirements = state["evidence_requirements"]
        for task in tasks:
            if requirements["verification"]:
                _require_verification(args.project_root, root, task)
            if requirements["review"]:
                _require_review(args.project_root, root, task)
            _require_worktree_cleanup(root, task)
        if requirements["batch_review"]:
            _require_batch_review(args.project_root, root, state, tasks)

        worktree_contract = state.get("worktree", {})
        worktree_approval_required = bool(
            isinstance(worktree_contract, dict)
            and (
                worktree_contract.get("delivery_approval_required")
                or worktree_contract.get("cleanup_approval_required")
            )
        )
        approval_required = bool(state["approval"]["required"] or worktree_approval_required)
        approval_kind = "user" if worktree_approval_required else state["approval"]["kind"]
        if approval_required and not approval_reference:
            raise ValueError("approval_reference is required by the workflow decision")

        decision = {
            "schema_version": 4,
            "workflow_decision_hash": state["workflow_decision_hash"],
            "task_bindings": _task_bindings(tasks),
            "evidence_requirements": requirements,
            "action": action,
            "outcome": outcome,
            "summary": summary,
            "approval_required": approval_required,
            "approval_kind": approval_kind,
            "approval_reference": approval_reference,
            "cleanup": cleanup,
        }
        validate_file(decision, DELIVERY_SCHEMA, "delivery decision")
        write_json_atomic(safe_child(root, "delivery-decision.json"), decision)
        append_event(
            args.project_root,
            "DELIVERY_DECISION_WRITTEN",
            {
                "action": decision["action"],
                "outcome": decision["outcome"],
                "workflow_decision_hash": decision["workflow_decision_hash"],
                "task_ids": [item["task_id"] for item in decision["task_bindings"]],
                "approval_required": decision["approval_required"],
            },
        )
        refresh_checklist(args.project_root)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"DELIVERY_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
