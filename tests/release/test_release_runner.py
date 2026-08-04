from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import run_tests  # noqa: E402


class ReleaseRunnerTests(unittest.TestCase):
    def require(self, name: str):
        value = getattr(run_tests, name, None)
        self.assertTrue(callable(value), f"run_tests.{name} is not implemented")
        return value

    def test_discovery_is_limited_to_configured_groups_and_excludes_generated_paths(self) -> None:
        paths = self.require("discover_test_files")()
        self.assertTrue(paths)
        for path in paths:
            relative = path.relative_to(ROOT)
            self.assertIn(relative.parts[0], {"tests", "skills"})
            self.assertFalse(set(part.casefold() for part in relative.parts) & run_tests.EXCLUDED_PARTS)

    def test_named_groups_have_deterministic_membership_and_release_alias(self) -> None:
        groups = self.require("test_groups")()
        self.assertEqual(list(groups), list(run_tests.GROUP_NAMES))
        self.assertEqual(groups, self.require("test_groups")())
        self.assertTrue(groups["unit"])
        self.assertTrue(groups["integration"])
        self.assertTrue(groups["release"])
        self.assertEqual(run_tests.GROUP_ALIASES.get("end_to_end"), "e2e")

    def test_group_summary_has_counts_collection_errors_elapsed_and_timeout_fields(self) -> None:
        summary = self.require("empty_group_summary")("unit")
        for key in ("passed", "failed", "skipped", "tests", "collection_errors", "elapsed_seconds", "timed_out"):
            self.assertIn(key, summary)

    def test_every_explicit_group_assignment_points_to_a_discovered_test(self) -> None:
        discovered = {path.name for path in self.require("discover_test_files")()}
        assignments = getattr(run_tests, "GROUP_ASSIGNMENTS", {})
        self.assertEqual(sorted(set(assignments) - discovered), [])

    def test_release_preflight_forwards_timeout_and_preserves_order(self) -> None:
        calls: list[tuple[str, int]] = []

        def fake_run(command, **kwargs):
            calls.append((run_tests.release_preflight_commands()[len(calls)][0], kwargs["timeout_seconds"]))
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch.object(run_tests, "_run_release_process", side_effect=fake_run):
            self.assertEqual(run_tests.run_release_preflight(timeout_seconds=7), [])
        self.assertEqual([name for name, _ in calls], [name for name, _ in run_tests.release_preflight_commands()])
        self.assertEqual(calls[0], ("test-suite", 7 * len(run_tests.GROUP_NAMES)))
        self.assertEqual({timeout for _, timeout in calls[1:]}, {7})

    def test_release_test_suite_is_forced_into_group_only_mode(self) -> None:
        captured: list[dict[str, str]] = []

        def fake_run(command, **kwargs):
            captured.append(kwargs["env"])
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch.object(run_tests, "_run_release_process", side_effect=fake_run):
            self.assertEqual(run_tests.run_release_preflight(timeout_seconds=7), [])
        self.assertEqual(captured[0].get("AGENTIC_RELEASE_GROUPS_ONLY"), "1")

    def test_release_preflight_names_each_failure_and_does_not_stop_early(self) -> None:
        calls: list[str] = []

        def fake_run(command, **kwargs):
            index = len(calls)
            name = run_tests.release_preflight_commands()[index][0]
            calls.append(name)
            return subprocess.CompletedProcess(command, 1 if name == "state-machine" else 0, stdout="", stderr="bad")

        with patch.object(run_tests, "_run_release_process", side_effect=fake_run):
            errors = run_tests.run_release_preflight(timeout_seconds=7)
        self.assertEqual(calls, [name for name, _ in run_tests.release_preflight_commands()])
        self.assertTrue(any(error.startswith("state-machine:") for error in errors))


if __name__ == "__main__":
    unittest.main()
