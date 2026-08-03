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
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "agentic-config.yaml"
CONFIG_SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "agentic-config.schema.json"
REQUIRED_SECTIONS = (
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
    allowed = policy.get("allowed_models")
    forbidden = policy.get("forbidden_models")
    immutable_forbidden = policy.get("immutable_forbidden_models")
    if not isinstance(allowed, list) or not allowed or any(not isinstance(item, str) or not item.strip() for item in allowed):
        raise ValueError("model_policy.allowed_models must be a non-empty array of strings")
    if not isinstance(forbidden, list) or any(not isinstance(item, str) or not item.strip() for item in forbidden):
        raise ValueError("model_policy.forbidden_models must be an array of strings")
    if not isinstance(immutable_forbidden, list) or any(not isinstance(item, str) or not item.strip() for item in immutable_forbidden):
        raise ValueError("model_policy.immutable_forbidden_models must be an array of strings")
    allowed_set = set(allowed)
    forbidden_set = set(forbidden)
    immutable_set = set(immutable_forbidden)
    if not immutable_set.issubset(forbidden_set):
        raise ValueError("model_policy.immutable_forbidden_models must be included in forbidden_models")
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
        model = record.get("model_dispatch")
        if dispatch_kind == "model":
            model = _require_string(model, f"agents.{agent_id}.model_dispatch")
            if model not in allowed_set or model in set(forbidden):
                raise ValueError(f"agents.{agent_id}.model_dispatch is not allowed by model_policy")
        elif dispatch_kind in {"script", "primary"}:
            if model is not None:
                raise ValueError(f"agents.{agent_id}.model_dispatch must be null for {dispatch_kind} dispatch")
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


def validate_dispatch_selection(dispatch: Any, config: dict[str, Any]) -> None:
    if not isinstance(dispatch, dict):
        raise ValueError("dispatch must be an object")
    agent_role = _require_string(dispatch.get("agent_role"), "dispatch.agent_role")
    selected_model = _require_string(dispatch.get("selected_model"), "dispatch.selected_model")
    record = config["agents"].get(agent_role)
    if not isinstance(record, dict):
        raise ValueError(f"dispatch.agent_role is not configured: {agent_role}")
    if record.get("dispatch_kind") != "model":
        raise ValueError(f"dispatch.agent_role is not a model agent: {agent_role}")
    if selected_model not in set(config["model_policy"]["allowed_models"]):
        raise ValueError(f"dispatch.selected_model is not allowed by the central config: {selected_model}")
    if selected_model != record.get("model_dispatch"):
        raise ValueError(f"dispatch.selected_model does not match {agent_role}: expected {record.get('model_dispatch')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        config = load_config(args.path)
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
