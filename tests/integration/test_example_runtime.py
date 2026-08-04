from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "agentic-state-tools"
SCRIPTS = SKILL_ROOT / "scripts"
CONFIG_ROOT = REPO_ROOT / "skills" / "agentic-configuration"
sys.path.insert(0, str(SCRIPTS))

try:
    from validate_examples import validate_all_examples  # noqa: E402
except ModuleNotFoundError:
    validate_all_examples = None

from dispatch_task import normalize_dispatch  # noqa: E402
from load_config import load_config, load_deployment_config  # noqa: E402


class ExampleRuntimeTests(unittest.TestCase):
    def test_all_examples_pass_their_runtime_validator(self) -> None:
        if not callable(validate_all_examples):
            self.fail("validate_examples.validate_all_examples is not implemented")
        errors = validate_all_examples(
            SKILL_ROOT / "examples",
            config_root=CONFIG_ROOT,
            deployment_path=CONFIG_ROOT / "config/deployment.test.json",
        )
        self.assertEqual(errors, [], "\n".join(errors))

    def test_portable_dispatch_template_resolves_through_deployment_overlay(self) -> None:
        config = load_config(CONFIG_ROOT / "config/agentic-config.yaml")
        deployment = load_deployment_config(CONFIG_ROOT / "config/deployment.test.json", config)
        value = json.loads((SKILL_ROOT / "examples/v1-dispatch.json").read_text(encoding="utf-8"))
        value["selected_mode"] = "SYNC"
        normalized = normalize_dispatch(value, config, deployment)
        expected = deployment["model_ids"][config["agents"]["agent-executor"]["model_ref"]]
        self.assertEqual(normalized["selected_model"], expected)


if __name__ == "__main__":
    unittest.main()
