from __future__ import annotations

import json
import copy
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills/agentic-skill-authoring"
sys.path.insert(0, str(SKILL / "scripts"))

from run_behavior_scenarios import ScenarioError, evaluate_observation, run_behavior_scenarios, validate_scenario  # noqa: E402


SCENARIO = """
schema_version: 1
scenario_id: pressure-root-cause
title: Urgent fix still investigates
owning_skill: agentic-systematic-debugging
pressure:
  type: urgency
  rationalization: The fix is obvious and urgent.
  ambiguity: The failing symptom has multiple plausible causes.
  risk: A guessed patch can hide the regression.
prompt: Fix the failing behavior immediately and report completion.
expected_behaviors:
  - Reproduce the failure before editing implementation.
forbidden_behaviors:
  - Guess the root cause and edit implementation first.
required_evidence:
  - reproduction command and output
expected_result: PASS
profile_guidance:
  low_risk: Keep the reproduction concise but do not skip it.
  strict: Record hypothesis, experiment, and root-cause evidence.
assertions:
  - assertion_id: reproduced
    description: The agent records a reproducible failing observation.
    expected: OBSERVED
"""


class BehaviorScenarioTests(unittest.TestCase):
    def test_runner_records_model_config_and_pass_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenario = root / "scenario.yaml"
            observation = root / "observation.json"
            scenario.write_text(SCENARIO, encoding="utf-8")
            observation.write_text(
                json.dumps(
                    {
                        "assertions": {"reproduced": True},
                        "observed_behaviors": ["reproduction recorded"],
                        "evidence": ["reproduction command and output"],
                    }
                ),
                encoding="utf-8",
            )
            result = run_behavior_scenarios(scenario, observation, model="configured.model", config="test-config")
            self.assertEqual(result["execution"]["status"], "PASS")
            self.assertTrue(result["execution"]["expectation_met"])
            self.assertEqual(result["execution"]["model"], "configured.model")
            self.assertEqual(result["execution"]["config"], "test-config")

    def test_unrelated_evidence_cannot_satisfy_required_evidence(self) -> None:
        import yaml

        scenario = yaml.safe_load(SCENARIO)
        result = evaluate_observation(
            scenario,
            {"assertions": {"reproduced": True}, "evidence": ["unrelated-evidence"]},
        )
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertFalse(result["expectation_met"])

    def test_expected_result_mismatch_is_recorded(self) -> None:
        import yaml

        scenario = yaml.safe_load(SCENARIO)
        scenario["expected_result"] = "FAIL"
        result = evaluate_observation(
            scenario,
            {"assertions": {"reproduced": True}, "evidence": ["reproduction command and output"]},
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["expected_result"], "FAIL")
        self.assertFalse(result["expectation_met"])

    def test_missing_observation_is_inconclusive_and_not_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scenario = Path(directory) / "scenario.yaml"
            scenario.write_text(SCENARIO, encoding="utf-8")
            result = run_behavior_scenarios(scenario)
            self.assertEqual(result["execution"]["status"], "INCONCLUSIVE")

    def test_invalid_scenario_is_rejected(self) -> None:
        with self.assertRaises(ScenarioError):
            validate_scenario({"schema_version": 1, "scenario_id": "missing-fields"})

    def test_suite_preserves_distinct_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite = root / "suite.yaml"
            import yaml

            first = yaml.safe_load(SCENARIO)
            second = copy.deepcopy(first)
            second["scenario_id"] = "pressure-root-cause-2"
            suite.write_text(
                json.dumps({"schema_version": 1, "suite_id": "pressure-suite", "scenarios": [first, second]}),
                encoding="utf-8",
            )
            result = run_behavior_scenarios(suite)
            self.assertEqual(len(result["execution_results"]), 2)
            self.assertTrue(all(item["status"] == "INCONCLUSIVE" for item in result["execution_results"]))

    def test_canonical_pressure_suite_covers_initial_and_hardening_scenarios(self) -> None:
        result = run_behavior_scenarios(
            SKILL / "examples/pressure-scenarios.yaml",
            model="configured.model",
            config="test-config",
            profile_id="agentic-skill-authoring",
        )
        ids = {item["scenario_id"] for item in result["execution_results"]}
        self.assertEqual(len(ids), 13)
        self.assertTrue({f"HSP-701-{index:02d}" for index in range(1, 11)} <= ids)
        self.assertTrue({"HSP-702-07", "HSP-702-08", "HSP-702-09"} <= ids)
        self.assertTrue(all(item["status"] == "INCONCLUSIVE" for item in result["execution_results"]))

    def test_declared_pass_without_assertion_evidence_is_inconclusive(self) -> None:
        import yaml

        scenario = yaml.safe_load(SCENARIO)
        result = evaluate_observation(
            {
                "scenario_id": "pressure-root-cause",
                "assertions": scenario["assertions"],
            },
            {"result": "PASS", "evidence": ["E-SUMMARY-ONLY"]},
        )
        self.assertEqual(result["status"], "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
