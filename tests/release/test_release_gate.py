from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

import run_tests


class ReleaseGateTests(unittest.TestCase):
    def test_release_commands_match_required_order(self) -> None:
        names = [name for name, _ in run_tests.release_preflight_commands()]
        self.assertEqual(names, ["test-suite", "compile", "wiki-links", "state-machine", "examples", "package"])

    def test_failed_preflight_is_reported_with_a_named_gate(self) -> None:
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="state failed")

        with patch.object(run_tests, "_run_release_process", side_effect=fake_run):
            errors = run_tests.run_release_preflight(timeout_seconds=1)
        self.assertEqual(len(errors), 6)
        self.assertTrue(all(":" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
