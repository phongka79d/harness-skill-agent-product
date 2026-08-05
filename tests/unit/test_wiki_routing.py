from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2] / "skills" / "agentic-engineering-wiki"
sys.path.insert(0, str(ROOT / "scripts"))
from validate_wiki_links import validate_links


class WikiRoutingTests(unittest.TestCase):
    def test_installed_wiki_has_no_broken_or_external_links(self) -> None:
        self.assertEqual(validate_links(ROOT), [])

    def test_boundary_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SKILL.md").write_text("[bad](../outside.md)\n", encoding="utf-8")
            self.assertTrue(validate_links(root))

    def test_installed_wiki_can_route_to_sibling_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skills = Path(directory) / "skills"
            wiki = skills / "agentic-engineering-wiki"
            sibling = skills / "agentic-skill-authoring"
            wiki.mkdir(parents=True)
            sibling.mkdir()
            (wiki / "SKILL.md").write_text(
                "[skill](../agentic-skill-authoring/SKILL.md)\n",
                encoding="utf-8",
            )
            (sibling / "SKILL.md").write_text("skill\n", encoding="utf-8")
            self.assertEqual(validate_links(wiki), [])

    def test_installed_wiki_cannot_route_outside_skills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skills = root / "skills"
            wiki = skills / "agentic-engineering-wiki"
            outside = root / "docs"
            wiki.mkdir(parents=True)
            outside.mkdir()
            (wiki / "SKILL.md").write_text("[bad](../../docs/outside.md)\n", encoding="utf-8")
            (outside / "outside.md").write_text("outside\n", encoding="utf-8")
            self.assertTrue(validate_links(wiki))


if __name__ == "__main__":
    unittest.main()
