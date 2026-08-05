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


REVIEW_CONTRACT = {
    "project_profile": "personal",
    "profile_hash": "d797c0c42d7f88fe34a1101f635fffc128946321f802336489471698dd865851",
    "task_type": "backend",
    "risk_flags": {},
    "review_type": "task",
    "rubric_id": "TASK_REVIEW_BACKEND_LIGHTWEIGHT_V1",
    "rubric_version": "1.1",
    "rubric_hash": "e9064bbddeb5838b3c77e1dc9ab33c88420c832329703da95d0498c7f8517ff3",
    "review_policy_version": "1",
}


class DebugRepairIntegrationTests(unittest.TestCase):
    task_id = "T-DBG-1"

    def write_json(self, path: Path, value: object) -> Path:
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def setUpProject(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        directory = tempfile.TemporaryDirectory()
        project = Path(directory.name)
        initialized = run_script("init_runtime.py", "--project-root", str(project))
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        task = {
            "task_id": self.task_id,
            "batch_id": "B-DBG-1",
            "plan_revision": 1,
            "revision": 3,
            "status": "REPAIR_REQUIRED",
            "run_id": "RUN-DBG-1",
            "attempt_id": "ATTEMPT-DBG-1",
            "dispatch_id": "DISPATCH-DBG-1",
            "review_contract": REVIEW_CONTRACT,
        }
        write_validated(str(project), f"work/{self.task_id}/task-state.json", task, SCHEMAS / "task-state.schema.json")
        return directory, project

    def investigation_payload(self, *, status: str = "COMPLETED", regression_status: str = "PASS", exit_code: int = 0) -> dict[str, object]:
        return {
            "schema_version": 1,
            "investigation_id": "DBG-T-DBG-1-1",
            "task_id": self.task_id,
            "run_id": "RUN-DBG-1",
            "attempt_id": "ATTEMPT-DBG-1",
            "task_revision": 4,
            "symptom": "The parser returns an empty result for a valid input.",
            "reproduction_status": "REPRODUCED",
            "reproduction_steps": ["Run the parser with the fixture input."],
            "observed_output": "[]",
            "expected_output": "[item]",
            "environment_facts": {"python": "repository-configured"},
            "recent_changes": ["Parser normalization changed."],
            "data_flow_trace": ["fixture -> parser input", "input -> normalization", "normalization -> empty result"],
            "working_reference": "tests/unit/test_parser.py::test_valid_input",
            "hypotheses": [{
                "hypothesis_id": "H-1",
                "statement": "Normalization drops the field.",
                "predicted_observation": "The normalized field is absent.",
                "experiment": "Inspect normalized input.",
                "result": "The field is absent.",
                "outcome": "CONFIRMED",
            }],
            "current_hypothesis": "H-1",
            "experiment": {"command": "python -m unittest", "expected_observation": "The focused check exercises the defect."},
            "experiment_result": {"observed": "The normalized field is absent.", "outcome": "CONFIRMED", "recorded_at": "2026-08-05T00:00:00Z"},
            "root_cause": "The normalization branch removes the valid field.",
            "regression_check": {"command": "python -m unittest", "exit_code": exit_code, "workspace_hash": "a" * 64, "status": regression_status},
            "fix_attempt_count": 1,
            "status": status,
            "created_at": "2026-08-05T00:00:00Z",
            "updated_at": "2026-08-05T00:00:00Z",
        }

    def create_investigation(self, project: Path, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
        input_path = self.write_json(project / "investigation-input.json", payload)
        return run_script("create_debug_investigation.py", "--project-root", str(project), "--task-id", self.task_id, "--input", str(input_path), "--actor", "executor")

    def dispatch_payload(self, investigation_id: str | None = None) -> dict[str, object]:
        value: dict[str, object] = {
            "dispatch_id": "DISPATCH-DBG-1",
            "task_id": self.task_id,
            "agent_role": "agent-executor",
            "selected_mode": "SYNC",
            "selected_owner": "primary-agent",
            "selected_model": "${deployment.model_ids[agents.agent-executor.model_ref]}",
            "model_reference": "agents.agent-executor.model_ref",
            "input_revisions": {"queue": 0, "task": 3},
            "approval_references": ["APR-TASK-DBG-1"],
            "evidence": {"reason": "repair investigation", "architecture_owner": "primary-agent"},
            "review_contract": REVIEW_CONTRACT,
            "run_id": "RUN-DBG-1",
            "attempt_id": "ATTEMPT-DBG-1",
        }
        if investigation_id is not None:
            value["investigation_id"] = investigation_id
        return value

    def dispatch(self, project: Path, investigation_id: str | None = None) -> subprocess.CompletedProcess[str]:
        input_path = self.write_json(project / "dispatch.json", self.dispatch_payload(investigation_id))
        return run_script(
            "dispatch_task.py", "--project-root", str(project), "--input", str(input_path),
            "--deployment", str(ROOT / "skills/agentic-configuration/config/deployment.test.json"),
        )

    def handoff_payload(self, *, investigation_id: str | None = None) -> dict[str, object]:
        value: dict[str, object] = {
            "run_id": "RUN-DBG-1",
            "attempt_id": "ATTEMPT-DBG-1",
            "dispatch_id": "DISPATCH-DBG-1",
            "from_role": "executor",
            "to_role": "task-reviewer",
            "task_revision": 4,
            "plan_revision": 1,
            "input_artifact_hashes": {"task": "a" * 64},
            "output_artifact_hashes": {"handoff": "b" * 64},
            "evidence": {"summary": "repair verified"},
            "status": "COMPLETE",
            "summary": "implemented repair",
            "files_read": [],
            "files_changed": [],
            "findings": [],
            "implementation_details": [],
            "validation_results": [{"command": "python -m unittest", "result": "PASS"}],
            "risks": [],
            "next_steps": [],
        }
        if investigation_id is not None:
            value["investigation_id"] = investigation_id
        return value

    def handoff(self, project: Path, *, investigation_id: str | None = None) -> subprocess.CompletedProcess[str]:
        input_path = self.write_json(project / "handoff-input.json", self.handoff_payload(investigation_id=investigation_id))
        return run_script("create_handoff.py", "--project-root", str(project), "--task-id", self.task_id, "--input", str(input_path))

    def test_repair_dispatch_requires_investigation_and_preserves_runtime(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        task_before = (project / ".agent/work/T-DBG-1/task-state.json").read_bytes()
        queue_before = (project / ".agent/runtime/queue.json").read_bytes()
        result = self.dispatch(project)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DISPATCH_REJECTED", result.stderr)
        self.assertEqual((project / ".agent/work/T-DBG-1/task-state.json").read_bytes(), task_before)
        self.assertEqual((project / ".agent/runtime/queue.json").read_bytes(), queue_before)
        self.assertFalse((project / ".agent/work/T-DBG-1/lease.json").exists())

    def test_invalid_repair_investigation_is_rejected(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        missing = self.dispatch(project, "DBG-T-DBG-1-1")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("DISPATCH_REJECTED", missing.stderr)
        investigating = self.create_investigation(project, self.investigation_payload(status="INVESTIGATING", regression_status="NOT_RUN"))
        self.assertEqual(investigating.returncode, 0, investigating.stderr)
        result = self.dispatch(project, "DBG-T-DBG-1-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DISPATCH_REJECTED", result.stderr)

    def test_confirmed_investigation_is_persisted_through_dispatch_identity(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        created = self.create_investigation(project, self.investigation_payload())
        self.assertEqual(created.returncode, 0, created.stderr)
        result = self.dispatch(project, "DBG-T-DBG-1-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        queue = json.loads((project / ".agent/runtime/queue.json").read_text(encoding="utf-8"))
        task = json.loads((project / ".agent/work/T-DBG-1/task-state.json").read_text(encoding="utf-8"))
        lease = json.loads((project / ".agent/work/T-DBG-1/lease.json").read_text(encoding="utf-8"))
        dispatch = next(item for item in queue["dispatches"] if item["task_id"] == self.task_id)
        task_entry = next(item for item in queue["tasks"] if item["task_id"] == self.task_id)
        task_state_entry = next(item for item in queue["task_states"] if item["task_id"] == self.task_id)
        for record in (dispatch, task_entry, task_state_entry, task, lease):
            self.assertEqual(record["investigation_id"], "DBG-T-DBG-1-1")

    def test_complete_handoff_rejects_missing_id_and_failed_regression(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        created = self.create_investigation(project, self.investigation_payload(status="ROOT_CAUSE_CONFIRMED", regression_status="FAIL", exit_code=1))
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(self.dispatch(project, "DBG-T-DBG-1-1").returncode, 0)
        missing = self.handoff(project)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("HANDOFF_REJECTED", missing.stderr)
        self.assertFalse((project / ".agent/work/T-DBG-1/handoff.json").exists())
        failed = self.handoff(project, investigation_id="DBG-T-DBG-1-1")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("HANDOFF_REJECTED", failed.stderr)
        self.assertFalse((project / ".agent/work/T-DBG-1/handoff.json").exists())

    def test_complete_handoff_accepts_matching_passing_investigation(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        created = self.create_investigation(project, self.investigation_payload())
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(self.dispatch(project, "DBG-T-DBG-1-1").returncode, 0)
        result = self.handoff(project, investigation_id="DBG-T-DBG-1-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        handoff = json.loads((project / ".agent/work/T-DBG-1/handoff.json").read_text(encoding="utf-8"))
        self.assertEqual(handoff["investigation_id"], "DBG-T-DBG-1-1")

    def test_investigation_can_record_post_dispatch_regression_evidence(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        initial = self.create_investigation(
            project,
            self.investigation_payload(status="ROOT_CAUSE_CONFIRMED", regression_status="NOT_RUN"),
        )
        self.assertEqual(initial.returncode, 0, initial.stderr)
        self.assertEqual(self.dispatch(project, "DBG-T-DBG-1-1").returncode, 0)

        completed = self.create_investigation(project, self.investigation_payload())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        artifact = json.loads((project / ".agent/work/T-DBG-1/debug-investigation.json").read_text(encoding="utf-8"))
        self.assertEqual(artifact["revision"], 2)
        self.assertEqual(artifact["task_revision"], 4)
        self.assertEqual(artifact["regression_check"]["status"], "PASS")
        self.assertEqual(self.handoff(project, investigation_id="DBG-T-DBG-1-1").returncode, 0)

    def test_complete_handoff_rejects_stale_workspace_evidence(self) -> None:
        directory, project = self.setUpProject()
        self.addCleanup(directory.cleanup)
        created = self.create_investigation(project, self.investigation_payload())
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(self.dispatch(project, "DBG-T-DBG-1-1").returncode, 0)
        path = project / ".agent/work/T-DBG-1/debug-investigation.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        artifact["regression_check"]["workspace_hash"] = "0" * 64
        path.write_text(json.dumps(artifact), encoding="utf-8")
        result = self.handoff(project, investigation_id="DBG-T-DBG-1-1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HANDOFF_REJECTED", result.stderr)
        self.assertFalse((project / ".agent/work/T-DBG-1/handoff.json").exists())


if __name__ == "__main__":
    unittest.main()
