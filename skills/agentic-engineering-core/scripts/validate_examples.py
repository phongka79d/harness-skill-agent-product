"""Validate every shipped JSON example against its public schema."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
STATE_SCRIPTS = HERE.parents[2] / "agentic-state-tools" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
sys.path.insert(0, str(STATE_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from plan_docs import inspect_plan_docs  # noqa: E402
from runtime_utils import sha256_json, validate_plan_binding_documents  # noqa: E402
from review_validation import validate_review_outcome  # noqa: E402
from validate_planning import validate_plan  # noqa: E402

EXAMPLE_SCHEMAS = {
    "agentic-delivery-finalizer/examples/delivery-decision.example.json": "agentic-state-tools/schemas/delivery-decision.schema.json",
    "agentic-plan-architect/examples/planning-bundle.example.json": "agentic-state-tools/schemas/planning-bundle.schema.json",
    "agentic-state-tools/examples/batch-review.example.json": "agentic-state-tools/schemas/batch-review.schema.json",
    "agentic-state-tools/examples/context.example.json": "agentic-state-tools/schemas/context.schema.json",
    "agentic-state-tools/examples/handoff.example.json": "agentic-state-tools/schemas/handoff.schema.json",
    "agentic-state-tools/examples/review.example.json": "agentic-state-tools/schemas/review.schema.json",
    "agentic-state-tools/examples/verification.example.json": "agentic-state-tools/schemas/verification-evidence.schema.json",
    "agentic-state-tools/examples/workflow-decision.example.json": "agentic-state-tools/schemas/workflow-decision.schema.json",
    "agentic-state-tools/examples/workflow-request.example.json": "agentic-state-tools/schemas/workflow-request.schema.json",
    "agentic-state-tools/examples/plan-manifest.example.json": "agentic-state-tools/schemas/plan-manifest.schema.json",
    "agentic-state-tools/examples/plan-review.example.json": "agentic-state-tools/schemas/plan-review.schema.json",
    "agentic-systematic-debugging/examples/debug-investigation.example.json": "agentic-state-tools/schemas/debug-investigation.schema.json",
    "agentic-verification-before-completion/examples/completion-claim.example.json": "agentic-state-tools/schemas/completion-claim.schema.json",
}

PLAN_BUNDLE_EXAMPLE = "agentic-plan-architect/examples/planning-bundle.example.json"
PLAN_DOCS_EXAMPLE = "agentic-plan-architect/examples/2026-08-09-example-feature"
PLAN_MANIFEST_EXAMPLE = "agentic-state-tools/examples/plan-manifest.example.json"
PLAN_REVIEW_EXAMPLE = "agentic-state-tools/examples/plan-review.example.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills-root", required=True)
    args = parser.parse_args()
    root = Path(args.skills_root).expanduser().resolve()
    errors: list[str] = []

    shipped = {
        path.relative_to(root).as_posix()
        for path in root.glob("*/examples/*.json")
    }
    expected = set(EXAMPLE_SCHEMAS)
    for path in sorted(shipped - expected):
        errors.append(f"unmapped example: {path}")
    for path in sorted(expected - shipped):
        errors.append(f"missing example: {path}")

    for example_rel, schema_rel in sorted(EXAMPLE_SCHEMAS.items()):
        example_path = root / example_rel
        schema_path = root / schema_rel
        if not example_path.is_file() or not schema_path.is_file():
            continue
        try:
            value = json.loads(example_path.read_text(encoding="utf-8"))
            validate_file(value, schema_path, example_rel)
            if example_rel.endswith("workflow-decision.example.json"):
                expected_hash = sha256_json({key: item for key, item in value.items() if key != "decision_hash"})
                if value["decision_hash"] != expected_hash:
                    raise ValueError(f"{example_rel}: decision_hash does not match content")
            if example_rel.endswith(("agentic-state-tools/examples/review.example.json", "agentic-state-tools/examples/batch-review.example.json")):
                validate_review_outcome(value["outcome"], value["findings"])
            if example_rel == PLAN_BUNDLE_EXAMPLE:
                validate_plan(value, require_v5=True)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))

    try:
        bundle = json.loads((root / PLAN_BUNDLE_EXAMPLE).read_text(encoding="utf-8"))
        manifest = json.loads((root / PLAN_MANIFEST_EXAMPLE).read_text(encoding="utf-8"))
        review = json.loads((root / PLAN_REVIEW_EXAMPLE).read_text(encoding="utf-8"))
        descriptor = inspect_plan_docs(root / PLAN_DOCS_EXAMPLE)
        if manifest.get("bundle") != bundle:
            raise ValueError("shipped plan manifest bundle differs from planning-bundle.example.json")
        if manifest.get("plan_path") != descriptor["plan_path"]:
            raise ValueError("shipped plan manifest path differs from the Markdown plan tree")
        if manifest.get("plan_docs_hash") != descriptor["plan_docs_hash"]:
            raise ValueError("shipped plan manifest hash differs from the Markdown plan tree")
        if manifest.get("plan_task_ids") != descriptor["plan_task_ids"]:
            raise ValueError("shipped plan Task IDs differ between JSON and Markdown")
        if set(manifest.get("acceptance_ids", [])) != set(descriptor["acceptance_ids"]):
            raise ValueError("shipped plan Acceptance IDs differ between JSON and Markdown")
        expected_acceptance_ids_by_task = {
            str(task.get("plan_task_id", task["id"])).strip(): [
                str(acceptance_id).strip() for acceptance_id in task["acceptance"]
            ]
            for task in bundle["tasks"]
        }
        if descriptor["acceptance_ids_by_task"] != expected_acceptance_ids_by_task:
            raise ValueError(
                "shipped plan task Acceptance IDs differ between JSON and Markdown"
            )

        validate_plan_binding_documents(manifest, review, require_v5=True)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        errors.append(str(exc))

    if errors:
        print(json.dumps({"status": "INVALID", "errors": errors}, indent=2))
        return 1
    print(json.dumps({"status": "VALID", "examples": len(EXAMPLE_SCHEMAS)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
