from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE_SCRIPTS = ROOT / "skills" / "agentic-state-tools" / "scripts"
CONFIG_SCRIPTS = ROOT / "skills" / "agentic-configuration" / "scripts"
sys.path.insert(0, str(STATE_SCRIPTS))
sys.path.insert(0, str(CONFIG_SCRIPTS))

from load_config import load_config, load_deployment_config  # noqa: E402
from dispatch_task import normalize_dispatch  # noqa: E402
from resolve_skill_route import resolve_skill_route, validate_skill_route  # noqa: E402


class SkillRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "skills/agentic-configuration/config/agentic-config.yaml")
        self.deployment = load_deployment_config(ROOT / "skills/agentic-configuration/config/deployment.test.json", self.config)

    def test_process_role_domain_precedence_is_deterministic(self) -> None:
        config = copy.deepcopy(self.config)
        config["skill_routing"]["domain_skills"] = {"backend": "agentic-engineering-core"}
        route = resolve_skill_route(
            {
                "intent_classification": "bug",
                "current_state": "REPAIR_REQUIRED",
                "task_type": "backend",
                "repair": True,
                "risk_flags": {},
                "project_profile": "personal",
                "requested_role": "agent-executor",
            },
            configured_skills=config["skill_routing"]["available_skills"],
            config=config,
        )
        self.assertEqual(
            route["applicable_skills"],
            ["agentic-systematic-debugging", "agentic-implementer", "agentic-engineering-core"],
        )
        self.assertEqual(route["required_skills"], route["applicable_skills"])
        self.assertFalse(config["skill_routing"]["one_percent_rule"])

    def test_missing_mandatory_process_skill_is_rejected(self) -> None:
        route = resolve_skill_route(
            {
                "intent_classification": "bug",
                "current_state": "REPAIR_REQUIRED",
                "task_type": "backend",
                "repair": True,
                "risk_flags": {},
                "project_profile": "personal",
                "requested_role": "agent-executor",
            },
            config=self.config,
            configured_skills=self.config["skill_routing"]["available_skills"],
            loaded_skills=["agentic-systematic-debugging", "agentic-implementer"],
        )
        route["loaded_skills"] = ["agentic-implementer"]
        with self.assertRaisesRegex(ValueError, "mandatory skill"):
            validate_skill_route(route, configured_skills=self.config["skill_routing"]["available_skills"])

    def test_provider_model_ids_are_not_valid_skills(self) -> None:
        route = resolve_skill_route(
            {"requested_role": "agent-executor"},
            config=self.config,
            configured_skills=self.config["skill_routing"]["available_skills"],
        )
        route["loaded_skills"] = ["provider.some-model"]
        with self.assertRaisesRegex(ValueError, "provider model IDs"):
            validate_skill_route(route)

    def test_example_is_a_valid_route_and_input_lists_are_consumed(self) -> None:
        example = json.loads(
            (ROOT / "skills/agentic-state-tools/examples/skill-routing.json").read_text(encoding="utf-8")
        )
        validate_skill_route(example)
        resolved = resolve_skill_route(
            {
                **example,
                "configured_skills": [
                    "agentic-systematic-debugging",
                    "agentic-implementer",
                ],
            }
        )
        self.assertNotEqual(resolved["routing_id"], example["routing_id"])
        self.assertEqual(resolved["loaded_skills"], example["loaded_skills"])

    def test_legacy_dispatch_gets_route_without_changing_selected_model(self) -> None:
        dispatch = {
            "dispatch_id": "DSP-ROUTE-UNIT",
            "task_id": "T-ROUTE-UNIT",
            "agent_role": "agent-executor",
            "selected_mode": "SYNC",
            "selected_owner": "primary-agent",
            "selected_model": "${deployment.model_ids[agents.agent-executor.model_ref]}",
            "model_reference": "agents.agent-executor.model_ref",
            "input_revisions": {"queue": 0, "task": 0},
            "approval_references": [],
            "evidence": {"reason": "routing test", "architecture_owner": "primary-agent"},
        }
        normalized = normalize_dispatch(dispatch, self.config, self.deployment)
        self.assertEqual(normalized["selected_model"], self.deployment["model_ids"]["implementation"])
        self.assertEqual(normalized["skill_route"]["loaded_skills"], ["agentic-implementer"])

    def test_dispatch_rejects_explicit_route_without_debugging_process(self) -> None:
        dispatch = {
            "dispatch_id": "DSP-ROUTE-NEG",
            "task_id": "T-ROUTE-NEG",
            "agent_role": "agent-executor",
            "selected_mode": "SYNC",
            "selected_owner": "primary-agent",
            "selected_model": "${deployment.model_ids[agents.agent-executor.model_ref]}",
            "model_reference": "agents.agent-executor.model_ref",
            "input_revisions": {"queue": 0, "task": 0},
            "approval_references": [],
            "evidence": {"reason": "routing test", "architecture_owner": "primary-agent"},
            "intent_classification": "bug",
            "current_state": "REPAIR_REQUIRED",
            "repair": True,
            "skill_route": {
                "routing_id": "ROUTE-BAD",
                "intent_classification": "bug",
                "task_type": "standard",
                "current_state": "REPAIR_REQUIRED",
                "repair": True,
                "project_profile": "personal",
                "requested_role": "agent-executor",
                "risk_flags": {},
                "applicable_skills": ["agentic-implementer"],
                "required_skills": ["agentic-implementer"],
                "loaded_skills": ["agentic-implementer"],
                "routing_reason": "bad omission",
                "routing_policy_version": "1",
            },
        }
        with self.assertRaisesRegex(ValueError, "deterministic routing|mandatory skill"):
            normalize_dispatch(dispatch, self.config, self.deployment)


if __name__ == "__main__":
    unittest.main()
