"""Create the canonical, approval-bound contract for one review batch."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from append_event import append_event_for_root
from authorization import authorize, require_persisted_approval
from operation_ledger import read_operation_ledger
from resolve_rubric import resolve_rubric
from review_contract import contract_from_rubric, validate_contract
from runtime_utils import (
    RuntimeLockedError,
    RuntimeNotInitializedError,
    append_jsonl,
    read_object,
    read_payload,
    runtime_lock,
    utc_now,
    validate_identifier,
    write_text_atomic,
)
from validate_payload import validate
from validate_planning import validate_manifest
from write_artifact import write_validated


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/batch-contract.schema.json"
TASK_STATE_SCHEMA = ROOT / "schemas/task-state.schema.json"
OPERATION_SCHEMA = ROOT / "schemas/operation.schema.json"
PLAN_APPROVAL_ACTIONS = {"MASTER_PLAN", "MASTER_PLAN_APPROVE", "PLAN_APPROVE"}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def artifact_hash(value: dict[str, Any], field: str) -> str:
    copy = dict(value)
    copy.pop(field, None)
    return hashlib.sha256(canonical(copy).encode("utf-8")).hexdigest()


def _validate_revision(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _plan_hash(approved_plan: dict[str, Any]) -> str:
    return artifact_hash(approved_plan, "plan_hash")


def _resolve_documents(approved_plan: dict[str, Any], batch_id: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    master = approved_plan["master_plan"]
    batches = approved_plan.get("batches") or []
    sub_plans = approved_plan.get("sub_plans") or []
    tasks = approved_plan.get("tasks") or []
    batch_matches = [item for item in batches if item.get("batch_id") == batch_id]
    if len(batch_matches) != 1:
        raise ValueError(f"batch {batch_id} must resolve to exactly one planning batch")
    batch = batch_matches[0]
    sub_matches = [item for item in sub_plans if item.get("sub_plan_id") == batch.get("sub_plan_id")]
    if len(sub_matches) != 1:
        raise ValueError(f"batch {batch_id} must resolve to exactly one sub-plan")
    sub_plan = sub_matches[0]
    sub_plan_batch_ids = sub_plan.get("batches")
    if not isinstance(sub_plan_batch_ids, list) or any(not isinstance(item, str) or not item.strip() for item in sub_plan_batch_ids):
        raise ValueError("sub-plan batches must be a list of non-empty IDs")
    if len(sub_plan_batch_ids) != len(set(sub_plan_batch_ids)):
        raise ValueError("sub-plan contains duplicate batch IDs")
    sub_plan_id = sub_plan.get("sub_plan_id")
    planning_batches_by_id = {
        item.get("batch_id"): item
        for item in batches
        if isinstance(item.get("batch_id"), str)
    }
    for listed_batch_id in sub_plan_batch_ids:
        listed_batch = planning_batches_by_id.get(listed_batch_id)
        if listed_batch is None:
            raise ValueError(f"sub-plan references missing batch: {listed_batch_id}")
        if listed_batch.get("sub_plan_id") != sub_plan_id:
            raise ValueError(f"batch {listed_batch_id} is assigned to a different sub-plan")
    referencing_batch_ids = [
        item.get("batch_id")
        for item in batches
        if item.get("sub_plan_id") == sub_plan_id
    ]
    if len(referencing_batch_ids) != len(set(referencing_batch_ids)) or set(referencing_batch_ids) != set(sub_plan_batch_ids):
        raise ValueError("sub-plan and planning batch membership is not exact in both directions")
    selected_ids = batch.get("tasks")
    if not isinstance(selected_ids, list) or not selected_ids or any(not isinstance(item, str) for item in selected_ids):
        raise ValueError("selected batch tasks must be a non-empty array of IDs")
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("selected batch contains duplicate task IDs")
    task_matches = {item.get("task_id"): item for item in tasks if isinstance(item.get("task_id"), str)}
    if len(task_matches) != len(tasks):
        raise ValueError("planning tasks must have unique task IDs")
    selected_set = set(selected_ids)
    reverse_set = {item["task_id"] for item in tasks if item.get("batch_id") == batch_id}
    if selected_set != reverse_set:
        raise ValueError("batch task membership is not exact in both directions")
    for task_id in selected_ids:
        task = task_matches.get(task_id)
        if task is None:
            raise ValueError(f"batch {batch_id} references missing task: {task_id}")
        if task.get("batch_id") != batch_id:
            raise ValueError(f"task {task_id} is assigned to a different batch")
    if batch.get("sub_plan_id") != sub_plan.get("sub_plan_id"):
        raise ValueError("batch-to-sub-plan membership is invalid")
    if sub_plan.get("master_plan_id") != master.get("plan_id"):
        raise ValueError("sub-plan does not belong to the master plan")
    return batch, sub_plan, [task_matches[task_id] for task_id in selected_ids]


def _approval(root: Path, plan_id: str, plan_revision: int, plan_hash: str, actor: str) -> dict[str, Any]:
    approval_path = root / "approvals" / f"MASTER_PLAN-{plan_id}.json"
    approval = read_object(approval_path)
    require_persisted_approval(root, approval, target_type="MASTER_PLAN", target_id=plan_id)
    if approval.get("action") not in PLAN_APPROVAL_ACTIONS:
        raise ValueError("approval action is not a typed master-plan approval")
    if approval.get("actor_type") != "primary_agent" or approval.get("actor_id") != "primary-agent":
        raise ValueError("master-plan approval must be issued by primary-agent")
    if actor != approval.get("actor_id") or actor != "primary-agent":
        raise ValueError("batch contract writer actor must be primary-agent")
    authorize(
        approval["action"],
        {
            "target_type": "MASTER_PLAN",
            "target_id": plan_id,
            "revision": plan_revision,
            "target_hash": plan_hash,
        },
        approval,
        actor={"actor_type": "primary_agent", "actor_id": actor},
    )
    return approval


def _task_contract(task: dict[str, Any], state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    revision = _validate_revision(state.get("revision"), f"task {task['task_id']} revision")
    contract = state.get("review_contract")
    if not isinstance(contract, dict):
        raise ValueError(f"task {task['task_id']} requires a canonical review_contract")
    validate_contract(contract, review_type="task")
    planned = task.get("review_contract")
    if planned is not None and planned != contract:
        raise ValueError(f"task {task['task_id']} review_contract differs from planning")
    return contract, {"task_revision": revision, "review_contract_hash": hashlib.sha256(canonical(contract).encode("utf-8")).hexdigest(), "rubric_id": contract["rubric_id"], "rubric_version": contract["rubric_version"], "rubric_hash": contract["rubric_hash"]}


def _batch_contract(batch: dict[str, Any]) -> dict[str, Any]:
    explicit = batch.get("review_contract")
    if isinstance(explicit, dict):
        validate_contract(explicit, review_type="batch")
        return explicit
    profile = batch.get("review_profile")
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("batch review_profile is required when review_contract is absent")
    task_type = batch.get("review_task_type", batch.get("task_type", "standard"))
    if not isinstance(task_type, str) or not task_type.strip():
        raise ValueError("batch review task type is invalid")
    rubric = resolve_rubric(profile, task_type, batch.get("risk_flags", {}), review_type="batch")
    return contract_from_rubric(rubric)


def _append_operation(root: Path, batch_id: str, revision: int, plan_hash: str, contract_hash: str, actor: str) -> None:
    path = root / "work" / batch_id / "operations.jsonl"
    records = read_operation_ledger(path, batch_id, OPERATION_SCHEMA)
    operation_id = f"OP-{batch_id}-CREATE-BATCH-CONTRACT-{revision}"
    if any(item.get("operation_id") == operation_id for item in records):
        raise ValueError(f"operation already exists: {operation_id}")
    record = {
        "operation_id": operation_id,
        "task_id": batch_id,
        "type": "OTHER",
        "status": "COMPLETED",
        "command": "CREATE_BATCH_CONTRACT",
        "input_hash": plan_hash,
        "output_hash": contract_hash,
        "result_summary": "canonical batch contract created",
        "recorded_at": utc_now(),
        "revision": 1,
        "actor": actor,
        "phase": "COMMIT",
        "transaction_id": operation_id,
        "idempotency_key": operation_id,
    }
    errors = validate(record, read_object(OPERATION_SCHEMA), base_path=OPERATION_SCHEMA.parent)
    if errors:
        raise ValueError("invalid batch contract operation: " + "; ".join(errors))
    append_jsonl(path, record)
    append_event_for_root(root, {"type": "OPERATION_RECORDED", "actor": actor, "data": {"operation_id": operation_id, "status": "COMPLETED", "type": "CREATE_BATCH_CONTRACT", "contract_hash": contract_hash}})


def _snapshot_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _restore_text(path: Path, content: str | None) -> None:
    if content is None:
        if path.is_file():
            path.unlink()
        return
    write_text_atomic(path, content)


def create_batch_contract(
    project_root: str | Path,
    approved_plan: dict[str, object],
    *,
    plan_id: str,
    plan_revision: int,
    batch_id: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    """Validate, pin, persist, and journal one canonical batch contract."""

    if not isinstance(approved_plan, dict):
        raise ValueError("approved_plan must be an object")
    validate_identifier(plan_id, "plan_id")
    validate_identifier(batch_id, "batch_id")
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor must be a non-empty string")
    plan_revision = _validate_revision(plan_revision, "plan_revision")
    if expected_revision is None:
        raise ValueError("expected_revision is required for batch contract creation")
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    planning_errors = validate_manifest(approved_plan)
    if planning_errors:
        raise ValueError("planning bundle is invalid: " + "; ".join(planning_errors))
    master = approved_plan["master_plan"]
    if master.get("plan_id") != plan_id:
        raise ValueError("supplied plan_id does not match master_plan")
    if "revision" not in master:
        raise ValueError("master_plan.revision is required")
    master_revision = _validate_revision(master["revision"], "master_plan.revision")
    if master_revision != plan_revision:
        raise ValueError("supplied plan_revision does not match master_plan")
    for field in ("revision", "plan_revision"):
        if field in approved_plan and approved_plan[field] != plan_revision:
            raise ValueError("supplied plan_revision does not match planning bundle")
        if field in master and master[field] != plan_revision:
            raise ValueError("supplied plan_revision does not match master_plan")
    plan_hash = _plan_hash(approved_plan)
    batch, _sub_plan, tasks = _resolve_documents(approved_plan, batch_id)

    with runtime_lock(project_root) as root:
        approval = _approval(root, plan_id, plan_revision, plan_hash, actor)
        pins: list[dict[str, Any]] = []
        for task in tasks:
            state_path = root / "work" / task["task_id"] / "task-state.json"
            if not state_path.is_file():
                raise ValueError(f"current task state is missing: {task['task_id']}")
            state = read_object(state_path)
            state_errors = validate(state, read_object(TASK_STATE_SCHEMA), base_path=TASK_STATE_SCHEMA.parent)
            if state_errors:
                raise ValueError(f"task state is invalid for {task['task_id']}: " + "; ".join(state_errors))
            if state.get("task_id") != task["task_id"] or state.get("batch_id") != batch_id:
                raise ValueError(f"task state identity does not match planning: {task['task_id']}")
            _contract, pin = _task_contract(task, state)
            pins.append({"task_id": task["task_id"], **pin})
        if len(pins) != len({pin["task_id"] for pin in pins}):
            raise ValueError("canonical batch contract contains duplicate task IDs")
        batch_review_contract = _batch_contract(batch)
        existing_path = root / "work" / batch_id / "batch-contract.json"
        existing: dict[str, Any] | None = read_object(existing_path) if existing_path.is_file() else None
        current_revision = 0 if existing is None else _validate_revision(existing.get("revision"), "existing contract revision")
        if existing is not None and expected_revision is None:
            raise ValueError("replacing an existing batch contract requires expected_revision")
        if expected_revision is not None and expected_revision != current_revision:
            raise ValueError(f"stale revision: expected {expected_revision}, current {current_revision}")
        revision = current_revision + 1
        contract: dict[str, Any] = {
            "schema_version": 1,
            "contract_id": f"BATCH-CONTRACT-{batch_id}-R{plan_revision}",
            "plan_id": plan_id,
            "plan_revision": plan_revision,
            "plan_hash": plan_hash,
            "plan_approval_id": approval["approval_id"],
            "batch_id": batch_id,
            "batch_revision": _validate_revision(batch.get("revision", batch.get("batch_revision", 1)), "batch_revision"),
            "tasks": pins,
            "review_contract": batch_review_contract,
            "rubric_id": batch_review_contract["rubric_id"],
            "rubric_version": batch_review_contract["rubric_version"],
            "rubric_hash": batch_review_contract["rubric_hash"],
            "revision": revision,
            "previous_revision": current_revision if existing is not None else None,
            "created_at": utc_now(),
        }
        contract["contract_hash"] = artifact_hash(contract, "contract_hash")
        errors = validate(contract, read_object(SCHEMA), base_path=SCHEMA.parent)
        if errors:
            raise ValueError("invalid batch contract: " + "; ".join(errors))
        operation_path = root / "work" / batch_id / "operations.jsonl"
        read_operation_ledger(operation_path, batch_id, OPERATION_SCHEMA)
        artifact_path = root / "work" / batch_id / "batch-contract.json"
        event_path = root / "runtime" / "events.jsonl"
        state_path = root / "runtime" / "state.json"
        snapshots = {
            artifact_path: _snapshot_text(artifact_path),
            operation_path: _snapshot_text(operation_path),
            event_path: _snapshot_text(event_path),
            state_path: _snapshot_text(state_path),
        }
        try:
            write_validated(project_root, f"work/{batch_id}/batch-contract.json", contract, SCHEMA)
            append_event_for_root(root, {"type": "BATCH_CONTRACT_CREATED", "actor": actor, "data": {"contract_id": contract["contract_id"], "batch_id": batch_id, "revision": revision, "contract_hash": contract["contract_hash"]}})
            _append_operation(root, batch_id, revision, plan_hash, contract["contract_hash"], actor)
        except Exception:
            for path, content in snapshots.items():
                _restore_text(path, content)
            raise
    return contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--plan-revision", required=True, type=int)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--expected-revision", required=True, type=int)
    parser.add_argument("--actor", required=True)
    args = parser.parse_args()
    try:
        result = create_batch_contract(args.project_root, read_payload(args.plan), plan_id=args.plan_id, plan_revision=args.plan_revision, batch_id=args.batch_id, actor=args.actor, expected_revision=args.expected_revision)
    except RuntimeNotInitializedError as exc:
        print(f"CREATE_BATCH_CONTRACT_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"CREATE_BATCH_CONTRACT_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"CREATE_BATCH_CONTRACT_WRITTEN: {result['contract_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
