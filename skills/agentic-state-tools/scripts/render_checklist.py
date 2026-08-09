"""Render a compact human-readable progress view from validated runtime state."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
CONFIG_SCRIPTS = HERE.parents[2] / "agentic-configuration" / "scripts"
sys.path.insert(0, str(CONFIG_SCRIPTS))
from schema_validation import validate_file  # noqa: E402
from runtime_utils import (  # noqa: E402
    append_event,
    read_json,
    require_task_index_consistent,
    runtime_root,
    safe_child,
    sanitize_for_persistence,
    task_state_path,
    validate_task_id,
    write_text_atomic,
)

STATE_SCHEMA = HERE.parents[1] / "schemas" / "state.schema.json"
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _inline(value: Any) -> str:
    """Keep runtime values on one safe Markdown line."""
    safe = sanitize_for_persistence(str(value))
    return str(safe).replace("`", "\\`").replace("\r", " ").replace("\n", " ").strip()


def _identifier(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if IDENTIFIER_RE.fullmatch(result) is None:
        raise ValueError(f"{label} must be a simple identifier")
    return result


def _stages(state: dict[str, Any]) -> list[dict[str, str]]:
    raw = state.get("stages", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("state stages must be an array")
    result: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"state stages[{index}] must be an object")
        stage_id = _identifier(item.get("id"), f"state stages[{index}].id")
        owner = str(item.get("owner", "")).strip()
        output = str(item.get("output", "")).strip()
        if not owner or not output:
            raise ValueError(f"state stages[{index}] must include owner and output")
        result.append({"id": stage_id, "owner": owner, "output": output})
    if len({item["id"] for item in result}) != len(result):
        raise ValueError("state stage IDs must be unique")
    return result


def _fallback_workflow_plan(state: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    """Recover the display plan for runtimes created before plan fields were persisted."""
    contract = state.get("request_contract")
    if not isinstance(contract, dict):
        return [], []
    try:
        from load_config import load_config  # noqa: PLC0415
        from resolve_workflow import resolve_workflow  # noqa: PLC0415

        decision = resolve_workflow(
            {
                "profile": state["profile_id"],
                "task_route": state["task_route"],
                **contract,
            },
            load_config(),
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return [], []
    if decision.get("decision_hash") != state.get("workflow_decision_hash"):
        return [], []
    return decision.get("required_skills", []), decision.get("stages", [])


def _last_stage_event(
    root: Path,
    state: dict[str, Any],
    stages: list[dict[str, str]],
    task_id: str | None = None,
) -> dict[str, str]:
    events_path = safe_child(root, "events.jsonl")
    if not events_path.is_file():
        return {}
    stage_ids = {item["id"] for item in stages}
    latest: dict[str, str] = {}
    for line in events_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event_type") != "WORKFLOW_STAGE_UPDATED":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("workflow_decision_hash") != state.get("workflow_decision_hash"):
            continue
        try:
            event_task_id = validate_task_id(payload.get("task_id"))
        except ValueError:
            continue
        if event_task_id not in state.get("tasks", {}):
            continue
        if task_id is not None and event_task_id != task_id:
            continue
        try:
            stage = _identifier(payload.get("stage"), "event stage")
            skill = _identifier(payload.get("skill"), "event skill")
        except ValueError:
            continue
        if stage_ids and stage not in stage_ids:
            continue
        latest = {"task_id": event_task_id, "current_stage": stage, "current_skill": skill}
    return latest


def _select_task_id(
    root: Path,
    state: dict[str, Any],
    stages: list[dict[str, str]],
    task_id: str | None,
) -> str:
    if task_id is not None:
        selected = validate_task_id(task_id)
        if selected not in state.get("tasks", {}):
            raise ValueError(f"task_id is not recorded in the runtime: {selected}")
        return selected

    active_task_id = state.get("active_task_id")
    if active_task_id is not None:
        selected = validate_task_id(active_task_id)
        if selected not in state.get("tasks", {}):
            raise ValueError(f"active task is not recorded in the runtime: {selected}")
        return selected

    latest = _last_stage_event(root, state, stages)
    if latest:
        return latest["task_id"]
    raise ValueError("no task can be selected for the checklist")


def _resolve_progress(
    project_root: str | Path,
    root: Path,
    state: dict[str, Any],
    stages: list[dict[str, str]],
    task_id: str,
    current_stage: str | None,
    current_skill: str | None,
) -> dict[str, str]:
    explicit = current_stage is not None or current_skill is not None
    if explicit and (current_stage is None or current_skill is None):
        raise ValueError("current_stage and current_skill must be provided together")
    if explicit:
        stage = _identifier(current_stage, "current_stage")
        skill = _identifier(current_skill, "current_skill")
        if stages and stage not in {item["id"] for item in stages}:
            raise ValueError(f"current_stage is not present in the workflow: {stage}")
        append_event(
            project_root,
            "WORKFLOW_STAGE_UPDATED",
            {
                "task_id": task_id,
                "stage": stage,
                "skill": skill,
                "workflow_decision_hash": state["workflow_decision_hash"],
            },
        )
        return {"current_stage": stage, "current_skill": skill}
    return _last_stage_event(root, state, stages, task_id)


def _owner_label(owner: str) -> str:
    return "Primary Agent" if owner == "primary" else f"`{_inline(owner)}`"


def render_checklist(
    project_root: str | Path,
    *,
    task_id: str | None = None,
    current_stage: str | None = None,
    current_skill: str | None = None,
) -> str:
    root = runtime_root(project_root)
    state = read_json(root / "state.json")
    validate_file(state, STATE_SCHEMA, "state")
    require_task_index_consistent(root, state)
    stages = _stages(state)
    required_skills = state.get("required_skills", [])
    if not stages or not required_skills:
        fallback_skills, fallback_stages = _fallback_workflow_plan(state)
        required_skills = required_skills or fallback_skills
        stages = stages or _stages({"stages": fallback_stages})
    selected_task_id = _select_task_id(root, state, stages, task_id)
    progress = _resolve_progress(
        project_root,
        root,
        state,
        stages,
        selected_task_id,
        current_stage,
        current_skill,
    )
    selected_task = state.get("tasks", {}).get(selected_task_id)
    if not isinstance(selected_task, dict):
        raise ValueError(f"selected task is not recorded in the runtime: {selected_task_id}")

    lines = [
        "# Agent progress",
        "",
        f"- Status: `{_inline(state['status'])}`",
        f"- Route: `{_inline(state['task_route'])}`",
        f"- Depth: `{_inline(state['execution_depth'])}`",
        f"- Current stage: `{_inline(progress.get('current_stage', 'unknown'))}`",
        f"- Current skill: `{_inline(progress.get('current_skill', 'unknown'))}`",
        f"- Task: `{_inline(selected_task_id)}`",
        f"- Updated: `{_inline(state.get('updated_at', 'unknown'))}`",
        f"- Task status: `{_inline(selected_task.get('status', 'unknown'))}`",
        f"- Task summary: `{_inline(selected_task.get('summary', ''))}`",
    ]

    detail: dict[str, Any] = {}
    try:
        detail = read_json(task_state_path(root, selected_task_id))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        detail = {}
    scope = ", ".join(_inline(item) for item in detail.get("scope", []))
    lines.extend(
        [
            "",
            "## Task detail",
            "",
            "| Task | Status | Plan task | Scope | Updated |",
            "|---|---|---|---|---|",
        ]
    )
    lines.append(
        f"| `{_inline(selected_task_id)}` | "
        f"`{_inline(detail.get('status') or selected_task.get('status') or '')}` | "
        f"`{_inline(detail.get('plan_task_id', ''))}` | {scope} | "
        f"`{_inline(detail.get('updated_at', ''))}` |"
    )

    lines.extend(["", "## Workflow stages", "Checkboxes mean reached, not completion."])
    current_id = progress.get("current_stage")
    current_index = next(
        (index for index, item in enumerate(stages) if item["id"] == current_id),
        None,
    )
    if stages:
        if current_index is not None:
            lines.append(f"Position: {current_index + 1}/{len(stages)}")
        for index, stage in enumerate(stages):
            current = " **CURRENT**" if index == current_index else ""
            mark = "x" if current_index is not None and index <= current_index else " "
            lines.append(
                f"- [{mark}]{current} `{_inline(stage['id'])}` - "
                f"{_owner_label(stage['owner'])}"
            )
    else:
        lines.append("- Workflow stages are not recorded in this runtime.")

    if isinstance(required_skills, list) and required_skills:
        lines.extend(["", "## Selected skills"])
        for skill in required_skills:
            lines.append(f"- `{_inline(skill)}`")

    text = "\n".join(lines) + "\n"
    checklist_dir = safe_child(root, "checklist")
    checklist_dir.mkdir(parents=True, exist_ok=True)
    filename = f"task-checklist-{validate_task_id(selected_task_id)}.md"
    write_text_atomic(safe_child(checklist_dir, filename), text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument(
        "--task-id",
        help="task to render; defaults to the active task or latest valid task-bound marker",
    )
    parser.add_argument(
        "--current-stage",
        help="last workflow stage reached; records a stage event",
    )
    parser.add_argument(
        "--current-skill",
        help="skill handling the current stage; records a stage event",
    )
    args = parser.parse_args()
    try:
        text = render_checklist(
            args.project_root,
            task_id=args.task_id,
            current_stage=args.current_stage,
            current_skill=args.current_skill,
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"CHECKLIST_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
