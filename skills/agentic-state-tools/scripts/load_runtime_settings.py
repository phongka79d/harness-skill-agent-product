"""Load or initialize user-editable project-local runtime settings."""
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
from runtime_utils import (  # noqa: E402
    read_json,
    runtime_root,
    safe_child,
    write_json_atomic,
)

SETTINGS_SCHEMA = HERE.parents[1] / "schemas" / "runtime-settings.schema.json"
SETTINGS_FILENAME = "settings.json"


def _validate(settings: dict[str, Any]) -> dict[str, Any]:
    validate_file(settings, SETTINGS_SCHEMA, "runtime settings")
    wait = settings["subagent_wait"]
    if wait["check_interval_seconds"] >= wait["timeout_seconds"]:
        raise ValueError(
            "subagent_wait.check_interval_seconds must be shorter than timeout_seconds"
        )
    execution = settings["execution"]
    if execution["dispatch_timeout_seconds"] < wait["check_interval_seconds"]:
        raise ValueError(
            "execution.dispatch_timeout_seconds must be at least "
            "subagent_wait.check_interval_seconds"
        )
    return settings


def _settings_path(project_root: str | Path) -> Path:
    root = runtime_root(project_root)
    unresolved = root / SETTINGS_FILENAME
    if unresolved.is_symlink():
        raise ValueError("runtime settings must not be a symbolic link")
    return safe_child(root, SETTINGS_FILENAME)


def _require_runtime(project_root: str | Path) -> None:
    root = runtime_root(project_root)
    if not safe_child(root, "state.json").is_file():
        raise ValueError("runtime is not initialized")


def settings_from_config(config: dict[str, Any]) -> dict[str, Any]:
    wait = config["subagent_policy"]["wait"]
    policy = config["subagent_policy"]
    return _validate(
        {
            "schema_version": 2,
            "subagent_wait": {
                "check_interval_seconds": wait["check_interval_seconds"],
                "timeout_seconds": wait["timeout_seconds"],
                "close_on_timeout": wait["close_on_timeout"],
            },
            "execution": {
                "mode": config["execution"]["mode"],
                "dispatch_timeout_seconds": wait["timeout_seconds"],
                "max_active_subagents": policy["depths"]["controlled"]["max_active"],
            },
            "primary_agent_fallback": policy["synthesized_fallback"],
        }
    )


def _migrate_v1(settings: dict[str, Any], config_path: str | Path | None = None) -> dict[str, Any]:
    """Upgrade a schema v1 settings file in place, preserving user subagent_wait values."""
    config = load_config(config_path)
    wait = config["subagent_policy"]["wait"]
    policy = config["subagent_policy"]
    upgraded = {
        "schema_version": 2,
        "subagent_wait": settings["subagent_wait"],
        "execution": {
            "mode": config["execution"]["mode"],
            "dispatch_timeout_seconds": wait["timeout_seconds"],
            "max_active_subagents": policy["depths"]["controlled"]["max_active"],
        },
        "primary_agent_fallback": policy["synthesized_fallback"],
    }
    return _validate(upgraded)


def read_runtime_settings(project_root: str | Path) -> dict[str, Any]:
    _require_runtime(project_root)
    path = _settings_path(project_root)
    if not path.is_file():
        raise ValueError("runtime settings are missing; run with --ensure")
    settings = read_json(path)
    if settings.get("schema_version") == 1:
        raise ValueError("runtime settings are schema v1; run with --ensure to migrate")
    return _validate(settings)


def ensure_runtime_settings(
    project_root: str | Path, config_path: str | Path | None = None
) -> dict[str, Any]:
    _require_runtime(project_root)
    path = _settings_path(project_root)
    if path.exists():
        settings = read_json(path)
        if settings.get("schema_version") == 1:
            upgraded = _migrate_v1(settings, config_path)
            write_json_atomic(path, upgraded)
            return upgraded
        return read_runtime_settings(project_root)
    settings = settings_from_config(load_config(config_path))
    write_json_atomic(path, settings)
    return settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--config")
    parser.add_argument("--ensure", action="store_true")
    args = parser.parse_args()
    try:
        settings = (
            ensure_runtime_settings(args.project_root, args.config)
            if args.ensure
            else read_runtime_settings(args.project_root)
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"RUNTIME_SETTINGS_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(settings, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
