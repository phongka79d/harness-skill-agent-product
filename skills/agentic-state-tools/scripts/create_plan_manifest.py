"""Validate a planning bundle and atomically write its canonical manifest."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "agentic-configuration" / "scripts"))
from runtime_utils import sha256_json, utc_now, write_json_atomic  # noqa: E402
from schema_validation import validate_file  # noqa: E402
from validate_planning import validate_plan  # noqa: E402

MANIFEST_SCHEMA = HERE.parents[1] / "schemas" / "plan-manifest.schema.json"


def _ids(bundle: dict) -> tuple[list[str], list[str]]:
    tasks = bundle["tasks"]
    task_ids = [str(item.get("plan_task_id", item["id"])).strip() for item in tasks]
    acceptance_ids: list[str] = []
    for item in bundle["acceptance"]:
        acceptance_ids.append(str(item.get("id", "")).strip() if isinstance(item, dict) else str(item).strip())
    return task_ids, acceptance_ids


def create(input_path: str, output_path: str, *, task_id: str | None = None, decision_hash: str | None = None, require_v5: bool = True) -> dict:
    bundle = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if not isinstance(bundle, dict):
        raise ValueError("planning bundle must be an object")
    validate_plan(bundle, require_v5=require_v5)
    task_ids, acceptance_ids = _ids(bundle)
    result = {
        "schema_version": 1,
        "plan_bundle_hash": sha256_json(bundle),
        "plan_task_ids": task_ids,
        "acceptance_ids": acceptance_ids,
        "bundle": bundle,
        "created_at": utc_now(),
    }
    if task_id:
        result["task_id"] = task_id
    if decision_hash:
        result["workflow_decision_hash"] = decision_hash
    validate_file(result, MANIFEST_SCHEMA, "plan manifest")
    write_json_atomic(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--workflow-decision-hash")
    parser.add_argument("--allow-v4", action="store_true", help="allow a legacy bundle outside a controlled gate")
    args = parser.parse_args()
    try:
        result = create(
            args.input,
            args.output,
            task_id=args.task_id,
            decision_hash=args.workflow_decision_hash,
            require_v5=not args.allow_v4,
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"PLAN_MANIFEST_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("PLAN_MANIFEST_WRITTEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
