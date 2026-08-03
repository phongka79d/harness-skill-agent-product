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
import load_config as config_module  # noqa: E402


class AgenticConfigurationTests(unittest.TestCase):
    def test_roles_use_portable_model_refs_and_deployment_overlay(self) -> None:
        config = load_config()
        for agent_id in ("agent-executor", "agent-review", "agent-explorer"):
            record = config["agents"][agent_id]
            self.assertIn("model_ref", record)
            self.assertNotIn("model_dispatch", record)

        config_text = (SKILL_ROOT / "config" / "agentic-config.yaml").read_text(encoding="utf-8")
        self.assertNotIn("5.6-", config_text)
        self.assertTrue((SKILL_ROOT / "config" / "deployment.example.json").is_file())

    def test_deployment_overlay_resolves_provider_model_for_role(self) -> None:
        self.assertTrue(hasattr(config_module, "load_deployment_config"))
        self.assertTrue(hasattr(config_module, "resolve_agent"))
        config = load_config()
        policy = config["model_policy"]
        refs = list(policy.get("allowed_model_refs", [])) + list(policy.get("forbidden_model_refs", []))
        self.assertTrue(refs)
        overlay = {
            "schema_version": 1,
            "deployment_id": "unit-test",
            "version": "1",
            "model_ids": {ref: f"provider.{ref}" for ref in refs},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.json"
            path.write_text(json.dumps(overlay), encoding="utf-8")
            deployment = config_module.load_deployment_config(path, config)
            resolved = config_module.resolve_agent(config, "agent-executor", deployment)
        self.assertEqual(resolved["model_dispatch"], overlay["model_ids"][resolved["model_ref"]])

    def test_deployment_overlay_cannot_omit_immutable_model_refs(self) -> None:
        self.assertTrue(hasattr(config_module, "load_deployment_config"))
        config = load_config()
        policy = config["model_policy"]
        refs = list(policy.get("allowed_model_refs", [])) + list(policy.get("forbidden_model_refs", []))
        self.assertTrue(refs)
        immutable_refs = set(policy.get("immutable_forbidden_model_refs", []))
        self.assertTrue(immutable_refs)
        overlay = {
            "schema_version": 1,
            "deployment_id": "unit-test",
            "version": "1",
            "model_ids": {ref: f"provider.{ref}" for ref in refs if ref not in immutable_refs},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.json"
            path.write_text(json.dumps(overlay), encoding="utf-8")
            with self.assertRaises(ValueError):
                config_module.load_deployment_config(path, config)

    def test_default_config_has_required_roles_and_policy(self) -> None:
        config = load_config()
        self.assertIn("async_execution_enabled", config["execution"])
        self.assertFalse(config["execution"]["async_execution_enabled"])
        allowed = set(config["model_policy"]["allowed_model_refs"])
        forbidden = set(config["model_policy"]["forbidden_model_refs"])
        immutable_forbidden = set(config["model_policy"]["immutable_forbidden_model_refs"])
        self.assertTrue(allowed)
        self.assertTrue(immutable_forbidden)
        self.assertTrue(immutable_forbidden.issubset(forbidden))
        self.assertTrue(allowed.isdisjoint(forbidden))
        for agent_id in ("agent-executor", "agent-review", "agent-explorer", "agent-runtime-recovery"):
            self.assertIn(agent_id, config["agents"])
            self.assertIn(config["agents"][agent_id]["model_ref"], allowed)

    def test_environment_override_is_loaded_and_invalid_policy_is_rejected(self) -> None:
        config = load_config()
        configured_review_ref = config["agents"]["agent-review"]["model_ref"]
        config["agents"]["agent-executor"]["model_ref"] = configured_review_ref
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "override.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            previous = os.environ.get("AGENTIC_CONFIG_FILE")
            os.environ["AGENTIC_CONFIG_FILE"] = str(path)
            try:
                self.assertEqual(load_config()["agents"]["agent-executor"]["model_ref"], configured_review_ref)
            finally:
                if previous is None:
                    os.environ.pop("AGENTIC_CONFIG_FILE", None)
                else:
                    os.environ["AGENTIC_CONFIG_FILE"] = previous
        invalid = dict(config)
        invalid["model_policy"] = dict(
            config["model_policy"],
            allowed_model_refs=list(config["model_policy"]["forbidden_model_refs"]),
        )
        with self.assertRaises(ValueError):
            validate_config(invalid)

    def test_protected_forbidden_models_cannot_be_removed_from_config(self) -> None:
        config = load_config()
        policy = dict(config["model_policy"])
        policy["forbidden_model_refs"] = []
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
