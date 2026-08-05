"""Resolve and validate the deterministic nested skill-routing artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from risk_flags import normalize_risk_flags
from validate_payload import validate


SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "skill-routing.schema.json"
DEFAULT_POLICY_VERSION = "1"
_MODEL_ID_MARKERS = ("provider.", "openai/", "anthropic/", "google/", "model_dispatch")


def _text(value: Any, field: str, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _skill_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        raise ValueError(f"{field} must be an array of skill names")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must contain non-empty strings")
        name = item.strip()
        if name not in result:
            result.append(name)
    return result


def _routing_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if config is None:
        return {
            "policy_version": DEFAULT_POLICY_VERSION,
            "one_percent_rule": False,
            "available_skills": [
                "agentic-brainstorm-facilitator",
                "agentic-engineering-core",
                "agentic-engineering-wiki",
                "agentic-explorer",
                "agentic-implementer",
                "agentic-plan-architect",
                "agentic-state-tools",
                "agentic-systematic-debugging",
                "agentic-verification-before-completion",
            ],
            "process_skills": {
                "brainstorming": "agentic-brainstorm-facilitator",
                "debugging": "agentic-systematic-debugging",
                "planning": "agentic-plan-architect",
                "verification": "agentic-verification-before-completion",
            },
            "role_skills": {
                "agent-brainstorm": "agentic-brainstorm-facilitator",
                "agent-executor": "agentic-implementer",
                "agent-explorer": "agentic-explorer",
                "agent-plan-architect": "agentic-plan-architect",
                "agent-review": "agentic-task-reviewer",
            },
            "domain_skills": {},
        }
    section = config.get("skill_routing")
    if section is None:
        return _routing_config(None)
    if not isinstance(section, dict):
        raise ValueError("skill_routing must be an object")
    return section


def _canonical_role(requested_role: str, role_skills: dict[str, Any]) -> str:
    aliases = {
        "implementer": "agent-executor",
        "executor": "agent-executor",
        "reviewer": "agent-review",
        "task_reviewer": "agent-review",
        "explorer": "agent-explorer",
        "plan_architect": "agent-plan-architect",
        "brainstorm_facilitator": "agent-brainstorm",
    }
    return aliases.get(requested_role, requested_role) if requested_role not in role_skills else requested_role


def _truthy_risk(risk_flags: dict[str, bool]) -> bool:
    return any(value is True for value in risk_flags.values())


def _processes(
    intent: str,
    state: str,
    task_type: str,
    repair: bool,
    risk_flags: dict[str, bool],
    profile: str,
    process_skills: dict[str, Any],
) -> tuple[list[str], list[str]]:
    intent_key = intent.lower().replace("-", "_").replace(" ", "_")
    state_key = state.upper().replace("-", "_").replace(" ", "_")
    task_key = task_type.lower().replace("-", "_").replace(" ", "_")
    selected: list[str] = []
    reasons: list[str] = []

    def add(name: str, reason: str) -> None:
        skill = process_skills.get(name)
        if isinstance(skill, str) and skill.strip() and skill.strip() not in selected:
            selected.append(skill.strip())
            reasons.append(reason)

    bug_intents = {"bug", "defect", "failure", "failing_behavior", "debug", "repair", "regression"}
    if repair or state_key in {"REPAIR_REQUIRED", "FAILED", "BLOCKED"} or intent_key in bug_intents:
        add("debugging", "repair, failure, or defect signals require root-cause debugging")

    ambiguous = {"ambiguous", "unclear", "exploration", "idea", "feature_request"}
    if intent_key in ambiguous:
        add("brainstorming", "ambiguous intent requires clarification before planning")

    if state_key in {"PLANNING", "PLAN_REQUIRED"} or task_key in {"planning", "architecture", "design"}:
        add("planning", "planning state or task type requires a planning process")

    strict_profiles = {"production", "high_risk"}
    if (
        state_key in {"COMPLETED", "VERIFYING", "REVIEWING"}
        or intent_key in {"completion", "verify", "verification", "release"}
        or profile in strict_profiles
        or _truthy_risk(risk_flags)
    ):
        add("verification", "completion, strict profile, or risk signals require fresh verification")

    return selected, reasons


def _routing_id(inputs: dict[str, Any]) -> str:
    canonical = json.dumps(inputs, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "ROUTE-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def resolve_skill_route(
    request: dict[str, Any] | None = None,
    *,
    intent_classification: str | None = None,
    current_state: str | None = None,
    task_type: str | None = None,
    repair: bool = False,
    risk_flags: dict[str, bool] | None = None,
    project_profile: str | None = None,
    requested_role: str | None = None,
    configured_skills: Iterable[str] | None = None,
    loaded_skills: Iterable[str] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve process -> role -> domain routing with deterministic precedence."""
    payload = dict(request or {})
    intent = _text(payload.get("intent_classification", intent_classification), "intent_classification", "unspecified")
    state = _text(payload.get("current_state", current_state), "current_state", "UNSPECIFIED")
    task = _text(payload.get("task_type", task_type), "task_type", "standard")
    is_repair = payload.get("repair", repair)
    if not isinstance(is_repair, bool):
        raise ValueError("repair must be boolean")
    flags = normalize_risk_flags(payload.get("risk_flags", risk_flags or {}))
    profile = _text(payload.get("project_profile", project_profile), "project_profile", "personal")
    role = _text(payload.get("requested_role", requested_role), "requested_role", "agent-executor")
    route_config = _routing_config(config)
    policy_version = _text(route_config.get("policy_version"), "skill_routing.policy_version", DEFAULT_POLICY_VERSION)
    if route_config.get("one_percent_rule") is not False:
        raise ValueError("skill routing must explicitly disable the probabilistic 1% rule")

    configured_input = configured_skills if configured_skills is not None else payload.get("configured_skills")
    available = _skill_list(
        configured_input if configured_input is not None else route_config.get("available_skills", []),
        "configured_skills",
    )
    process_map = route_config.get("process_skills", {})
    role_map = route_config.get("role_skills", {})
    domain_map = route_config.get("domain_skills", {})
    if not isinstance(process_map, dict) or not isinstance(role_map, dict) or not isinstance(domain_map, dict):
        raise ValueError("skill routing process_skills, role_skills, and domain_skills must be objects")
    canonical_role = _canonical_role(role, role_map)
    process, reasons = _processes(intent, state, task, is_repair, flags, profile, process_map)
    role_skill = role_map.get(canonical_role, role_map.get(role))
    if role_skill is None:
        raise ValueError(f"requested role has no configured skill: {role}")
    role_skill = _text(role_skill, f"role_skills.{canonical_role}")
    domain_skill = domain_map.get(task)
    if domain_skill is None:
        domain_skill = domain_map.get(task.lower())
    if domain_skill is not None:
        domain_skill = _text(domain_skill, f"domain_skills.{task}")
    applicable = [*process, role_skill, *([] if domain_skill is None else [domain_skill])]
    required = list(applicable)
    loaded_input = loaded_skills if loaded_skills is not None else payload.get("loaded_skills")
    if loaded_input is None:
        loaded = list(required)
    else:
        loaded = _skill_list(loaded_input, "loaded_skills")
    if available:
        unknown = sorted(set(applicable) - set(available))
        if unknown:
            raise ValueError("routing selected skills not present in configured_skills: " + ", ".join(unknown))
    route_inputs = {
        "intent_classification": intent,
        "current_state": state,
        "task_type": task,
        "repair": is_repair,
        "risk_flags": flags,
        "project_profile": profile,
        "requested_role": role,
        "configured_skills": available,
    }
    route = {
        "routing_id": _routing_id(route_inputs),
        "intent_classification": intent,
        "task_type": task,
        "current_state": state,
        "repair": is_repair,
        "project_profile": profile,
        "requested_role": role,
        "risk_flags": flags,
        "applicable_skills": applicable,
        "required_skills": required,
        "loaded_skills": loaded,
        "routing_reason": "; ".join(reasons + [f"role {role} selects {role_skill}"]),
        "routing_policy_version": policy_version,
    }
    validate_skill_route(route, configured_skills=available or None)
    return route


def validate_skill_route(route: Any, *, configured_skills: Iterable[str] | None = None) -> dict[str, Any]:
    if not isinstance(route, dict):
        raise ValueError("skill_route must be an object")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = validate(route, schema, base_path=SCHEMA.parent)
    if errors:
        raise ValueError("skill routing schema validation failed: " + "; ".join(errors))
    if route.get("routing_policy_version") != DEFAULT_POLICY_VERSION:
        raise ValueError("unsupported skill routing policy version")
    if route.get("one_percent_rule") is not None:
        raise ValueError("skill route cannot carry probabilistic routing controls")
    for field in ("applicable_skills", "required_skills", "loaded_skills"):
        for skill in route[field]:
            if any(marker in skill.lower() for marker in _MODEL_ID_MARKERS):
                raise ValueError(f"skill route {field} cannot contain provider model IDs")
    applicable = route["applicable_skills"]
    required = route["required_skills"]
    loaded = set(route["loaded_skills"])
    if not set(required).issubset(set(applicable)):
        raise ValueError("required_skills must be a subset of applicable_skills")
    missing = [skill for skill in required if skill not in loaded]
    if missing:
        raise ValueError("mandatory skill(s) not loaded: " + ", ".join(missing))
    if configured_skills is not None:
        configured = set(_skill_list(configured_skills, "configured_skills"))
        unknown = sorted(set(applicable) - configured)
        if unknown:
            raise ValueError("route contains skills unavailable in configuration: " + ", ".join(unknown))
    return dict(route)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        value = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = resolve_skill_route(value)
        if args.output:
            Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"SKILL_ROUTE_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
