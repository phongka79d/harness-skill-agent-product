"""Run tests from staged skills whose directory names are not Python packages."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STATE_ROOT = ROOT / "skills" / "agentic-state-tools"
CONFIG_ROOT = ROOT / "skills" / "agentic-configuration"


def validate_release_examples() -> list[str]:
    """Validate the bundled V1 examples before loading the test suite."""

    examples = STATE_ROOT / "examples"
    config_value = json.loads((CONFIG_ROOT / "config/agentic-config.yaml").read_text(encoding="utf-8"))
    preflight_commands = [
        ("agentic-config", [sys.executable, str(CONFIG_ROOT / "scripts/load_config.py"), "--check"]),
        ("agentic-config-schema", [sys.executable, str(STATE_ROOT / "scripts/validate_payload.py"), "--input", str(CONFIG_ROOT / "config/agentic-config.yaml"), "--schema", str(CONFIG_ROOT / "schemas/agentic-config.schema.json")]),
    ]
    example_commands = [
        ("v1-planning-bundle.json", [sys.executable, str(STATE_ROOT / "scripts/validate_planning.py"), "--input", str(examples / "v1-planning-bundle.json")]),
        ("v1-dispatch.json", [sys.executable, str(STATE_ROOT / "scripts/validate_payload.py"), "--input", str(examples / "v1-dispatch.json"), "--schema", str(STATE_ROOT / "schemas/dispatch.schema.json")]),
        ("v1-recovery.json", [sys.executable, str(STATE_ROOT / "scripts/validate_payload.py"), "--input", str(examples / "v1-recovery.json"), "--schema", str(STATE_ROOT / "schemas/reconciliation.schema.json")]),
    ]
    errors: list[str] = []
    for name, command in preflight_commands:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            errors.append(f"{name}: {result.stderr.strip() or result.stdout.strip()}")
    for name, command in example_commands:
        path = examples / name
        if not path.is_file():
            errors.append(f"missing release example: {name}")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"invalid JSON in {name}: {exc}")
            continue
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            errors.append(f"{name}: {result.stderr.strip() or result.stdout.strip()}")
        if name == "v1-dispatch.json":
            try:
                dispatch = json.loads(path.read_text(encoding="utf-8"))
                role = dispatch.get("agent_role")
                reference = dispatch.get("model_reference")
                if reference == f"agents.{role}.model_dispatch" and isinstance(config_value.get("agents", {}).get(role), dict):
                    dispatch["selected_model"] = config_value["agents"][role]["model_dispatch"]
                policy_result = subprocess.run(
                    [sys.executable, str(STATE_ROOT / "scripts/dispatch_task.py"), "--input", "-"],
                    cwd=ROOT,
                    input=json.dumps(dispatch),
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if policy_result.returncode != 0:
                    errors.append(f"{name} policy: {policy_result.stderr.strip() or policy_result.stdout.strip()}")
            except (OSError, TypeError, ValueError) as exc:
                errors.append(f"{name} policy: {exc}")
    return errors


def load_suite() -> unittest.TestSuite:
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for test_path in sorted((ROOT / "skills").glob("*/tests/test_*.py")):
        module_name = "staged_" + "_".join(test_path.relative_to(ROOT).with_suffix("").parts)
        spec = importlib.util.spec_from_file_location(module_name, test_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load test module: {test_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


def main() -> int:
    release_errors = validate_release_examples()
    if release_errors:
        for error in release_errors:
            print(f"RELEASE_GATE_FAILED: {error}", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(load_suite())
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
