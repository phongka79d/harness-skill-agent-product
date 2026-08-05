from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "agentic-systematic-debugging"


class SystematicDebuggingSkillTests(unittest.TestCase):
    def test_entrypoint_contains_triggers_workflow_and_boundaries(self) -> None:
        body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "flaky",
            "unexplained failure",
            "root cause",
            "one falsifiable hypothesis",
            "condition-based wait",
            "BLOCKED",
            "ESCALATED",
            "agentic-engineering-core",
            "agentic-engineering-wiki",
            "agentic-state-tools",
        ):
            self.assertIn(phrase, body)
        self.assertIn("Do not modify implementation", body)
        self.assertIn("Do not repeat an identical failed hypothesis", body)

    def test_references_and_example_exist_and_are_local(self) -> None:
        for relative in (
            "references/debugging-protocol.md",
            "references/root-cause-tracing.md",
            "references/condition-based-waiting.md",
            "references/escalation-and-stop-rules.md",
            "examples/debug-investigation.example.json",
        ):
            self.assertTrue((SKILL / relative).is_file(), relative)
        example = json.loads((SKILL / "examples/debug-investigation.example.json").read_text(encoding="utf-8"))
        self.assertEqual(example["schema_version"], 1)
        self.assertEqual(example["status"], "COMPLETED")
        self.assertEqual(example["hypotheses"][0]["outcome"], "CONFIRMED")

    def test_ui_metadata_points_to_the_new_skill(self) -> None:
        metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$agentic-systematic-debugging", metadata)


if __name__ == "__main__":
    unittest.main()
