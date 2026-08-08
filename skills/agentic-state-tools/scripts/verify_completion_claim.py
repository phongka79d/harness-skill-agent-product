"""Validate and persist a completion claim against current verification evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from runtime_utils import (  # noqa: E402
    append_event,
    read_json,
    refresh_checklist,
    require_scope_coverage,
    require_task_index_consistent,
    runtime_root,
    sha256_json,
    task_artifact_path,
    task_state_path,
    utc_now,
    validate_task_id,
    verify_workspace_snapshot,
    write_json_atomic,
)

STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"
TASK_SCHEMA = HERE.parents[1] / "schemas" / "task-state.schema.json"
CLAIM_SCHEMA = HERE.parents[1] / "schemas" / "completion-claim.schema.json"
EVIDENCE_SCHEMA = HERE.parents[1] / "schemas" / "verification-evidence.schema.json"
GATE_SCHEMA = HERE.parents[1] / "schemas" / "completion-gate.schema.json"


def _acceptance_ids(claim: dict, evidence: dict) -> tuple[list[str], list[str]]:
    acceptance_ids: list[str] = []
    for item in claim["acceptance"]:
        acceptance_id = str(item["id"]).strip()
        if not acceptance_id:
            raise ValueError("completion claim acceptance IDs must not be blank")
        item["id"] = acceptance_id
        acceptance_ids.append(acceptance_id)
    if len(acceptance_ids) != len(set(acceptance_ids)):
        raise ValueError("completion claim acceptance IDs must be unique")
    check_ids: list[str] = []
    for item in evidence["checks"]:
        check_id = str(item["name"]).strip()
        if not check_id:
            raise ValueError("verification check names must not be blank")
        check_ids.append(check_id)
    if len(check_ids) != len(set(check_ids)):
        raise ValueError("verification check names must be unique acceptance IDs")
    if set(acceptance_ids) != set(check_ids):
        missing = sorted(set(check_ids) - set(acceptance_ids))
        extra = sorted(set(acceptance_ids) - set(check_ids))
        details: list[str] = []
        if missing:
            details.append("claim missing verification IDs: " + ", ".join(missing))
        if extra:
            details.append("claim has unverified IDs: " + ", ".join(extra))
        raise ValueError("acceptance mapping does not match verification checks; " + "; ".join(details))
    return acceptance_ids, check_ids


def verify(project_root: str, claim_path: str) -> dict:
    claim = read_json(claim_path)
    validate_file(claim, CLAIM_SCHEMA, "completion claim")
    task_id = validate_task_id(claim.get("task_id"))
    root = runtime_root(project_root)
    state = read_json(root / "state.json")
    validate_file(state, STATE_SCHEMA, "state")
    require_task_index_consistent(root, state)
    if task_id not in state["tasks"]:
        raise ValueError("task is missing from runtime index")

    task_path = task_state_path(root, task_id)
    verification_path = task_artifact_path(root, task_id, "verification.json")
    if not task_path.is_file():
        raise ValueError("task state is missing")
    if not verification_path.is_file():
        raise ValueError("current verification artifact is missing")

    task = read_json(task_path)
    validate_file(task, TASK_SCHEMA, "task state")
    summary = state["tasks"][task_id]
    for field in ("status", "status_revision", "work_revision", "summary"):
        if task[field] != summary.get(field):
            raise ValueError(f"runtime task summary mismatch: {field}")

    evidence = read_json(verification_path)
    validate_file(evidence, EVIDENCE_SCHEMA, "verification evidence")
    if evidence["task_id"] != task_id:
        raise ValueError("verification evidence is bound to another task")
    if claim["work_revision"] != task["work_revision"]:
        raise ValueError("completion claim is stale for the current work revision")
    if evidence["work_revision"] != task["work_revision"]:
        raise ValueError("verification evidence is stale for the current work revision")
    if evidence["workflow_decision_hash"] != task["workflow_decision_hash"]:
        raise ValueError("verification evidence is bound to another workflow decision")
    verified_files = verify_workspace_snapshot(
        project_root, evidence["workspace"], task_id
    )
    require_scope_coverage(project_root, task, verified_files)
    _acceptance_ids(claim, evidence)

    unresolved = [
        item
        for item in claim["acceptance"]
        if item.get("status") != "PASS" or not item.get("evidence", "").strip()
    ]
    accepted = (
        task["status"] in {"COMPLETED", "ACCEPTED"}
        and evidence["status"] == "PASS"
        and claim["verification_status"] == evidence["status"]
        and not unresolved
    )
    result = {
        "task_id": task_id,
        "status_revision": task["status_revision"],
        "work_revision": task["work_revision"],
        "workflow_decision_hash": task["workflow_decision_hash"],
        "accepted": accepted,
        "outcome": "PASS" if accepted else "BLOCKED",
        "reason": (
            "current work revision, workflow decision, full scope, verification checks, and acceptance mapping all pass"
            if accepted
            else "task is not completed or claim contains non-passing evidence"
        ),
    }
    gate_path = task_artifact_path(root, task_id, "completion-gate.json")
    persisted_claim_path = task_artifact_path(root, task_id, "completion-claim.json")
    if accepted:
        write_json_atomic(persisted_claim_path, claim)
        gate = {
            "schema_version": 1,
            "task_id": task_id,
            "work_revision": task["work_revision"],
            "workflow_decision_hash": task["workflow_decision_hash"],
            "status": "PASS",
            "claim_hash": sha256_json(claim),
            "verified_at": utc_now(),
        }
        validate_file(gate, GATE_SCHEMA, "completion gate")
        write_json_atomic(gate_path, gate)
        append_event(
            project_root,
            "COMPLETION_GATE_PASSED",
            {
                "task_id": task_id,
                "work_revision": task["work_revision"],
                "workflow_decision_hash": task["workflow_decision_hash"],
                "claim_hash": gate["claim_hash"],
            },
        )
    else:
        for path in (gate_path, persisted_claim_path):
            if path.exists():
                path.unlink()
        append_event(project_root, "COMPLETION_GATE_CLEARED", {"task_id": task_id, "reason": result["reason"]})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        result = verify(args.project_root, args.input)
        refresh_checklist(args.project_root)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"CLAIM_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
