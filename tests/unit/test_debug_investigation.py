from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE_TOOLS = ROOT / "skills" / "agentic-state-tools"
SCRIPTS = STATE_TOOLS / "scripts"
SCHEMAS = STATE_TOOLS / "schemas"
sys.path.insert(0, str(SCRIPTS))

from write_artifact import write_validated  # noqa: E402


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
        env=os.environ.copy(),
    )


class DebugInvestigationTests(unittest.TestCase):
    task = {
        "task_id": "T-DBG-1",
        "batch_id": "B-DBG-1",
        "plan_revision": 1,
        "revision": 3,
        "status": "REPAIR_REQUIRED",
        "run_id": "RUN-DBG-1",
        "attempt_id": "ATTEMPT-DBG-1",
        "dispatch_id": "DISPATCH-DBG-1",
    }

    def write_json(self, path: Path, value: object) -> Path:
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def setUpProject(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        directory = tempfile.TemporaryDirectory()
        project = Path(directory.name)
        initialized = run_script("init_runtime.py", "--project-root", str(project))
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        work = project / ".agent" / "work" / self.task["task_id"]
        work.mkdir(parents=True, exist_ok=True)
        write_validated(str(project), f"work/{self.task['task_id']}/task-state.json", self.task, SCHEMAS / "task-state.schema.json")
        return directory, project

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "investigation_id": "DBG-T-DBG-1-1",
            "task_id": "T-DBG-1",
            "run_id": "RUN-DBG-1",
            "attempt_id": "ATTEMPT-DBG-1",
            "task_revision": 4,
            "symptom": "The parser returns an empty result for a valid input.",
            "reproduction_status": "REPRODUCED",
            "reproduction_steps": ["Run the parser with the fixture input."],
            "observed_output": "[]",
            "expected_output": "[item]",
            "environment_facts": {"python": "repository-configured"},
            "recent_changes": ["Parser normalization changed in the previous attempt."],
            "data_flow_trace": ["fixture -> parser input", "input -> normalization", "normalization -> empty result"],
            "working_reference": "tests/unit/test_parser.py::test_valid_input",
            "hypotheses": [
                {
                    "hypothesis_id": "H-1",
                    "statement": "Normalization drops the field before parsing.",
                    "predicted_observation": "The field is absent immediately after normalization.",
                    "experiment": "Log the normalized object for the fixture input.",
                    "result": "The field is absent.",
                    "outcome": "CONFIRMED",
                }
            ],
            "current_hypothesis": "H-1",
            "experiment": {
                "command": "python -m unittest tests/unit/test_parser.py -v",
                "expected_observation": "The focused regression test fails before the fix.",
            },
            "experiment_result": {
                "observed": "The normalized field is absent.",
                "outcome": "CONFIRMED",
                "recorded_at": "2026-08-05T00:00:00Z",
            },
            "root_cause": "The normalization branch removes the valid field.",
            "regression_check": {
                "command": "python -m unittest tests/unit/test_parser.py -v",
                "exit_code": 0,
                "workspace_hash": "a" * 64,
                "status": "PASS",
            },
            "fix_attempt_count": 1,
            "status": "COMPLETED",
            "created_at": "2026-08-05T00:00:00Z",
            "updated_at": "2026-08-05T00:00:00Z",
        }

    def run_writer(self, project: Path, payload: dict[str, object], *, actor: str = "executor") -> subprocess.CompletedProcess[str]:
        input_path = self.write_json(project / "investigation-input.json", payload)
        return run_script(
            "create_debug_investigation.py",
            "--project-root", str(project),
            "--task-id", "T-DBG-1",
            "--input", str(input_path),
            "--actor", actor,
        )

    def test_valid_payload_writes_versioned_artifact_and_event(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        result = self.run_writer(project, self.payload())
        self.assertEqual(result.returncode, 0, result.stderr)
        artifact = json.loads((project / ".agent/work/T-DBG-1/debug-investigation.json").read_text(encoding="utf-8"))
        self.assertEqual(artifact["revision"], 1)
        self.assertEqual(artifact["task_revision"], 4)
        events = (project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8")
        self.assertIn("DEBUG_INVESTIGATION_CREATED", events)

    def test_duplicate_hypothesis_ids_do_not_change_existing_bytes(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        self.assertEqual(self.run_writer(project, self.payload()).returncode, 0)
        target = project / ".agent/work/T-DBG-1/debug-investigation.json"
        before = target.read_bytes()
        invalid = self.payload()
        invalid["hypotheses"] = [invalid["hypotheses"][0], dict(invalid["hypotheses"][0])]  # type: ignore[index]
        result = self.run_writer(project, invalid)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEBUG_INVESTIGATION_REJECTED", result.stderr)
        self.assertEqual(target.read_bytes(), before)

    def test_mismatched_identity_is_rejected_without_new_artifact(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        invalid = self.payload()
        invalid["run_id"] = "RUN-OTHER"
        result = self.run_writer(project, invalid)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEBUG_INVESTIGATION_REJECTED", result.stderr)
        self.assertFalse((project / ".agent/work/T-DBG-1/debug-investigation.json").exists())

    def test_completed_requires_root_cause_and_passing_regression(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        invalid = self.payload()
        invalid["root_cause"] = None
        invalid["regression_check"] = {**invalid["regression_check"], "exit_code": 1, "status": "FAIL"}  # type: ignore[index]
        result = self.run_writer(project, invalid)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEBUG_INVESTIGATION_REJECTED", result.stderr)
        self.assertFalse((project / ".agent/work/T-DBG-1/debug-investigation.json").exists())

    def test_fourth_fix_attempt_is_rejected(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        invalid = self.payload()
        invalid["fix_attempt_count"] = 4
        result = self.run_writer(project, invalid)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEBUG_INVESTIGATION_REJECTED", result.stderr)
        self.assertFalse((project / ".agent/work/T-DBG-1/debug-investigation.json").exists())

    def test_unknown_schema_version_is_rejected_before_write(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        invalid = self.payload()
        invalid["schema_version"] = 2
        result = self.run_writer(project, invalid)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEBUG_INVESTIGATION_REJECTED", result.stderr)
        self.assertFalse((project / ".agent/work/T-DBG-1/debug-investigation.json").exists())

    def test_invalid_actor_is_rejected_before_artifact_write(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        result = self.run_writer(project, self.payload(), actor="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEBUG_INVESTIGATION_REJECTED", result.stderr)
        self.assertFalse((project / ".agent/work/T-DBG-1/debug-investigation.json").exists())

    def test_invalid_event_journal_is_rejected_before_artifact_write(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        (project / ".agent/runtime/events.jsonl").write_text("not-json\n", encoding="utf-8")
        result = self.run_writer(project, self.payload())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEBUG_INVESTIGATION_REJECTED", result.stderr)
        self.assertFalse((project / ".agent/work/T-DBG-1/debug-investigation.json").exists())

    def test_second_revision_preserves_identity_and_increments_revision(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        first = self.payload()
        self.assertEqual(self.run_writer(project, first).returncode, 0)
        original = json.loads((project / ".agent/work/T-DBG-1/debug-investigation.json").read_text(encoding="utf-8"))
        second = self.payload()
        second["status"] = "COMPLETED"
        second["updated_at"] = "2026-08-05T00:01:00Z"
        result = self.run_writer(project, second)
        self.assertEqual(result.returncode, 0, result.stderr)
        current = json.loads((project / ".agent/work/T-DBG-1/debug-investigation.json").read_text(encoding="utf-8"))
        self.assertEqual(current["revision"], 2)
        self.assertEqual(current["previous_revision"], 1)
        self.assertEqual(current["investigation_id"], original["investigation_id"])
        self.assertEqual(current["task_id"], original["task_id"])
        self.assertEqual(current["run_id"], original["run_id"])
        self.assertEqual(current["attempt_id"], original["attempt_id"])
        self.assertGreaterEqual(current["updated_at"], original["updated_at"])


if __name__ == "__main__":
    unittest.main()
