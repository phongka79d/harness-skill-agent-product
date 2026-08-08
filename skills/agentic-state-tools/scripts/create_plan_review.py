"""Validate a plan review against a manifest and atomically persist its hash."""
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
from review_validation import validate_review_contract  # noqa: E402

MANIFEST_SCHEMA = HERE.parents[1] / "schemas" / "plan-manifest.schema.json"
REVIEW_SCHEMA = HERE.parents[1] / "schemas" / "plan-review.schema.json"


def create(input_path: str, manifest_path: str, output_path: str) -> dict:
    review_input = json.loads(Path(input_path).read_text(encoding="utf-8"))
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    validate_file(manifest, MANIFEST_SCHEMA, "plan manifest")
    if not isinstance(review_input, dict):
        raise ValueError("plan review must be an object")
    outcome = review_input.get("outcome")
    if outcome not in {"PASS", "FAIL", "BLOCKED"}:
        raise ValueError("plan review outcome must be PASS, FAIL, or BLOCKED")
    review_contract = {
        "review_mode": review_input.get("review_mode"),
        "review_rubric_id": review_input.get("review_rubric_id"),
        "review_rubric_version": review_input.get("review_rubric_version"),
        "outcome": outcome,
        "criteria": review_input.get("criteria"),
    }
    validate_review_contract(review_contract, "plan")
    base = {
        "schema_version": 1,
        "review_mode": review_contract["review_mode"],
        "review_rubric_id": review_contract["review_rubric_id"],
        "review_rubric_version": review_contract["review_rubric_version"],
        "outcome": outcome,
        "plan_bundle_hash": manifest["plan_bundle_hash"],
        "acceptance_ids": list(manifest["acceptance_ids"]),
        "criteria": review_contract["criteria"],
        "reviewed_at": utc_now(),
    }
    for key in ("task_id", "workflow_decision_hash"):
        if key in review_input:
            base[key] = review_input[key]
    result = dict(base)
    result["plan_review_hash"] = sha256_json(base)
    validate_file(result, REVIEW_SCHEMA, "plan review")
    write_json_atomic(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = create(args.input, args.manifest, args.output)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"PLAN_REVIEW_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("PLAN_REVIEW_WRITTEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
