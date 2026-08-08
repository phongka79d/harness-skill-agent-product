"""Persist verification evidence bound to work revision, decision, and full task scope."""
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
    runtime_root,
    revalidate_plan_binding,
    utc_now,
    validate_task_id,
    verify_workspace_snapshot,
)

CALLER_FIELDS = {
    "schema_version",
    "task_id",
    "task_revision",
    "work_revision",
    "status",
    "checks",
    "workspace",
    "workspace_summary",
    "plan_task_id",
}
VERIFYABLE = {"IN_PROGRESS", "COMPLETED", "ACCEPTED"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    try:
        result = read_json(args.input)
        unknown = sorted(set(result) - CALLER_FIELDS)
        if unknown:
            raise ValueError(
                "caller must not supply derived verification fields: " + ", ".join(unknown)
            )
        task_id = validate_task_id(result.get("task_id"))
        task = ensure_task_binding(args.project_root, task_id)
        if task["status"] not in VERIFYABLE:
            raise ValueError(
                "task is not verifiable; expected IN_PROGRESS, COMPLETED, or ACCEPTED"
            )

        legacy_revision = result.pop("task_revision", None)
        supplied_revision = result.get("work_revision", legacy_revision)
        if supplied_revision is not None and supplied_revision != task["work_revision"]:
            raise ValueError(f"work_revision is stale; current revision is {task['work_revision']}")
        result["schema_version"] = 3
        result["work_revision"] = task["work_revision"]
        result["workflow_decision_hash"] = task["workflow_decision_hash"]
        result["recorded_at"] = utc_now()

        state = read_json(runtime_root(args.project_root) / "state.json")
        plan_binding = state.get("plan_binding", {})
        if isinstance(plan_binding, dict) and plan_binding.get("required"):
            revalidate_plan_binding(args.project_root, plan_binding, expected_decision_hash=task["workflow_decision_hash"])
            if not plan_binding.get("bound"):
                raise ValueError("verification requires a current PASS plan review")
            if task.get("plan_task_id") not in plan_binding.get("plan_task_ids", []):
                raise ValueError("task is not bound to an approved plan_task_id")
            if result.get("plan_task_id") not in {None, task["plan_task_id"]}:
                raise ValueError("verification plan_task_id does not match the task")
            result["plan_task_id"] = task["plan_task_id"]
            result["plan_bundle_hash"] = task.get("plan_bundle_hash")
            result["plan_review_hash"] = task.get("plan_review_hash")
            result["acceptance_ids"] = list(plan_binding.get("acceptance_ids", []))

        validate_file(
            result,
            HERE.parents[1] / "schemas" / "verification-evidence.schema.json",
            "verification evidence",
        )
        checks = result["checks"]
        names: list[str] = []
        for item in checks:
            name = str(item.get("name", "")).strip()
            if not name:
                raise ValueError("verification check names must not be blank")
            item["name"] = name
            names.append(name)
        if len(names) != len(set(names)):
            raise ValueError("verification check names must be unique acceptance IDs")
        if isinstance(plan_binding, dict) and plan_binding.get("required"):
            if set(names) != set(plan_binding.get("acceptance_ids", [])):
                raise ValueError("verification checks must exactly match approved plan acceptance IDs")
        statuses = {str(item.get("status", "")).upper() for item in checks}
        if result["status"] == "PASS" and statuses != {"PASS"}:
            raise ValueError("PASS requires every recorded check to pass")
        if result["status"] == "FAIL" and "FAIL" not in statuses:
            raise ValueError("FAIL requires at least one failed check")
        if result["status"] == "BLOCKED" and "BLOCKED" not in statuses:
            raise ValueError("BLOCKED requires at least one blocked check")

        verified_files = verify_workspace_snapshot(args.project_root, result["workspace"], task_id)
        require_scope_coverage(args.project_root, task, verified_files)
        result["workspace"] = {"files": verified_files}
        identity = bound_worktree_identity(args.project_root, task_id)
        if identity is not None:
            result["workspace"]["worktree"] = identity
        persist_artifact(args.project_root, result, "verification.json", "VERIFICATION_WRITTEN")
        refresh_checklist(args.project_root)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"VERIFICATION_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
