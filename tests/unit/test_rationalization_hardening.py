from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RationalizationHardeningTests(unittest.TestCase):
    def test_each_critical_reference_points_to_executable_pressure_scenarios(self) -> None:
        references = {
            "skills/agentic-systematic-debugging/references/escalation-and-stop-rules.md": {"HSP-701-01", "HSP-701-02", "HSP-701-05"},
            "skills/agentic-verification-before-completion/references/completion-gate.md": {"HSP-701-03", "HSP-702-07", "HSP-702-09"},
            "skills/agentic-implementer/references/implementation-loop.md": {"HSP-701-02", "HSP-701-09"},
            "skills/agentic-task-reviewer/references/review-contract.md": {"HSP-701-04", "HSP-702-08"},
            "skills/agentic-engineering-core/references/policies/skill-routing.md": {"HSP-701-09", "HSP-701-10"},
        }
        for relative, scenario_ids in references.items():
            body = (ROOT / relative).read_text(encoding="utf-8")
            for scenario_id in scenario_ids:
                self.assertIn(scenario_id, body, f"{relative} lacks {scenario_id}")

    def test_profile_guidance_keeps_safety_rigid_and_depth_flexible(self) -> None:
        body = (ROOT / "skills/agentic-skill-authoring/references/behavioral-testing.md").read_text(encoding="utf-8")
        self.assertIn("machine-readable", body)
        self.assertIn("exception", body)
        self.assertIn("Profile flexibility changes verification depth", body)
        self.assertIn("not a passing test", body)


if __name__ == "__main__":
    unittest.main()
