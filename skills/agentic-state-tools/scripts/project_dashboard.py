"""Print a compact validated read-only dashboard from minimal runtime state."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from runtime_utils import read_json, require_task_index_consistent, runtime_root  # noqa: E402

STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"
DASHBOARD_SCHEMA = HERE.parents[1] / "schemas" / "dashboard-snapshot.schema.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()
    try:
        root = runtime_root(args.project_root)
        state = read_json(root / "state.json")
        validate_file(state, STATE_SCHEMA, "state")
        require_task_index_consistent(root, state)
        tasks = [
            {"task_id": task_id, **summary}
            for task_id, summary in sorted(state.get("tasks", {}).items())
        ]
        active = state.get("active_task_id")
        result = {
            "profile_id": state["profile_id"],
            "task_route": state["task_route"],
            "execution_depth": state["execution_depth"],
            "workflow_decision_hash": state["workflow_decision_hash"],
            "approval": state["approval"],
            "delivery": state["delivery"],
            "subagent_plan": state["subagent_plan"],
            "status": state["status"],
            "tasks": tasks,
            "next_action": f"Inspect active task {active}" if active else "No active task",
        }
        validate_file(result, DASHBOARD_SCHEMA, "dashboard snapshot")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"DASHBOARD_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
