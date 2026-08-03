"""Validate and write a generated checkpoint artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from append_event import append_event_for_root
from render_checklist import render_checklist_for_root
from capture_workspace import capture_workspace
from runtime_utils import RuntimeLockedError, RuntimeNotInitializedError, next_revision, read_object, read_payload, runtime_lock, utc_now, validate_identifier
from write_artifact import write_validated
from inspect_recovery import validate_checkpoint_binding
from task_state_contract import EXECUTION_IDENTITY_FIELDS, validate_execution_identity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="executor")
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
        if not isinstance(payload, dict) or not isinstance(payload.get("task_id"), str) or not payload["task_id"]:
            raise ValueError("checkpoint requires a non-empty string task_id")
        payload = dict(payload)
        task_id = payload["task_id"]
        validate_identifier(task_id, "task_id")
        with runtime_lock(args.project_root) as root:
            existing = root / "work" / task_id / "checkpoint.json"
            previous_revision = 0
            if existing.is_file():
                previous_revision = int(read_object(existing).get("revision", 0))
            task_state_path = root / "work" / task_id / "task-state.json"
            if task_state_path.is_file():
                task_state = read_object(task_state_path)
                current_task_revision = task_state.get("revision")
                if isinstance(current_task_revision, int) and not isinstance(current_task_revision, bool):
                    supplied_task_revision = payload.get("task_revision", current_task_revision)
                    if supplied_task_revision != current_task_revision:
                        raise ValueError("checkpoint.task_revision does not match task state")
                    payload["task_revision"] = current_task_revision
                for field in EXECUTION_IDENTITY_FIELDS:
                    current_identity = task_state.get(field)
                    if isinstance(current_identity, str) and current_identity:
                        supplied_identity = payload.get(field, current_identity)
                        if supplied_identity != current_identity:
                            raise ValueError(f"checkpoint.{field} does not match task state")
                        payload[field] = current_identity
                current_hashes = task_state.get("input_artifact_hashes")
                if current_hashes is not None:
                    supplied_hashes = payload.get("input_artifact_hashes", current_hashes)
                    if supplied_hashes != current_hashes:
                        raise ValueError("checkpoint.input_artifact_hashes do not match task state")
                    payload["input_artifact_hashes"] = current_hashes
                binding_errors = validate_checkpoint_binding(task_state, payload)
                if binding_errors:
                    raise ValueError("checkpoint binding is inconsistent: " + "; ".join(binding_errors))
                lease_path = task_state_path.parent / "lease.json"
                queue_path = root / "runtime" / "queue.json"
                lease = read_object(lease_path) if lease_path.is_file() else None
                queue = read_object(queue_path) if queue_path.is_file() else None
                validate_execution_identity(task_state, lease, queue)
            workspace = capture_workspace(
                root.parent,
                expected_files=payload.get("files_modified", []),
                expected_base=payload.get("base_commit"),
            )
            payload["workspace_snapshot"] = workspace
            payload["workspace_evidence_hash"] = hashlib.sha256(json.dumps(workspace, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            payload.setdefault("workspace_status", workspace["workspace_status"])
            if workspace.get("base_commit") and not payload.get("base_commit") and workspace["workspace_status"] != "NOT_A_REPOSITORY":
                payload["base_commit"] = workspace["base_commit"]
            if "files_modified" not in payload:
                payload["files_modified"] = workspace["changed_files"]
            payload.setdefault("checkpoint_id", f"CP-{task_id}-{previous_revision + 1}")
            payload.setdefault("created_at", utc_now())
            payload["revision"] = next_revision(payload, previous_revision)
            target = write_validated(
                args.project_root,
                f"work/{task_id}/checkpoint.json",
                payload,
                Path(__file__).resolve().parents[1] / "schemas/checkpoint.schema.json",
            )
            append_event_for_root(
                root,
                {"type": "CHECKPOINT_CREATED", "actor": args.actor, "task_id": task_id, "data": {"checkpoint_id": payload["checkpoint_id"]}},
            )
            render_checklist_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"CHECKPOINT_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"CHECKPOINT_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"CHECKPOINT_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
