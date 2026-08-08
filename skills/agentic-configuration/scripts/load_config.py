"""Load the central lean workflow configuration."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from schema_validation import validate_file

CONFIG_ENV = "AGENTIC_CONFIG_FILE"
DEPLOYMENT_ENV = "AGENTIC_DEPLOYMENT_CONFIG"
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "agentic-config.json"
CONFIG_SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "agentic-config.schema.json"
DEPLOYMENT_SCHEMA = (
    Path(__file__).resolve().parents[1] / "schemas" / "deployment-config.schema.json"
)
REQUIRED_AGENTS = {
    "agent-brainstorm",
    "agent-plan-architect",
    "agent-explorer",
    "agent-executor",
    "agent-independent-reviewer",
    "agent-runtime-recovery",
    "agent-state-tools",
    "agent-skill-authoring",
    "agent-debugger",
    "agent-verifier",
}
REQUIRED_PROCESS_ROUTES = {"core", "debug", "verify"}
REQUIRED_ROLE_ROUTES = {
    "brainstorm",
    "plan",
    "plan_review",
    "explore",
    "implement",
    "review",
    "batch_review",
    "recovery",
    "delivery",
    "configuration",
    "skill_authoring",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _validate_required_companions(
    routing: dict[str, Any], skills_root: Path
) -> None:
    companions = routing.get("required_companion_skills")
    if not isinstance(companions, list) or not companions:
        raise ValueError("skill_routing.required_companion_skills must be non-empty")

    core_skill = routing.get("process_skills", {}).get("core")
    seen: set[str] = set()
    for index, companion in enumerate(companions):
        if not isinstance(companion, str) or not companion.strip():
            raise ValueError(
                f"skill_routing.required_companion_skills[{index}] must be a non-empty string"
            )
        if companion != companion.strip() or any(
            separator in companion for separator in ("/", "\\")
        ):
            raise ValueError(
                f"skill_routing.required_companion_skills[{index}] must be a package name"
            )
        if companion in seen:
            raise ValueError(
                "skill_routing.required_companion_skills must not contain duplicates"
            )
        seen.add(companion)
        if companion == core_skill:
            raise ValueError(
                "skill_routing.required_companion_skills must not include the Primary skill"
            )

        skill_path = (skills_root / companion / "SKILL.md").resolve()
        if skills_root not in skill_path.parents or not skill_path.is_file():
            raise ValueError(
                "skill_routing.required_companion_skills references a missing package skill: "
                + companion
            )


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    validate_file(config, CONFIG_SCHEMA, "agentic config")

    default_profile = config["default_profile"]
    if (
        not isinstance(default_profile, str)
        or not default_profile
        or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_" for ch in default_profile)
    ):
        raise ValueError("default_profile must be a lowercase profile id")
    profile_path = (
        Path(__file__).resolve().parents[2]
        / "agentic-state-tools"
        / "profiles"
        / f"{default_profile}.json"
    )
    if not profile_path.is_file():
        raise ValueError(f"default_profile does not exist: {default_profile}")

    missing = sorted(REQUIRED_AGENTS - set(config["agents"]))
    if missing:
        raise ValueError("missing agents: " + ", ".join(missing))

    allowed = config["model_policy"].get("allowed_model_refs")
    if not isinstance(allowed, list) or not allowed:
        raise ValueError("model_policy.allowed_model_refs must be non-empty")

    skills_root = Path(__file__).resolve().parents[2]
    for agent_id, record in config["agents"].items():
        if not isinstance(record, dict):
            raise ValueError(f"agents.{agent_id} must be an object")
        kind = record.get("dispatch_kind")
        if kind == "model" and record.get("model_ref") not in allowed:
            raise ValueError(f"agents.{agent_id}.model_ref is not allowed")
        if kind not in {"model", "script", "primary"}:
            raise ValueError(f"agents.{agent_id}.dispatch_kind is unsupported")
        if kind == "model":
            prompt_path = record.get("prompt_path")
            if not isinstance(prompt_path, str) or not prompt_path.strip():
                raise ValueError(f"agents.{agent_id}.prompt_path is required")
            prompt = (skills_root / prompt_path).resolve()
            if skills_root not in prompt.parents or not prompt.is_file():
                raise ValueError(f"agents.{agent_id}.prompt_path is invalid: {prompt_path}")
            if record.get("fresh_context") is not True:
                raise ValueError(f"agents.{agent_id}.fresh_context must be true")
            if not isinstance(record.get("parallel_safe"), bool):
                raise ValueError(f"agents.{agent_id}.parallel_safe must be boolean")
            editing_capabilities = {"repository_editing", "skill_editing"}
            if editing_capabilities & set(record.get("capabilities", [])) and record.get("parallel_safe"):
                raise ValueError(
                    f"agents.{agent_id}.parallel_safe must be false for a writer in the single-active-task runtime"
                )

    routing = config["skill_routing"]
    process_routes = routing.get("process_skills", {})
    role_routes = routing.get("role_skills", {})
    _validate_required_companions(routing, skills_root)
    missing_process = sorted(REQUIRED_PROCESS_ROUTES - set(process_routes))
    missing_roles = sorted(REQUIRED_ROLE_ROUTES - set(role_routes))
    if missing_process or missing_roles:
        raise ValueError(
            "missing skill routes: "
            + ", ".join(missing_process + missing_roles)
        )

    depth_order = config["workflow"]["depth_order"]
    if depth_order != ["focused", "standard", "controlled"]:
        raise ValueError("workflow.depth_order must be focused, standard, controlled")

    routes = routing.get("task_routes")
    if not isinstance(routes, dict) or not routes:
        raise ValueError("skill_routing.task_routes must be a non-empty object")
    valid_tokens = set(process_routes) | set(role_routes)
    required_route_fields = {
        "description", "source_editing", "default_depth", "state_mode",
        "clarify_on_unclear", "reviewable", "batch_reviewable", "sequences"
    }
    for route_id, route in routes.items():
        if not isinstance(route_id, str) or not route_id or any(
            ch not in "abcdefghijklmnopqrstuvwxyz0123456789_" for ch in route_id
        ):
            raise ValueError(f"invalid task route id: {route_id}")
        if not isinstance(route, dict):
            raise ValueError(f"task_routes.{route_id} must be an object")
        missing_fields = sorted(required_route_fields - set(route))
        if missing_fields:
            raise ValueError(
                f"task_routes.{route_id} missing fields: " + ", ".join(missing_fields)
            )
        if not isinstance(route["description"], str) or not route["description"].strip():
            raise ValueError(f"task_routes.{route_id}.description must be non-empty")
        for field in ("source_editing", "clarify_on_unclear", "reviewable", "batch_reviewable"):
            if not isinstance(route[field], bool):
                raise ValueError(f"task_routes.{route_id}.{field} must be boolean")
        if route["default_depth"] not in depth_order:
            raise ValueError(f"task_routes.{route_id}.default_depth is invalid")
        if route["state_mode"] not in {"inherit", "off", "optional", "required"}:
            raise ValueError(f"task_routes.{route_id}.state_mode is invalid")
        sequences = route["sequences"]
        if not isinstance(sequences, dict) or set(sequences) != set(depth_order):
            raise ValueError(
                f"task_routes.{route_id}.sequences must define every execution depth"
            )
        for depth, tokens in sequences.items():
            if not isinstance(tokens, list) or not tokens:
                raise ValueError(f"task_routes.{route_id}.sequences.{depth} must be non-empty")
            if len(tokens) != len(set(tokens)):
                raise ValueError(
                    f"task_routes.{route_id}.sequences.{depth} must not contain duplicates"
                )
            unknown_tokens = sorted(set(tokens) - valid_tokens)
            if unknown_tokens:
                raise ValueError(
                    f"task_routes.{route_id}.sequences.{depth} has unknown tokens: "
                    + ", ".join(unknown_tokens)
                )

            editing_tokens = {"implement", "configuration", "skill_authoring"}
            edits = [token for token in tokens if token in editing_tokens]
            if not route["source_editing"] and edits:
                raise ValueError(
                    f"task_routes.{route_id}.sequences.{depth} is read-only but contains: "
                    + ", ".join(edits)
                )
            if route["source_editing"]:
                if len(edits) != 1:
                    raise ValueError(
                        f"task_routes.{route_id}.sequences.{depth} must contain exactly one editing token"
                    )
                edit_index = tokens.index(edits[0])
                if "verify" not in tokens or tokens.index("verify") < edit_index:
                    raise ValueError(
                        f"task_routes.{route_id}.sequences.{depth} must verify after editing"
                    )
                if depth == "controlled" and "review" not in tokens:
                    raise ValueError(
                        f"task_routes.{route_id}.sequences.controlled must include review"
                    )
                if "review" in tokens:
                    review_index = tokens.index("review")
                    if review_index < edit_index or review_index > tokens.index("verify"):
                        raise ValueError(
                            f"task_routes.{route_id}.sequences.{depth} must review after editing and before verification"
                        )
                if "batch_review" in tokens:
                    batch_index = tokens.index("batch_review")
                    if batch_index < edit_index or batch_index > tokens.index("verify"):
                        raise ValueError(
                            f"task_routes.{route_id}.sequences.{depth} must batch-review after editing and before verification"
                        )
                    if "review" in tokens and batch_index < tokens.index("review"):
                        raise ValueError(
                            f"task_routes.{route_id}.sequences.{depth} must batch-review after task review"
                        )
            if route_id == "debug" and edits:
                if "debug" not in tokens or tokens.index("debug") > tokens.index(edits[0]):
                    raise ValueError(
                        f"task_routes.debug.sequences.{depth} must debug before editing"
                    )
            if "review" in tokens and "verify" in tokens and tokens.index("review") > tokens.index("verify"):
                raise ValueError(
                    f"task_routes.{route_id}.sequences.{depth} must review before verification"
                )
            if "batch_review" in tokens:
                if "verify" in tokens and tokens.index("batch_review") > tokens.index("verify"):
                    raise ValueError(
                        f"task_routes.{route_id}.sequences.{depth} must batch-review before verification"
                    )
                if "review" in tokens and tokens.index("batch_review") < tokens.index("review"):
                    raise ValueError(
                        f"task_routes.{route_id}.sequences.{depth} must batch-review after task review"
                    )
            if route_id == "delivery":
                if "delivery" not in tokens:
                    raise ValueError(
                        f"task_routes.delivery.sequences.{depth} must include delivery"
                    )
                if "verify" not in tokens or tokens.index("verify") > tokens.index("delivery"):
                    raise ValueError(
                        f"task_routes.delivery.sequences.{depth} must verify before delivery"
                    )

    subagents = config["subagent_policy"]
    if subagents["primary_skill"] != process_routes["core"]:
        raise ValueError("subagent_policy.primary_skill must match process_skills.core")
    wait = subagents["wait"]
    if wait["check_interval_seconds"] >= wait["timeout_seconds"]:
        raise ValueError(
            "subagent_policy.wait.check_interval_seconds must be shorter than timeout_seconds"
        )
    previous_active = previous_total = previous_writers = -1
    for depth in depth_order:
        limits = subagents["depths"][depth]
        if limits["max_active"] > limits["max_total"]:
            raise ValueError(f"subagent_policy.depths.{depth}.max_active exceeds max_total")
        if limits["max_parallel_writers"] > limits["max_active"]:
            raise ValueError(f"subagent_policy.depths.{depth}.max_parallel_writers exceeds max_active")
        if limits["max_parallel_writers"] != 1:
            raise ValueError(
                f"subagent_policy.depths.{depth}.max_parallel_writers must be 1 for the single-active-task runtime"
            )
        if limits["max_active"] < previous_active or limits["max_total"] < previous_total or limits["max_parallel_writers"] < previous_writers:
            raise ValueError("subagent limits must not decrease with execution depth")
        previous_active = limits["max_active"]
        previous_total = limits["max_total"]
        previous_writers = limits["max_parallel_writers"]
    dispatchable = set(subagents["dispatchable_stages"])
    unknown_dispatchable = sorted(dispatchable - valid_tokens)
    if unknown_dispatchable:
        raise ValueError("unknown dispatchable stages: " + ", ".join(unknown_dispatchable))

    approval_matrix = config["approval_matrix"]
    workflow = config["workflow"]
    known_flags = set(workflow["high_risk_flags"]) | set(workflow["standard_flags"])
    risk_approval_map = workflow["risk_approval_map"]
    unknown_risk_keys = sorted(set(risk_approval_map) - known_flags)
    if unknown_risk_keys:
        raise ValueError(
            "workflow.risk_approval_map has unknown risk flags: "
            + ", ".join(unknown_risk_keys)
        )
    unknown_approval_keys = sorted(set(risk_approval_map.values()) - set(approval_matrix))
    if unknown_approval_keys:
        raise ValueError(
            "workflow.risk_approval_map targets unknown approval keys: "
            + ", ".join(unknown_approval_keys)
        )
    for action_id, action in config["delivery_actions"].items():
        if action["approval_key"] not in approval_matrix:
            raise ValueError(
                f"delivery_actions.{action_id}.approval_key is not in approval_matrix"
            )
    if workflow["focused_max_files"] > workflow["standard_max_files"]:
        raise ValueError("workflow focused file limit must not exceed standard limit")
    budgets = config["context_budget"]
    if not (
        budgets["focused_max_files"]
        <= budgets["standard_max_files"]
        <= budgets["controlled_max_files"]
    ):
        raise ValueError("context file budgets must increase with execution depth")

    legacy_routes = config["workflow"]["legacy_change_type_routes"]
    if not isinstance(legacy_routes, dict):
        raise ValueError("workflow.legacy_change_type_routes must be an object")
    unknown_legacy_targets = sorted(set(legacy_routes.values()) - set(routes))
    if unknown_legacy_targets:
        raise ValueError(
            "legacy change types target unknown routes: " + ", ".join(unknown_legacy_targets)
        )
    return config


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    resolved = Path(path or os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG).expanduser().resolve()
    return validate_config(_read(resolved))


def load_deployment_config(
    path: str | Path | None = None, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    base = config or load_config()
    raw_path = path or os.environ.get(DEPLOYMENT_ENV)
    if not raw_path:
        raise ValueError(
            f"{DEPLOYMENT_ENV} is required only when provider model IDs are needed"
        )
    deployment = _read(Path(raw_path).expanduser().resolve())
    validate_file(deployment, DEPLOYMENT_SCHEMA, "deployment config")
    required = set(base["model_policy"]["allowed_model_refs"])
    actual = set(deployment.get("model_ids", {}))
    if required != actual:
        raise ValueError(
            f"deployment refs mismatch; missing={sorted(required-actual)}, extra={sorted(actual-required)}"
        )
    for ref, value in deployment["model_ids"].items():
        if (
            not isinstance(value, str)
            or not value.strip()
            or (value.startswith("<") and value.endswith(">"))
        ):
            raise ValueError(f"deployment.model_ids.{ref} is unresolved")
    return deployment


def resolve_agent(
    config: dict[str, Any], agent_id: str, deployment: dict[str, Any] | None = None
) -> dict[str, Any]:
    record = config["agents"].get(agent_id)
    if not isinstance(record, dict):
        raise ValueError(f"unknown agent: {agent_id}")
    result = dict(record)
    if record.get("dispatch_kind") == "model" and deployment is not None:
        result["model_dispatch"] = deployment["model_ids"][record["model_ref"]]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--deployment")
    parser.add_argument("--agent")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        result: Any = config
        deployment = None
        if args.deployment:
            deployment = load_deployment_config(args.deployment, config)
            result = deployment
        if args.agent:
            result = resolve_agent(config, args.agent, deployment)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"CONFIG_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(
        "CONFIG_VALID"
        if args.check and not args.agent and not args.deployment
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
