"""Explicitly convert a legacy v4 planning bundle to the v5 contract."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE))
from runtime_utils import write_json_atomic  # noqa: E402
from validate_planning import validate_plan  # noqa: E402


def migrate(input_path: str, output_path: str) -> dict:
    source = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if not isinstance(source, dict) or source.get("schema_version") != 4:
        raise ValueError("only schema_version 4 planning bundles can be migrated")
    result = copy.deepcopy(source)
    result["schema_version"] = 5
    task_ids: list[str] = []
    for task in result["tasks"]:
        task_id = str(task.get("id", "")).strip()
        if not task_id:
            raise ValueError("v4 task IDs must be non-empty")
        task["plan_task_id"] = task_id
        task_ids.append(task_id)
    acceptance_ids: list[str] = []
    migrated_acceptance: list[dict[str, str]] = []
    for index, item in enumerate(result["acceptance"], start=1):
        if isinstance(item, dict):
            identifier = str(item.get("id", "")).strip()
            description = str(item.get("description", "")).strip()
        else:
            identifier = f"AC-{index:02d}"
            description = str(item).strip()
        if not identifier or not description:
            raise ValueError("v4 acceptance values must be non-empty")
        migrated_acceptance.append({"id": identifier, "description": description})
        acceptance_ids.append(identifier)
    result["acceptance"] = migrated_acceptance
    result["plan_task_ids"] = task_ids
    result["acceptance_ids"] = acceptance_ids
    result.pop("plan_bundle_hash", None)
    result.pop("plan_review_hash", None)
    validate_plan(result, require_v5=True)
    write_json_atomic(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = migrate(args.input, args.output)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"PLAN_MIGRATION_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("PLAN_MIGRATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
