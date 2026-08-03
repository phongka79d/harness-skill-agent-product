from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from load_config import load_config, validate_config  # noqa: E402


class AgenticConfigurationTests(unittest.TestCase):
    def test_default_config_has_required_roles_and_policy(self) -> None:
        config = load_config()
        allowed = set(config["model_policy"]["allowed_models"])
        forbidden = set(config["model_policy"]["forbidden_models"])
        immutable_forbidden = set(config["model_policy"]["immutable_forbidden_models"])
        self.assertTrue(allowed)
        self.assertTrue(immutable_forbidden)
        self.assertTrue(immutable_forbidden.issubset(forbidden))
        self.assertTrue(allowed.isdisjoint(forbidden))
        for agent_id in ("agent-executor", "agent-review", "agent-explorer", "agent-runtime-recovery"):
            self.assertIn(agent_id, config["agents"])
            self.assertIn(config["agents"][agent_id]["model_dispatch"], allowed)

    def test_environment_override_is_loaded_and_invalid_policy_is_rejected(self) -> None:
        config = load_config()
        configured_review_model = config["agents"]["agent-review"]["model_dispatch"]
        config["agents"]["agent-executor"]["model_dispatch"] = configured_review_model
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "override.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            previous = os.environ.get("AGENTIC_CONFIG_FILE")
            os.environ["AGENTIC_CONFIG_FILE"] = str(path)
            try:
                self.assertEqual(load_config()["agents"]["agent-executor"]["model_dispatch"], configured_review_model)
            finally:
                if previous is None:
                    os.environ.pop("AGENTIC_CONFIG_FILE", None)
                else:
                    os.environ["AGENTIC_CONFIG_FILE"] = previous
        invalid = dict(config)
        invalid["model_policy"] = dict(config["model_policy"], allowed_models=list(config["model_policy"]["forbidden_models"]))
        with self.assertRaises(ValueError):
            validate_config(invalid)

    def test_protected_forbidden_models_cannot_be_removed_from_config(self) -> None:
        config = load_config()
        policy = dict(config["model_policy"])
        policy["forbidden_models"] = []
        config["model_policy"] = policy
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_schema_invalid_config_is_rejected_before_policy_checks(self) -> None:
        config = load_config()
        config["schema_version"] = True
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_schema_rejects_malformed_execution_and_context_budget_values(self) -> None:
        config = load_config()
        config["execution"]["default_mode"] = 123
        with self.assertRaises(ValueError):
            validate_config(config)

        config = load_config()
        config["context_budget"]["max_files"] = "many"
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_loader_cli_checks_the_bundled_config(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "load_config.py"), "--check"],
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CONFIG_VALID", result.stdout)


if __name__ == "__main__":
    unittest.main()
