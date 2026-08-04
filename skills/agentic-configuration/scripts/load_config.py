"""Load and validate the central agentic configuration."""

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
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "agentic-config.yaml"
CONFIG_SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "agentic-config.schema.json"
DEPLOYMENT_SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "deployment-config.schema.json"
REQUIRED_SECTIONS = (
    "planning",
    "execution",
    "approval_matrix",
    "runtime",
    "checkpoint",
    "locking",
    "recovery",
    "version_control",
    "documentation",
    "context_budget",
    "security",
    "retention",
)
REQUIRED_AGENTS = (
    "agent-brainstorm",
    "agent-plan-architect",
    "agent-plan-reviewer",
    "agent-explorer",
    "agent-context-builder",
    "agent-executor",
    "agent-review",
    "agent-batch-review",
    "agent-runtime-recovery",
    "agent-dashboard",
    "agent-state-tools",
    "agent-configuration",
)


def _read_data(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError("config is not JSON-compatible YAML and PyYAML is unavailable") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError("agentic config must be an object")
    return value


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def validate_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("agentic config must be an object")
    validate_file(config, CONFIG_SCHEMA, "agentic config")
    schema_version = config.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise ValueError("agentic config schema_version must be 1")
    _require_string(config.get("config_id"), "config_id")
    _require_string(config.get("version"), "version")
    agents = config.get("agents")
    if not isinstance(agents, dict):
        raise ValueError("agents must be an object")
    missing_agents = [agent_id for agent_id in REQUIRED_AGENTS if agent_id not in agents]
    if missing_agents:
        raise ValueError("missing required agents: " + ", ".join(missing_agents))
    policy = config.get("model_policy")
    if not isinstance(policy, dict):
        raise ValueError("model_policy must be an object")
    allowed = policy.get("allowed_model_refs")
    forbidden = policy.get("forbidden_model_refs")
    immutable_forbidden = policy.get("immutable_forbidden_model_refs")
    if not isinstance(allowed, list) or not allowed or any(not isinstance(item, str) or not item.strip() for item in allowed):
        raise ValueError("model_policy.allowed_model_refs must be a non-empty array of strings")
    if not isinstance(forbidden, list) or any(not isinstance(item, str) or not item.strip() for item in forbidden):
        raise ValueError("model_policy.forbidden_model_refs must be an array of strings")
    if not isinstance(immutable_forbidden, list) or any(not isinstance(item, str) or not item.strip() for item in immutable_forbidden):
        raise ValueError("model_policy.immutable_forbidden_model_refs must be an array of strings")
    allowed_set = set(allowed)
    forbidden_set = set(forbidden)
    immutable_set = set(immutable_forbidden)
    if len(allowed) != len(allowed_set) or len(forbidden) != len(forbidden_set) or len(immutable_forbidden) != len(immutable_set):
        raise ValueError("model policy reference lists must not contain duplicates")
    if immutable_set.issubset(allowed_set):
        raise ValueError("immutable forbidden model refs cannot be allowed")
    if not immutable_set.issubset(forbidden_set):
        raise ValueError("model_policy.immutable_forbidden_model_refs must be included in forbidden_model_refs")
    if allowed_set.intersection(forbidden_set):
        raise ValueError("model policy cannot allow and forbid the same model")
    if policy.get("selection_mode") != "role_configured_only":
        raise ValueError("model_policy.selection_mode must be role_configured_only")
    for agent_id, record in agents.items():
        if not isinstance(record, dict):
            raise ValueError(f"agents.{agent_id} must be an object")
        _require_string(record.get("skill"), f"agents.{agent_id}.skill")
        _require_string(record.get("role"), f"agents.{agent_id}.role")
        dispatch_kind = _require_string(record.get("dispatch_kind"), f"agents.{agent_id}.dispatch_kind")
        model_ref = record.get("model_ref")
        if dispatch_kind == "model":
            model_ref = _require_string(model_ref, f"agents.{agent_id}.model_ref")
            if model_ref not in allowed_set or model_ref in forbidden_set:
                raise ValueError(f"agents.{agent_id}.model_ref is not allowed by model_policy")
        elif dispatch_kind in {"script", "primary"}:
            if model_ref is not None or "model_dispatch" in record:
                raise ValueError(f"agents.{agent_id}.model_ref must be absent for {dispatch_kind} dispatch")
        else:
            raise ValueError(f"agents.{agent_id}.dispatch_kind is unsupported: {dispatch_kind}")
        for field in ("capabilities", "forbidden"):
            value = record.get(field)
            if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"agents.{agent_id}.{field} must be an array of strings")
    for section in REQUIRED_SECTIONS:
        if not isinstance(config.get(section), dict):
            raise ValueError(f"{section} must be an object")
    return config


def resolve_config_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_CONFIG


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    resolved = resolve_config_path(path)
    try:
        config = _read_data(resolved)
    except OSError as exc:
        raise ValueError(f"agentic config is unreadable: {resolved}") from exc
    validate_config(config)
    return config


def resolve_deployment_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    override = os.environ.get(DEPLOYMENT_ENV)
    if not override:
        raise ValueError(f"{DEPLOYMENT_ENV} is required to resolve provider model IDs")
    return Path(override).expanduser().resolve()


def load_deployment_config(path: str | Path | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    base = load_config() if config is None else validate_config(config)
    resolved = resolve_deployment_path(path)
    try:
        deployment = _read_data(resolved)
    except OSError as exc:
        raise ValueError(f"deployment config is unreadable: {resolved}") from exc
    validate_file(deployment, DEPLOYMENT_SCHEMA, "deployment config")
    model_ids = deployment.get("model_ids")
    if not isinstance(model_ids, dict):
        raise ValueError("deployment.model_ids must be an object")
    policy = base["model_policy"]
    required_refs = set(policy["allowed_model_refs"]) | set(policy["forbidden_model_refs"])
    actual_refs = set(model_ids)
    if actual_refs != required_refs:
        missing = sorted(required_refs - actual_refs)
        extra = sorted(actual_refs - required_refs)
        raise ValueError(f"deployment model refs mismatch; missing={missing}, extra={extra}")
    values = []
    for ref in sorted(required_refs):
        value = model_ids.get(ref)
        value = _require_string(value, f"deployment.model_ids.{ref}")
        if value.startswith("<") and value.endswith(">"):
            raise ValueError(f"deployment.model_ids.{ref} is a placeholder")
        values.append(value)
    if len(values) != len(set(values)):
        raise ValueError("deployment model IDs must be unique")
    return deployment


def resolve_agent(config: dict[str, Any], agent_id: str, deployment: dict[str, Any] | None = None) -> dict[str, Any]:
    validated = validate_config(config)
    deployment = load_deployment_config(config=validated) if deployment is None else deployment
    agents = validated["agents"]
    record = agents.get(agent_id)
    if not isinstance(record, dict):
        raise ValueError(f"agent is not configured: {agent_id}")
    if record.get("dispatch_kind") != "model":
        raise ValueError(f"agent is not a model agent: {agent_id}")
    model_ref = _require_string(record.get("model_ref"), f"agents.{agent_id}.model_ref")
    if model_ref not in set(validated["model_policy"]["allowed_model_refs"]):
        raise ValueError(f"agent model ref is not allowed: {agent_id}")
    model_ids = deployment.get("model_ids")
    if not isinstance(model_ids, dict) or model_ref not in model_ids:
        raise ValueError(f"deployment does not resolve agent model ref: {model_ref}")
    resolved = dict(record)
    resolved["model_dispatch"] = _require_string(model_ids[model_ref], f"deployment.model_ids.{model_ref}")
    return resolved


def validate_dispatch_selection(dispatch: Any, config: dict[str, Any], deployment: dict[str, Any] | None = None) -> None:
    if not isinstance(dispatch, dict):
        raise ValueError("dispatch must be an object")
    agent_role = _require_string(dispatch.get("agent_role"), "dispatch.agent_role")
    selected_model = _require_string(dispatch.get("selected_model"), "dispatch.selected_model")
    record = resolve_agent(config, agent_role, deployment)
    if selected_model != record["model_dispatch"]:
        raise ValueError(f"dispatch.selected_model does not match {agent_role}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path")
    parser.add_argument("--deployment")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        config = load_config(args.path)
        if args.deployment:
            load_deployment_config(args.deployment, config)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"CONFIG_INVALID: {exc}", file=sys.stderr)
        return 1
    if args.check:
        print("CONFIG_VALID")
    else:
        print(json.dumps(config, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
