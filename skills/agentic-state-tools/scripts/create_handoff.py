"""Validate and write a generated executor handoff artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from append_event import append_event
from capture_workspace import capture_workspace
from render_checklist import render_checklist
from runtime_utils import RuntimeLockedError, RuntimeNotInitializedError, next_revision, parse_timestamp, read_object, read_payload, runtime_lock, utc_now, validate_identifier
from validate_payload import validate
from write_artifact import write_validated


HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ROOT = Path(__file__).resolve().parents[1]
DEBUG_INVESTIGATION_SCHEMA = ROOT / "schemas/debug-investigation.schema.json"


def _workspace_evidence_hash(root: Path) -> str:
    snapshot = capture_workspace(root.parent)
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_hash_map(value: object, field: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"handoff.{field} must be an object")
    for key, digest in value.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(digest, str) or not HASH_PATTERN.fullmatch(digest):
            raise ValueError(f"handoff.{field} must map non-empty names to SHA-256 hashes")


def _bound_investigation_id(root: Path, task_id: str, task_state: dict[str, object]) -> str | None:
    """Find the repair binding from task state or its persisted dispatch."""

    state_id = task_state.get("investigation_id")
    if state_id is not None and (not isinstance(state_id, str) or not state_id.strip()):
        raise ValueError("task-state investigation_id must be a non-empty string")
    candidates: set[str] = {state_id} if isinstance(state_id, str) else set()
    queue_path = root / "runtime" / "queue.json"
    if queue_path.is_file():
        queue = read_object(queue_path)
        dispatch_id = task_state.get("dispatch_id")
        for record in queue.get("dispatches", []):
            if not isinstance(record, dict) or record.get("task_id") != task_id:
                continue
            if dispatch_id is not None and record.get("dispatch_id") != dispatch_id:
                continue
            value = record.get("investigation_id")
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("dispatch investigation_id must be a non-empty string")
                candidates.add(value)
    if len(candidates) > 1:
        raise ValueError("task and dispatch investigation bindings do not match")
    return next(iter(candidates), None)


def _require_complete_repair_evidence(
    root: Path,
    task_id: str,
    task_state: dict[str, object],
    payload: dict[str, object],
    investigation_id: str,
) -> None:
    supplied_id = payload.get("investigation_id")
    if supplied_id != investigation_id:
        raise ValueError("complete repair handoff requires the matching investigation_id")
    path = root / "work" / task_id / "debug-investigation.json"
    if not path.is_file():
        raise ValueError("complete repair handoff requires a canonical debug investigation artifact")
    investigation = read_object(path)
    errors = validate(investigation, read_object(DEBUG_INVESTIGATION_SCHEMA), base_path=DEBUG_INVESTIGATION_SCHEMA.resolve().parent)
    if errors:
        raise ValueError("repair investigation schema validation failed: " + "; ".join(errors))
    if investigation.get("investigation_id") != investigation_id:
        raise ValueError("handoff investigation_id does not match canonical artifact")
    expected_identity = {
        "task_id": task_id,
        "run_id": payload.get("run_id"),
        "attempt_id": payload.get("attempt_id"),
        "task_revision": payload.get("task_revision"),
    }
    for field, expected in expected_identity.items():
        if investigation.get(field) != expected:
            raise ValueError(f"repair investigation {field} does not match handoff")
    for field in ("run_id", "attempt_id"):
        if task_state.get(field) is not None and task_state.get(field) != payload.get(field):
            raise ValueError(f"handoff.{field} does not match the current task state")
    if investigation.get("status") not in {"ROOT_CAUSE_CONFIRMED", "COMPLETED"}:
        raise ValueError("complete repair handoff requires a confirmed root cause")
    root_cause = investigation.get("root_cause")
    if not isinstance(root_cause, str) or not root_cause.strip():
        raise ValueError("complete repair handoff requires root-cause evidence")
    regression = investigation.get("regression_check")
    if not isinstance(regression, dict) or regression.get("status") != "PASS" or regression.get("exit_code") != 0:
        raise ValueError("complete repair handoff requires a passing regression check with exit_code 0")
    if regression.get("workspace_hash") != _workspace_evidence_hash(root):
        raise ValueError("complete repair handoff requires fresh workspace-bound regression evidence")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="executor")
    args = parser.parse_args()
    try:
        payload = read_payload(args.input)
        if not isinstance(payload, dict):
            raise ValueError("handoff must be an object")
        validate_identifier(args.task_id, "task_id")
        payload = dict(payload)
        payload["task_id"] = args.task_id
        payload.setdefault("handoff_id", f"HANDOFF-{args.task_id}-{utc_now().replace(':', '').replace('-', '')}")
        payload.setdefault("created_at", utc_now())
        for field in ("run_id", "attempt_id", "from_role", "to_role"):
            if not isinstance(payload.get(field), str) or not payload[field].strip():
                raise ValueError(f"handoff.{field} must be a non-empty string")
        for field in ("task_revision", "plan_revision"):
            if isinstance(payload.get(field), bool) or not isinstance(payload.get(field), int) or payload[field] < 1:
                raise ValueError(f"handoff.{field} must be a positive integer")
        validate_hash_map(payload.get("input_artifact_hashes"), "input_artifact_hashes")
        validate_hash_map(payload.get("output_artifact_hashes"), "output_artifact_hashes")
        if not isinstance(payload.get("evidence"), dict):
            raise ValueError("handoff.evidence must be an object")
        parse_timestamp(payload["created_at"])
        with runtime_lock(args.project_root) as root:
            task_state_path = root / "work" / args.task_id / "task-state.json"
            if task_state_path.is_file():
                task_state = read_object(task_state_path)
                if task_state.get("revision") is not None and payload["task_revision"] != task_state.get("revision"):
                    raise ValueError("handoff.task_revision does not match the current task state")
                for field in ("run_id", "attempt_id"):
                    if task_state.get(field) is not None and payload[field] != task_state.get(field):
                        raise ValueError(f"handoff.{field} does not match the current task state")
                if task_state.get("dispatch_id") is not None and payload.get("dispatch_id") != task_state.get("dispatch_id"):
                    raise ValueError("handoff.dispatch_id does not match the current task state")
                investigation_id = _bound_investigation_id(root, args.task_id, task_state)
                if payload.get("status") == "COMPLETE" and investigation_id is not None:
                    _require_complete_repair_evidence(root, args.task_id, task_state, payload, investigation_id)
            else:
                investigation_id = None
            existing = root / "work" / args.task_id / "handoff.json"
            existing_revision = int(read_object(existing).get("revision", 0)) if existing.is_file() else 0
            if existing.is_file():
                previous = read_object(existing)
                if payload["handoff_id"] == previous.get("handoff_id"):
                    for field in ("run_id", "attempt_id", "task_revision", "plan_revision", "from_role", "to_role"):
                        if payload[field] != previous.get(field):
                            raise ValueError("handoff identity cannot be reused for another attempt or revision")
            payload["revision"] = next_revision(payload, existing_revision)
            target = write_validated(
                args.project_root,
                f"work/{args.task_id}/handoff.json",
                payload,
                Path(__file__).resolve().parents[1] / "schemas/handoff.schema.json",
            )
            append_event(
                args.project_root,
                {
                    "type": "HANDOFF_CREATED",
                    "actor": args.actor,
                    "task_id": args.task_id,
                    "data": {
                        "handoff_id": payload["handoff_id"],
                        **({"investigation_id": payload["investigation_id"]} if payload.get("investigation_id") else {}),
                    },
                },
                acquire_lock=False,
                refresh_checklist=False,
            )
            render_checklist(args.project_root, acquire_lock=False)
    except RuntimeNotInitializedError as exc:
        print(f"HANDOFF_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError) as exc:
        print(f"HANDOFF_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"HANDOFF_WRITTEN: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
