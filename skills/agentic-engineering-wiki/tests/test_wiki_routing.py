from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
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


if __name__ == "__main__":
    unittest.main()
