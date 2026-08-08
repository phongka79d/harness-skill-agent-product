"""Write a bounded, validated context.json artifact."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from load_config import load_config  # noqa: E402
from schema_validation import validate_file  # noqa: E402

from artifact_writer import persist_artifact  # noqa: E402
from runtime_utils import (  # noqa: E402
    normalize_workspace_path,
    read_json,
    resolve_workspace_context,
    runtime_root,
    sha256_json,
)

CONTEXT_SCHEMA = HERE.parents[1] / "schemas" / "context.schema.json"
DECISION_SCHEMA = HERE.parents[1] / "schemas" / "workflow-decision.schema.json"


def _limits(
    project_root: str, decision_path: str | None, config_path: str | None
) -> dict[str, Any]:
    config = load_config(config_path)
    state_path = runtime_root(project_root) / "state.json"
    state = read_json(state_path) if state_path.is_file() else None
    if state is not None and state.get("config_hash") != sha256_json(config):
        raise ValueError("runtime was created from a different configuration")

    if decision_path:
        decision = read_json(decision_path)
        validate_file(decision, DECISION_SCHEMA, "workflow decision")
        expected_hash = sha256_json(
            {key: value for key, value in decision.items() if key != "decision_hash"}
        )
        if decision["decision_hash"] != expected_hash:
            raise ValueError("workflow decision hash does not match its content")
        if decision["config_hash"] != sha256_json(config):
            raise ValueError("workflow decision was created from a different configuration")
        if state is not None and state.get("workflow_decision_hash") != decision["decision_hash"]:
            raise ValueError("context decision does not match the active runtime")
        budget = decision["context_budget"]
        expected_budget = {
            "max_files": config["context_budget"][f"{decision['execution_depth']}_max_files"],
            "max_bytes": config["context_budget"]["max_bytes"],
            "allow_unbounded_scan": config["context_budget"]["allow_unbounded_scan"],
        }
        if budget != expected_budget:
            raise ValueError("workflow decision context budget does not match central configuration")
        if decision["limits"]["max_context_files"] != budget["max_files"]:
            raise ValueError("workflow decision context file limits are inconsistent")
        if decision["limits"]["max_context_bytes"] != budget["max_bytes"]:
            raise ValueError("workflow decision context byte limits are inconsistent")
    else:
        depth = (state or {}).get("execution_depth", "standard")
        budget = {
            "max_files": config["context_budget"][f"{depth}_max_files"],
            "max_bytes": config["context_budget"]["max_bytes"],
            "allow_unbounded_scan": config["context_budget"]["allow_unbounded_scan"],
        }

    if budget["allow_unbounded_scan"]:
        raise ValueError("unbounded context scans are disabled")
    return budget


def _prepare_payload(
    project_root: str, input_path: str, budget: dict[str, Any]
) -> dict[str, Any]:
    payload = read_json(input_path)
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("context.files must contain at least one explicit file")
    if len(files) > budget["max_files"]:
        raise ValueError(
            f"context file count exceeds limit ({len(files)}>{budget['max_files']})"
        )

    workspace_root, identity = resolve_workspace_context(
        project_root, task_id=payload.get("task_id")
    )
    seen: set[str] = set()
    byte_count = 0
    for index, value in enumerate(files):
        path, normalized = normalize_workspace_path(workspace_root, value)
        if normalized in seen:
            raise ValueError(f"duplicate context file: {normalized}")
        seen.add(normalized)
        if not path.is_file():
            raise ValueError(f"context file is missing or not a regular file: {value}")
        byte_count += path.stat().st_size
        if byte_count > budget["max_bytes"]:
            raise ValueError(
                f"context byte count exceeds limit ({byte_count}>{budget['max_bytes']})"
            )

    for field, expected in (("file_count", len(files)), ("byte_count", byte_count)):
        if field in payload and payload[field] != expected:
            raise ValueError(f"context {field} does not match the listed files")

    payload["file_count"] = len(files)
    payload["byte_count"] = byte_count
    payload["context_budget"] = budget
    if identity is not None:
        payload["worktree"] = identity
    validate_file(payload, CONTEXT_SCHEMA, "context")
    return payload

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--decision")
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        budget = _limits(args.project_root, args.decision, args.config)
        payload = _prepare_payload(args.project_root, args.input, budget)
        result = persist_artifact(args.project_root, payload, "context.json", "CONTEXT_WRITTEN")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ARTIFACT_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
