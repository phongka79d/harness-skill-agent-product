"""Resolve async or sync execution for one task without mutating runtime state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runtime_utils import read_object

CONFIG_SKILL = Path(__file__).resolve().parents[2] / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))

from load_config import load_config  # noqa: E402


def resolve_execution_mode(task: dict[str, Any], *, scope_conflict: bool = False, dependencies_pending: bool = False) -> str:
    config = load_config()
    requested = str(task.get("execution_mode", "auto")).lower()
    if requested not in {"auto", "async", "sync"}:
        raise ValueError("execution_mode must be auto, async, or sync")
    if requested == "auto":
        requested = str(config["execution"]["default_mode"]).lower()
    status = str(task.get("status", "")).upper()
    if requested == "sync" or scope_conflict or task.get("scope_conflict") is True or dependencies_pending or task.get("dependencies_pending") is True or status in {"REPAIR_REQUIRED", "BLOCKED", "ESCALATED", "RECOVERY_PENDING", "STALE", "RESUMING", "PAUSED"}:
        return "SYNC"
    return "ASYNC"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--scope-conflict", action="store_true")
    parser.add_argument("--dependencies-pending", action="store_true")
    args = parser.parse_args()
    try:
        task = read_object(args.input)
        result = {"task_id": task.get("task_id"), "execution_mode": resolve_execution_mode(task, scope_conflict=args.scope_conflict, dependencies_pending=args.dependencies_pending)}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"EXECUTION_MODE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
