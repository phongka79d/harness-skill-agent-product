"""Persist an independent review bound to the current task work revision."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from artifact_writer import ensure_task_binding, persist_artifact  # noqa: E402
from runtime_utils import (  # noqa: E402
    read_json,
    refresh_checklist,
    require_scope_coverage,
    bound_worktree_identity,
    utc_now,
    validate_task_id,
    verify_workspace_snapshot,
)
from review_validation import (  # noqa: E402
    validate_review_contract,
    validate_review_outcome,
)

CALLER_FIELDS = {
    "schema_version",
    "task_id",
    "review_mode",
    "review_rubric_id",
    "review_rubric_version",
    "criteria",
    "outcome",
    "summary",
    "findings",
    "workspace",
    "workspace_summary",
}
REVIEWABLE = {"IN_PROGRESS", "COMPLETED", "ACCEPTED"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        supplied = read_json(args.input)
        unknown = sorted(set(supplied) - CALLER_FIELDS)
        if unknown:
            raise ValueError("caller must not supply derived review fields: " + ", ".join(unknown))
        task_id = validate_task_id(supplied.get("task_id"))
        task = ensure_task_binding(args.project_root, task_id)
        if task["status"] not in REVIEWABLE:
            raise ValueError(
                "task is not reviewable; expected IN_PROGRESS, COMPLETED, or ACCEPTED"
            )
        result = dict(supplied)
        result["schema_version"] = 5
        result["task_id"] = task_id
        result["work_revision"] = task["work_revision"]
        result["workflow_decision_hash"] = task["workflow_decision_hash"]
        result["recorded_at"] = utc_now()
        outcome = str(result.get("outcome", "")).strip().upper()
        result["outcome"] = outcome
        validate_review_outcome(outcome, result.get("findings"))
        validate_review_contract(result, "task")
        verified_files = verify_workspace_snapshot(args.project_root, result.get("workspace"), task_id)
        require_scope_coverage(args.project_root, task, verified_files)
        result["workspace"] = {"files": verified_files}
        identity = bound_worktree_identity(args.project_root, task_id)
        if identity is not None:
            result["workspace"]["worktree"] = identity
        validate_file(result, HERE.parents[1] / "schemas" / "review.schema.json", "review")
        persist_artifact(args.project_root, result, "review.json", "REVIEW_WRITTEN")
        refresh_checklist(args.project_root)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"ARTIFACT_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
