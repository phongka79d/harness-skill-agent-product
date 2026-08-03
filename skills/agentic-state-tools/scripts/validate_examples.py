"""Validate bundled examples through schemas and runtime normalization paths."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

from create_batch_review import normalize as normalize_batch_review
from create_context import normalize as normalize_context
from dispatch_task import normalize_dispatch
from resolve_rubric import resolve_rubric
from runtime_utils import validate_event
from validate_payload import validate
from validate_planning import validate_manifest

CONFIG_SKILL = Path(__file__).resolve().parents[2] / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))
from load_config import load_config, load_deployment_config  # noqa: E402


SCHEMA_MAP = {
    "batch-review.json": "batch-review.schema.json",
    "context.json": "context.schema.json",
    "event.json": "event.schema.json",
    "heartbeat.json": "lease.schema.json",
    "lock.json": "lock.schema.json",
    "operation.json": "operation.schema.json",
    "review.json": "review.schema.json",
    "task-state.json": "task-state.schema.json",
    "v1-dispatch.json": "dispatch.schema.json",
    "v1-recovery.json": "reconciliation.schema.json",
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


def _schema_errors(value: Any, schema_path: Path) -> list[str]:
    schema = _read_json(schema_path)
    return validate(value, schema, base_path=schema_path.resolve().parent)


def _validate_one(path: Path, *, config: dict[str, Any], deployment: dict[str, Any], schema_root: Path) -> list[str]:
    value = _read_json(path)
    errors: list[str] = []
    if path.name == "v1-planning-bundle.json":
        errors.extend(validate_manifest(value))
        return errors
    schema_name = SCHEMA_MAP.get(path.name)
    if schema_name is None:
        return ["no runtime validator is registered"]
    errors.extend(_schema_errors(value, schema_root / schema_name))
    if errors:
        return errors
    try:
        if path.name == "context.json":
            normalize_context(value, config)
        elif path.name == "event.json":
            validate_event(value)
        elif path.name == "review.json":
            if not isinstance(value.get("resolved_rubric"), dict) and value.get("legacy_migration") is not True:
                raise ValueError("review example lacks a resolved_rubric")
        elif path.name == "batch-review.json":
            if value.get("legacy_migration") is not True:
                normalize_batch_review(value)
        elif path.name == "v1-dispatch.json":
            dispatch = copy.deepcopy(value)
            role = dispatch.get("agent_role")
            reference = dispatch.get("model_reference")
            if reference == f"agents.{role}.model_ref" and isinstance(config.get("agents", {}).get(role), dict):
                dispatch["selected_model"] = deployment["model_ids"][config["agents"][role]["model_ref"]]
            dispatch["input_revisions"] = {"task": 1, "queue": 0}
            normalize_dispatch(dispatch, config, deployment)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return errors


def validate_all_examples(
    examples_root: str | Path,
    *,
    config_root: str | Path | None = None,
    deployment_path: str | Path | None = None,
) -> list[str]:
    examples = Path(examples_root).expanduser().resolve()
    configuration = Path(config_root).expanduser().resolve() if config_root else CONFIG_SKILL
    config = load_config(configuration / "config/agentic-config.yaml")
    deployment = load_deployment_config(deployment_path, config)
    schema_root = Path(__file__).resolve().parents[1] / "schemas"
    errors: list[str] = []
    for path in sorted(examples.glob("*.json")):
        try:
            path_errors = _validate_one(path, config=config, deployment=deployment, schema_root=schema_root)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            path_errors = [str(exc)]
        errors.extend(f"{path.name}: {error}" for error in path_errors)
    return errors


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--examples-root", required=True)
    parser.add_argument("--deployment")
    args = parser.parse_args()
    try:
        errors = validate_all_examples(args.examples_root, deployment_path=args.deployment)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"EXAMPLES_INVALID: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"EXAMPLE_INVALID: {error}", file=sys.stderr)
        return 1
    print("EXAMPLES_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
