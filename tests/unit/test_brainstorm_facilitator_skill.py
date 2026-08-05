from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "agentic-brainstorm-facilitator"
WIKI = ROOT / "skills" / "agentic-engineering-wiki"


class BrainstormFacilitatorSkillTests(unittest.TestCase):
    def test_entrypoint_routes_protocol_and_scales_ceremony(self) -> None:
        body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "Inspect the relevant project context",
            "facts, assumptions, constraints, unknowns, and decisions",
            "independent subsystems",
            "two or three materially different",
            "design self-review",
            "quick_change",
            "production",
            "Do not silently resolve",
        ):
            self.assertIn(phrase, body)
        self.assertIn("references/brainstorming-protocol.md", body)
        self.assertIn("references/design-self-review.md", body)

    def test_protocol_self_review_and_example_are_complete(self) -> None:
        protocol = (SKILL / "references" / "brainstorming-protocol.md").read_text(encoding="utf-8")
        review = (SKILL / "references" / "design-self-review.md").read_text(encoding="utf-8")
        example = (SKILL / "examples" / "brainstorm-handoff.example.md").read_text(encoding="utf-8")
        for phrase in (
            "Facts:",
            "Assumptions:",
            "Constraints:",
            "Unknowns:",
            "Decisions:",
            "Error handling",
            "Testing strategy",
            "Completion conditions",
            "Ask focused questions",
        ):
            self.assertIn(phrase, protocol)
        for phrase in ("Contradiction", "Ambiguity", "Placeholders", "Unnecessary scope", "Handoff readiness"):
            self.assertIn(phrase, review)
        for phrase in ("status: READY_FOR_PLANNING", "facts:", "assumptions:", "options:", "self_review:", "status: PASS"):
            self.assertIn(phrase, example)

    def test_wiki_routes_to_local_brainstorm_references(self) -> None:
        role = (WIKI / "refs" / "roles" / "brainstorm-facilitator.md").read_text(encoding="utf-8")
        workflow = (WIKI / "refs" / "workflows" / "planning.md").read_text(encoding="utf-8")
        self.assertIn("agentic-brainstorm-facilitator/references/brainstorming-protocol.md", role)
        self.assertIn("agentic-brainstorm-facilitator/references/design-self-review.md", role)
        self.assertIn("design self-review", workflow)
        self.assertIn("independent subsystems", workflow)


if __name__ == "__main__":
    unittest.main()
