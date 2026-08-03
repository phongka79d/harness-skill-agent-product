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
                current_attempt = task_state.get("attempt_id")
                if isinstance(current_attempt, str) and current_attempt:
                    supplied_attempt = payload.get("attempt_id", current_attempt)
                    if supplied_attempt != current_attempt:
                        raise ValueError("checkpoint.attempt_id does not match task state")
                    payload["attempt_id"] = current_attempt
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
