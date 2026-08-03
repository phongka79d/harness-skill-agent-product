"""Create an explicit, dry-run rollback plan from a task operation ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from append_event import append_event_for_root
from operation_ledger import read_operation_ledger
from render_checklist import render_checklist_for_root
from rollback import build_rollback_plan
from runtime_utils import RuntimeLockedError, RuntimeNotInitializedError, read_payload, runtime_lock
from write_artifact import write_validated


SKILL_ROOT = Path(__file__).resolve().parents[1]
OPERATION_SCHEMA = SKILL_ROOT / "schemas/operation.schema.json"
PLAN_SCHEMA = SKILL_ROOT / "schemas/rollback-plan.schema.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--actor", default="primary-agent")
    args = parser.parse_args()
    try:
        request = read_payload(args.input)
        if not isinstance(request, dict):
            raise ValueError("rollback request must be an object")
        task_id = request.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("rollback request requires task_id")
        with runtime_lock(args.project_root) as root:
            operations = read_operation_ledger(root / "work" / task_id / "operations.jsonl", task_id, OPERATION_SCHEMA)
            plan = build_rollback_plan(request, operations)
            relative = f"recovery/rollback-plan-{plan['plan_id']}.json"
            target = root / relative
            if target.exists():
                raise ValueError(f"rollback plan already exists: {plan['plan_id']}")
            output = write_validated(args.project_root, relative, plan, PLAN_SCHEMA)
            append_event_for_root(
                root,
                {
                    "type": "ROLLBACK_PLANNED",
                    "actor": args.actor,
                    "task_id": task_id,
                    "data": {"plan_id": plan["plan_id"], "operation_ids": plan["operation_ids"], "dry_run": True},
                },
            )
            render_checklist_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"ROLLBACK_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"ROLLBACK_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"ROLLBACK_PLAN_WRITTEN: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
