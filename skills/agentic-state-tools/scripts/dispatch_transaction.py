"""Durably persist one validated dispatch under the runtime lock."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from append_event import append_event_for_root
from operation_ledger import read_operation_ledger
from render_checklist import render_checklist_for_root
from worktree_manager import validate_canonical_isolation_proof, validate_isolation_proof
from runtime_utils import (
    RuntimeNotInitializedError,
    STATUS_TO_EVENT_TYPE,
    append_jsonl,
    lease_expiry,
    parse_timestamp,
    read_object,
    runtime_lock,
    task_dependencies,
    task_write_scopes,
    utc_now,
    write_json_atomic,
)
from task_state_contract import EXECUTION_IDENTITY_FIELDS, merge_task_state, validate_execution_identity
from validate_payload import validate
from write_artifact import write_validated
from review_contract import validate_contract


ROOT = Path(__file__).resolve().parents[1]
QUEUE_SCHEMA = ROOT / "schemas/queue.schema.json"
GRAPH_SCHEMA = ROOT / "schemas/graph.schema.json"
LEASE_SCHEMA = ROOT / "schemas/lease.schema.json"
TASK_STATE_SCHEMA = ROOT / "schemas/task-state.schema.json"
OPERATION_SCHEMA = ROOT / "schemas/operation.schema.json"
ASYNC_PROOF_FIELDS = (
    "worktree_path",
    "branch_name",
    "base_commit",
    "plan_revision",
    "write_scope_hash",
    "active_conflicts_checked_at",
    "isolation_status",
)
ASYNC_BINDING_FIELDS = (*ASYNC_PROOF_FIELDS, "isolation_proof")


def _require_async_proof(task_id: str, dispatch: dict[str, Any], task: dict[str, Any] | None = None) -> dict[str, Any]:
    proof = dispatch.get("isolation_proof")
    if not validate_isolation_proof({"task_id": task_id}, proof) or not validate_canonical_isolation_proof(
        {"task_id": task_id}, proof
    ):
        raise ValueError("async dispatch requires a verified canonical isolation proof")
    assert isinstance(proof, dict)
    for field in ("run_id", *ASYNC_PROOF_FIELDS):
        if dispatch.get(field) is not None and dispatch.get(field) != proof.get(field):
            raise ValueError(f"async dispatch {field} does not match isolation proof")
    if task is not None:
        task_identity = {"task_id": task_id}
        for field in ("run_id", *ASYNC_PROOF_FIELDS):
            if task.get(field) is not None:
                task_identity[field] = task[field]
        if not validate_canonical_isolation_proof(task_identity, proof):
            raise ValueError("async dispatch isolation proof does not match task identity")
    return copy.deepcopy(proof)


def _async_binding_metadata(proof: dict[str, Any], dispatch: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    metadata = {field: copy.deepcopy(proof[field]) for field in ASYNC_PROOF_FIELDS}
    metadata["isolation_proof"] = copy.deepcopy(proof)
    input_hashes = dispatch.get("input_artifact_hashes", task.get("input_artifact_hashes"))
    if input_hashes is not None:
        metadata["input_artifact_hashes"] = copy.deepcopy(input_hashes)
    return metadata


def _validate_async_record(record: dict[str, Any], expected: dict[str, Any]) -> None:
    for field in ("task_id", "run_id", "attempt_id", "dispatch_id", *ASYNC_BINDING_FIELDS):
        if record.get(field) != expected.get(field):
            raise ValueError(f"async dispatch {field} does not match persisted identity")


def _typed_dependency_edge(source: str, target: str, expected: dict[str, Any]) -> dict[str, Any]:
    edge = {
        "from": source,
        "to": target,
        "kind": "DEPENDENCY",
        "edge_id": f"EDGE-{source}-{target}-DEPENDENCY",
        **{field: copy.deepcopy(expected[field]) for field in (*ASYNC_PROOF_FIELDS, "run_id", "attempt_id", "dispatch_id", "isolation_proof")},
    }
    edge["edge_hash"] = hashlib.sha256(json.dumps(edge, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return edge


def _validated_write(path: Path, value: dict[str, Any], schema_path: Path) -> None:
    errors = validate(value, read_object(schema_path), base_path=schema_path.resolve().parent)
    if errors:
        raise ValueError("invalid runtime artifact: " + "; ".join(errors))
    write_json_atomic(path, value)


def _append_operation(root: Path, task_id: str, operation: dict[str, Any]) -> None:
    path = root / "work" / task_id / "operations.jsonl"
    records = read_operation_ledger(path, task_id, OPERATION_SCHEMA)
    latest = next((item for item in records if item["operation_id"] == operation["operation_id"]), None)
    operation = dict(operation)
    operation["revision"] = (latest["revision"] + 1) if latest else 1
    operation["recorded_at"] = utc_now()
    operation.setdefault("phase", "PREPARE" if operation["status"] == "STARTED" else "COMMIT" if operation["status"] == "COMPLETED" else "ROLLBACK")
    operation.setdefault("transaction_id", operation["operation_id"])
    operation.setdefault("idempotency_key", operation["operation_id"])
    if operation["status"] == "COMPLETED":
        operation.setdefault("commit_marker", operation["operation_id"])
    elif operation["status"] in {"FAILED", "UNKNOWN"}:
        operation.setdefault("rollback_marker", operation["operation_id"])
    errors = validate(operation, read_object(OPERATION_SCHEMA), base_path=OPERATION_SCHEMA.resolve().parent)
    if errors:
        raise ValueError("invalid dispatch operation: " + "; ".join(errors))
    append_jsonl(path, operation)


def _active_lease_count(root: Path, current_task_id: str) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    for path in sorted((root / "work").glob("*/lease.json")):
        lease = read_object(path)
        expires_at = parse_timestamp(lease.get("expires_at"))
        if expires_at > now and lease.get("task_id") != current_task_id:
            count += 1
    return count


def _find_existing_dispatch(queue: dict[str, Any], task_id: str, idempotency_key: str) -> dict[str, Any] | None:
    for item in queue.get("dispatches", []):
        if isinstance(item, dict) and item.get("task_id") == task_id and item.get("idempotency_key") == idempotency_key:
            return copy.deepcopy(item)
    return None


def _validate_idempotent_retry(
    existing: dict[str, Any],
    dispatch: dict[str, Any],
    task: dict[str, Any],
    expected_task_revision: int,
) -> None:
    immutable_fields = (
        "dispatch_id",
        "task_id",
        "agent_role",
        "selected_mode",
        "selected_owner",
        "selected_model",
        "input_revisions",
        "approval_references",
        "evidence",
    )
    for field in immutable_fields:
        if existing.get(field) != dispatch.get(field):
            raise ValueError(f"idempotency key conflicts with existing dispatch field: {field}")
    binding_fields = (*EXECUTION_IDENTITY_FIELDS, "plan_revision", "worktree_path", "branch_name", "base_commit", "write_scope_hash", "active_conflicts_checked_at", "isolation_status", "isolation_proof", "input_artifact_hashes")
    for field in binding_fields:
        submitted = dispatch.get(field)
        effective = submitted if submitted is not None else task.get(field)
        if effective is None:
            effective = existing.get(field)
        if existing.get(field) is not None and effective != existing.get(field):
            raise ValueError(f"idempotency key conflicts with existing dispatch field: {field}")
    expected_published_revision = expected_task_revision + 1
    if existing.get("task_revision") != expected_published_revision:
        raise ValueError("idempotency key conflicts with a different task revision")
    if task.get("revision") != existing.get("task_revision"):
        raise ValueError("idempotent dispatch task state revision no longer matches the published envelope")
    for field in binding_fields:
        if task.get(field) is not None and existing.get(field) != task.get(field):
            raise ValueError(f"idempotent dispatch {field} does not match task state")


def persist_dispatch(
    project_root: str,
    dispatch: dict[str, Any],
    config: dict[str, Any],
    deployment: dict[str, Any],
) -> dict[str, Any]:
    """Validate runtime evidence and atomically publish a dispatch envelope."""

    task_id = str(dispatch["task_id"])
    mode = str(dispatch["selected_mode"]).upper()
    if mode == "ASYNC" and not config.get("execution", {}).get("async_execution_enabled", False):
        raise ValueError("async execution is disabled until isolated worktree support is enabled")
    input_revisions = dispatch.get("input_revisions")
    if not isinstance(input_revisions, dict):
        raise ValueError("dispatch.input_revisions must be an object")
    expected_task_revision = input_revisions.get("task")
    expected_queue_revision = input_revisions.get("queue")
    if isinstance(expected_task_revision, bool) or not isinstance(expected_task_revision, int) or expected_task_revision < 0:
        raise ValueError("dispatch.input_revisions.task must be a non-negative integer")
    if isinstance(expected_queue_revision, bool) or not isinstance(expected_queue_revision, int) or expected_queue_revision < 0:
        raise ValueError("dispatch.input_revisions.queue must be a non-negative integer")
    proof = _require_async_proof(task_id, dispatch) if mode == "ASYNC" else None
    idempotency_key = str(dispatch.get("idempotency_key") or f"{task_id}:r{expected_task_revision}")

    with runtime_lock(project_root) as root:
        queue_path = root / "runtime" / "queue.json"
        graph_path = root / "runtime" / "graph.json"
        task_path = root / "work" / task_id / "task-state.json"
        queue = read_object(queue_path)
        graph = read_object(graph_path)
        existing = _find_existing_dispatch(queue, task_id, idempotency_key)
        if existing is not None:
            if not task_path.is_file():
                raise ValueError(f"idempotent dispatch task state does not exist for {task_id}")
            existing_task = read_object(task_path)
            _validate_idempotent_retry(existing, dispatch, existing_task, expected_task_revision)
            lease_path = root / "work" / task_id / "lease.json"
            if lease_path.is_file():
                existing_lease = read_object(lease_path)
                if parse_timestamp(existing_lease.get("expires_at")) <= datetime.now(timezone.utc):
                    raise ValueError("existing dispatch lease is stale; recovery is required before retry")
            else:
                repair_revision = int(existing.get("task_revision", expected_task_revision))
                repair_lease = {
                    "task_id": task_id,
                    "owner": str(existing.get("selected_owner", dispatch["selected_owner"])),
                    "owner_pid": os.getpid(),
                    "owner_identity": str(existing.get("selected_owner", dispatch["selected_owner"])),
                    "task_revision": repair_revision,
                    "acquired_at": utc_now(),
                    "last_heartbeat": utc_now(),
                    "lease_seconds": 300,
                    "expires_at": lease_expiry(300),
                    "idempotency_key": idempotency_key,
                }
                for field in EXECUTION_IDENTITY_FIELDS:
                    value = existing.get(field, existing_task.get(field))
                    if value is not None:
                        repair_lease[field] = str(value)
                for field in ASYNC_BINDING_FIELDS:
                    value = existing.get(field, existing_task.get(field))
                    if value is not None:
                        repair_lease[field] = copy.deepcopy(value)
                validate_execution_identity(existing_task, repair_lease, None)
                write_validated(project_root, f"work/{task_id}/lease.json", repair_lease, LEASE_SCHEMA)
            return existing
        if queue.get("revision") != expected_queue_revision:
            raise ValueError(f"stale queue revision: expected {expected_queue_revision}, current {queue.get('revision')}")
        if not task_path.is_file():
            raise ValueError(f"task state does not exist for {task_id}")
        current_task = read_object(task_path)
        current_revision = current_task.get("revision", 0)
        if current_revision != expected_task_revision:
            raise ValueError(f"stale task revision: expected {expected_task_revision}, current {current_revision}")
        if mode == "ASYNC":
            proof = _require_async_proof(task_id, dispatch, current_task)
        try:
            current_review_contract = validate_contract(current_task.get("review_contract"), review_type="task")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"task {task_id} review_contract is invalid or missing: {exc}") from exc
        submitted_review_contract = dispatch.get("review_contract")
        if submitted_review_contract is not None:
            try:
                submitted_review_contract = validate_contract(submitted_review_contract, review_type="task")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"dispatch review_contract is invalid: {exc}") from exc
            if submitted_review_contract != current_review_contract:
                raise ValueError("dispatch review_contract does not match the pinned task contract")
        current_status = str(current_task.get("status", "")).upper()
        if current_status not in {"READY", "REPAIR_REQUIRED", "QUEUED", "QUEUED_SYNC", "QUEUED_ASYNC"}:
            raise ValueError(f"task status is not dispatchable: {current_status}")
        active_lease = root / "work" / task_id / "lease.json"
        if active_lease.is_file():
            lease = read_object(active_lease)
            if parse_timestamp(lease.get("expires_at")) > datetime.now(timezone.utc):
                raise ValueError(f"task already has an active lease: {task_id}")
            active_lease.unlink()
        dependencies = task_dependencies(current_task)
        runtime_state = read_object(root / "runtime" / "state.json")
        statuses = runtime_state.get("task_statuses", {})
        unaccepted = [dependency for dependency in dependencies if str(statuses.get(dependency, "")).upper() != "ACCEPTED"]
        if unaccepted:
            raise ValueError("dependencies are not accepted: " + ", ".join(unaccepted))
        if _active_lease_count(root, task_id) >= int(config["execution"]["max_parallel_tasks"]):
            raise ValueError("configured max_parallel_tasks has been reached")

        run_id = str(dispatch.get("run_id") or (proof["run_id"] if mode == "ASYNC" and proof is not None else f"RUN-{task_id}-{uuid.uuid4().hex[:12].upper()}"))
        attempt_id = str(dispatch.get("attempt_id") or f"ATTEMPT-{task_id}-{uuid.uuid4().hex[:12].upper()}")
        operation_id = f"OP-{task_id}-DISPATCH-{uuid.uuid4().hex[:12].upper()}"
        next_status = "QUEUED_ASYNC" if mode == "ASYNC" else "QUEUED_SYNC"
        next_revision = current_revision + 1
        envelope = dict(dispatch)
        binding_metadata = (
            _async_binding_metadata(proof, dispatch, current_task)
            if mode == "ASYNC" and proof is not None
            else {
                field: dispatch.get(field, current_task.get(field))
                for field in ("plan_revision", "worktree_path", "branch_name", "input_artifact_hashes")
                if dispatch.get(field, current_task.get(field)) is not None
            }
        )
        for field, value in {"run_id": run_id, "attempt_id": attempt_id, "dispatch_id": envelope["dispatch_id"], **binding_metadata}.items():
            if current_task.get(field) is not None and current_task.get(field) != value:
                raise ValueError(f"dispatch {field} does not match existing task identity")
        envelope.update(
            {
                "status": "RECORDED",
                "idempotency_key": idempotency_key,
                "run_id": run_id,
                "attempt_id": attempt_id,
                "task_revision": next_revision,
                "operation_id": operation_id,
                "review_contract": current_review_contract,
                **binding_metadata,
            }
        )

        original_queue = copy.deepcopy(queue)
        original_graph = copy.deepcopy(graph)
        original_task = copy.deepcopy(current_task)
        operation = {
            "operation_id": operation_id,
            "task_id": task_id,
            "run_id": run_id,
            "type": "OTHER",
            "status": "STARTED",
            "command": "dispatch_task",
            "actor": "agentic-state-tools",
        }
        event_written = False
        try:
            _append_operation(root, task_id, operation)

            task_entry = {
                "task_id": task_id,
                "queue_state": "DISPATCHED",
                "execution_mode": mode,
                "dependency_snapshot": {"depends_on": dependencies, "accepted_task_ids": sorted(statuses)},
                "scope_snapshot": {"write_scope": task_write_scopes(current_task)},
                "owner": str(dispatch["selected_owner"]),
                "revision": next_revision,
                "run_id": run_id,
                "attempt_id": attempt_id,
                "dispatch_id": envelope["dispatch_id"],
                **binding_metadata,
            }
            tasks = [item for item in queue.get("tasks", []) if not isinstance(item, dict) or item.get("task_id") != task_id]
            tasks.append(task_entry)
            queue["tasks"] = tasks
            queue["dispatches"] = [*queue.get("dispatches", []), envelope]
            queue["task_states"] = [item for item in queue.get("task_states", []) if not isinstance(item, dict) or item.get("task_id") != task_id] + [
                {"task_id": task_id, "status": next_status, "revision": next_revision, "run_id": run_id, "attempt_id": attempt_id, "dispatch_id": envelope["dispatch_id"], **binding_metadata}
            ]
            queue["revision"] = int(queue.get("revision", 0)) + 1
            _validated_write(queue_path, queue, QUEUE_SCHEMA)

            nodes = list(graph.get("nodes", []))
            graph_node: dict[str, Any] | None = None
            if mode == "ASYNC":
                graph_node = {
                    "task_id": task_id,
                    "execution_mode": mode,
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "dispatch_id": envelope["dispatch_id"],
                    **binding_metadata,
                }
                for index, node in enumerate(nodes):
                    node_id = node.get("task_id", node.get("id")) if isinstance(node, dict) else node
                    if node_id == task_id:
                        if isinstance(node, dict):
                            node.update(graph_node)
                            graph_node = node
                        else:
                            nodes[index] = graph_node
                        break
                else:
                    nodes.append(graph_node)
            elif task_id not in nodes:
                nodes.append(task_id)
            edges = list(graph.get("edges", []))
            for dependency in dependencies:
                if mode == "ASYNC":
                    expected_identity = {
                        "run_id": run_id,
                        "attempt_id": attempt_id,
                        "dispatch_id": envelope["dispatch_id"],
                        **binding_metadata,
                    }
                    edge = _typed_dependency_edge(dependency, task_id, expected_identity)
                    for index, existing_edge in enumerate(edges):
                        if isinstance(existing_edge, dict) and existing_edge.get("from") == dependency and existing_edge.get("to") == task_id:
                            edges[index] = edge
                            break
                    else:
                        edges.append(edge)
                else:
                    edge = {"from": dependency, "to": task_id}
                    if edge not in edges:
                        edges.append(edge)
            graph["nodes"] = nodes
            graph["edges"] = edges
            graph["revision"] = int(graph.get("revision", 0)) + 1
            _validated_write(graph_path, graph, GRAPH_SCHEMA)

            for field, value in {"run_id": run_id, "attempt_id": attempt_id, "dispatch_id": envelope["dispatch_id"], **binding_metadata}.items():
                if current_task.get(field) is not None and current_task.get(field) != value:
                    raise ValueError(f"dispatch {field} does not match existing task identity")
            next_task = merge_task_state(
                current_task,
                {
                    "status": next_status,
                    "previous_revision": current_revision,
                    "revision": next_revision,
                    "updated_at": utc_now(),
                },
            )
            next_task.update({"run_id": run_id, "attempt_id": attempt_id, "dispatch_id": envelope["dispatch_id"], "idempotency_key": idempotency_key, **binding_metadata})
            write_validated(project_root, f"work/{task_id}/task-state.json", next_task, TASK_STATE_SCHEMA)

            lease = {
                "task_id": task_id,
                "owner": str(dispatch["selected_owner"]),
                "owner_pid": os.getpid(),
                "owner_identity": str(dispatch["selected_owner"]),
                "run_id": run_id,
                "attempt_id": attempt_id,
                "dispatch_id": envelope["dispatch_id"],
                "task_revision": next_revision,
                "acquired_at": utc_now(),
                "last_heartbeat": utc_now(),
                "lease_seconds": 300,
                "expires_at": lease_expiry(300),
                "idempotency_key": idempotency_key,
                **binding_metadata,
            }
            write_validated(project_root, f"work/{task_id}/lease.json", lease, LEASE_SCHEMA)
            validate_execution_identity(next_task, lease, queue)
            if mode == "ASYNC":
                expected_identity = {
                    "task_id": task_id,
                    "run_id": run_id,
                    "attempt_id": attempt_id,
                    "dispatch_id": envelope["dispatch_id"],
                    **binding_metadata,
                }
                _validate_async_record(envelope, expected_identity)
                _validate_async_record(task_entry, expected_identity)
                _validate_async_record(queue["task_states"][-1], expected_identity)
                _validate_async_record(next_task, expected_identity)
                _validate_async_record(lease, expected_identity)
                if graph_node is not None:
                    _validate_async_record(graph_node, expected_identity)

            append_event_for_root(
                root,
                {
                    "type": STATUS_TO_EVENT_TYPE[next_status],
                    "actor": "agentic-state-tools",
                    "task_id": task_id,
                    "run_id": run_id,
                    "data": {"dispatch_id": envelope["dispatch_id"], "attempt_id": attempt_id, "task_revision": next_revision},
                },
            )
            event_written = True
            _append_operation(root, task_id, {**operation, "status": "COMPLETED", "phase": "COMMIT", "commit_marker": operation_id, "result_summary": "dispatch persisted"})
            render_checklist_for_root(root)
            return envelope
        except Exception:
            if not event_written:
                write_json_atomic(queue_path, original_queue)
                write_json_atomic(graph_path, original_graph)
                write_validated(project_root, f"work/{task_id}/task-state.json", original_task, TASK_STATE_SCHEMA)
                if active_lease.exists():
                    active_lease.unlink()
            try:
                _append_operation(root, task_id, {**operation, "status": "FAILED", "phase": "ROLLBACK", "rollback_marker": operation_id, "result_summary": "dispatch transaction failed"})
            except Exception:
                pass
            raise
