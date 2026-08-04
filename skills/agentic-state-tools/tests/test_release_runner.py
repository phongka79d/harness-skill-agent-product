from __future__ import annotations

import subprocess
import sys
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import run_tests  # noqa: E402


class ReleaseRunnerTests(unittest.TestCase):
    def require(self, name: str):
        value = getattr(run_tests, name, None)
        self.assertTrue(callable(value), f"run_tests.{name} is not implemented")
        return value

    def test_discovery_excludes_generated_cache_and_runtime_paths(self) -> None:
        paths = self.require("discover_test_files")()
        self.assertTrue(paths)
        for path in paths:
            self.assertNotIn("__pycache__", path.parts)
            self.assertNotIn(".pytest_cache", path.parts)
            self.assertNotIn(".agent", path.parts)

    def test_named_groups_have_deterministic_membership(self) -> None:
        group_fn = self.require("test_groups")
        groups = group_fn()
        self.assertEqual(
            list(groups),
            ["unit", "schema", "cli", "integration", "end_to_end", "recovery", "concurrency", "rollback", "review_integrity", "examples", "package"],
        )
        self.assertEqual(groups, group_fn())
        self.assertTrue(any(groups[name] for name in groups))
        self.assertTrue(groups["cli"], "CLI group must contain the CLI-facing orchestration tests")

    def test_group_summary_has_counts_elapsed_and_timeout_fields(self) -> None:
        summary = self.require("empty_group_summary")("unit")
        self.assertEqual(summary["group"], "unit")
        for key in ("passed", "failed", "skipped", "tests", "elapsed_seconds", "timed_out"):
            self.assertIn(key, summary)

    def test_every_explicit_group_assignment_points_to_a_discovered_test(self) -> None:
        discovered = {path.name for path in self.require("discover_test_files")()}
        assignments = getattr(run_tests, "GROUP_ASSIGNMENTS", {})
        missing = sorted(set(assignments) - discovered)
        self.assertEqual(missing, [], f"group assignments reference missing test files: {missing}")

    def test_release_preflight_forwards_timeout_to_every_child_process(self) -> None:
        timeouts: list[int | None] = []

        def fake_run(command, **kwargs):
            timeouts.append(kwargs.get("timeout"))
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch.object(run_tests.subprocess, "run", side_effect=fake_run):
            self.assertEqual(run_tests.validate_release_examples(timeout_seconds=7), [])

        self.assertTrue(timeouts)
        self.assertEqual(set(timeouts), {7})


if __name__ == "__main__":
    unittest.main()
