from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from write_artifact import write_validated  # noqa: E402


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
        env=os.environ.copy(),
    )


class ContractHardeningTests(unittest.TestCase):
    def write_json(self, path: Path, value: dict[str, object]) -> Path:
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def identity(self) -> dict[str, object]:
        return {
            "task_id": "T-ID-1",
            "plan_id": "MP-1",
            "plan_revision": 4,
            "batch_id": "B-1",
            "requirement_ids": ["REQ-1"],
            "depends_on": [],
            "read_scope": ["src/"],
            "write_scope": ["src/app.py"],
            "review_contract": {
                "project_profile": "production",
                "profile_hash": "b" * 64,
                "task_type": "backend",
                "risk_flags": {},
                "review_type": "task",
                "rubric_id": "R-1",
                "rubric_version": "1",
                "rubric_hash": "a" * 64,
                "review_policy_version": "1",
            },
            "run_id": "RUN-1",
            "attempt_id": "ATTEMPT-1",
            "dispatch_id": "DISPATCH-1",
            "worktree_path": "C:/work/T-ID-1",
            "branch_name": "agent/T-ID-1-r4",
            "input_artifact_hashes": {"plan": "b" * 64},
        }

    def initialize_task(self, project: Path) -> None:
        self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
        queued = self.identity()
        queued.update(
            {
                "title": "identity regression",
                "status": "QUEUED",
                "revision": 1,
                "previous_revision": 0,
                "updated_at": "2026-08-03T00:00:00Z",
            }
        )
        write_validated(
            str(project),
            "work/T-ID-1/task-state.json",
            queued,
            SCHEMAS / "task-state.schema.json",
        )

    def test_mutable_only_transitions_retain_every_identity_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.initialize_task(project)
            expected_identity = self.identity()

            for revision, status, mutable in (
                (1, "RUNNING", {"progress": 40, "checkpoint": {"step": "implementation"}}),
                (2, "COMPLETED", {"progress": 100, "result_summary": "complete", "output_artifact_hashes": {"result": "c" * 64}}),
            ):
                payload = {"task_id": "T-ID-1", "status": status, "expected_revision": revision, **mutable}
                input_path = self.write_json(project / f"{status.lower()}.json", payload)
                result = run_script("update_task_state.py", "--project-root", str(project), "--input", str(input_path))
                self.assertEqual(result.returncode, 0, result.stderr)
                state = json.loads((project / ".agent/work/T-ID-1/task-state.json").read_text(encoding="utf-8"))
                self.assertEqual({field: state[field] for field in expected_identity}, expected_identity)

            state = json.loads((project / ".agent/work/T-ID-1/task-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "COMPLETED")
            self.assertEqual(state["revision"], 3)
            self.assertEqual(state["previous_revision"], 2)
            self.assertEqual(state["progress"], 100)
            self.assertEqual(state["result_summary"], "complete")

    def test_immutable_identity_changes_are_rejected_without_writing(self) -> None:
        immutable_changes = {
            "run_id": "RUN-CHANGED",
            "attempt_id": "ATTEMPT-CHANGED",
            "dispatch_id": "DISPATCH-CHANGED",
            "plan_revision": 5,
            "write_scope": ["src/other.py"],
            "input_artifact_hashes": {"plan": "c" * 64},
        }
        for field, changed in immutable_changes.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.initialize_task(project)
                target = project / ".agent/work/T-ID-1/task-state.json"
                before = target.read_bytes()
                payload = {"task_id": "T-ID-1", "status": "RUNNING", "expected_revision": 1, field: changed}
                input_path = self.write_json(project / "invalid.json", payload)
                result = run_script("update_task_state.py", "--project-root", str(project), "--input", str(input_path))
                self.assertEqual(result.returncode, 1)
                self.assertIn("TASK_STATE_REJECTED", result.stderr)
                self.assertEqual(target.read_bytes(), before)

    def test_new_immutable_identity_field_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            current = {"task_id": "T-MISSING-ID", "status": "QUEUED", "revision": 1, "previous_revision": 0, "updated_at": "2026-08-03T00:00:00Z"}
            write_validated(str(project), "work/T-MISSING-ID/task-state.json", current, SCHEMAS / "task-state.schema.json")
            target = project / ".agent/work/T-MISSING-ID/task-state.json"
            before = target.read_bytes()
            update = self.write_json(project / "invalid-new-identity.json", {"task_id": "T-MISSING-ID", "status": "RUNNING", "expected_revision": 1, "plan_id": "MP-NEW"})
            result = run_script("update_task_state.py", "--project-root", str(project), "--input", str(update))
            self.assertEqual(result.returncode, 1)
            self.assertIn("TASK_STATE_REJECTED", result.stderr)
            self.assertEqual(target.read_bytes(), before)

    def test_handoff_rejects_wrong_run_and_attempt_identity(self) -> None:
        base_handoff = {
            "attempt_id": "ATTEMPT-1",
            "from_role": "executor",
            "to_role": "task-reviewer",
            "task_revision": 1,
            "plan_revision": 4,
            "input_artifact_hashes": {"plan": "b" * 64},
            "output_artifact_hashes": {"handoff": "c" * 64},
            "evidence": {"summary": "identity check"},
            "status": "COMPLETE",
            "summary": "ready for review",
            "files_read": [],
            "files_changed": [],
            "findings": [],
            "implementation_details": [],
            "validation_results": [],
            "risks": [],
            "next_steps": [],
        }
        for field, value in (("run_id", "RUN-WRONG"), ("attempt_id", "ATTEMPT-WRONG")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.initialize_task(project)
                payload = dict(base_handoff)
                payload["run_id"] = "RUN-1"
                payload[field] = value
                input_path = self.write_json(project / "handoff.json", payload)
                result = run_script("create_handoff.py", "--project-root", str(project), "--task-id", "T-ID-1", "--input", str(input_path))
                self.assertEqual(result.returncode, 1)
                self.assertIn("HANDOFF_REJECTED", result.stderr)

    def test_executor_cannot_mark_task_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.initialize_task(project)
            accepted = self.write_json(
                project / "accepted.json",
                {"task_id": "T-ID-1", "status": "ACCEPTED", "expected_revision": 1},
            )
            result = run_script("update_task_state.py", "--project-root", str(project), "--input", str(accepted))
            self.assertEqual(result.returncode, 1)
            self.assertIn("TASK_STATE_REJECTED", result.stderr)

    def test_attempt_reissue_schema_separates_identity_changes(self) -> None:
        schema = json.loads((SCHEMAS / "attempt-reissue.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            schema["required"],
            ["task_id", "reason", "new_run_id", "new_attempt_id", "new_dispatch_id", "expected_revision"],
        )
        self.assertIn("expected_revision", schema["properties"])
        self.assertIn("expected_revision", schema["required"])

    def _prepare_reissue_project(self, project: Path) -> None:
        self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
        state = self.identity()
        state.update({"status": "REPAIR_REQUIRED", "revision": 1, "previous_revision": 0, "updated_at": "2026-08-03T00:00:00Z"})
        write_validated(str(project), "work/T-ID-1/task-state.json", state, SCHEMAS / "task-state.schema.json")
        old_identity = {field: state[field] for field in ("run_id", "attempt_id", "dispatch_id")}
        queue = {
            "schema_version": 1,
            "queue_id": "Q-1",
            "revision": 1,
            "tasks": [{"task_id": "T-ID-1", "queue_state": "DISPATCHED", "execution_mode": "SYNC", "dependency_snapshot": {"depends_on": [], "accepted_task_ids": []}, "scope_snapshot": {"write_scope": ["src/app.py"]}, "owner": "executor", "revision": 1, **old_identity}],
            "task_states": [{"task_id": "T-ID-1", "status": "REPAIR_REQUIRED", "revision": 1, **old_identity}],
            "dispatches": [{"task_id": "T-ID-1", "dispatch_id": "DISPATCH-1", "run_id": "RUN-1", "attempt_id": "ATTEMPT-1", "task_revision": 1, "plan_revision": 4, "worktree_path": "C:/work/T-ID-1", "branch_name": "agent/T-ID-1-r4"}],
            "locks": [],
        }
        self.write_json(project / ".agent/runtime/queue.json", queue)
        lease = {"task_id": "T-ID-1", "owner": "executor", "run_id": "RUN-1", "attempt_id": "ATTEMPT-1", "dispatch_id": "DISPATCH-1", "task_revision": 1, "acquired_at": "2026-08-03T00:00:00Z", "last_heartbeat": "2026-08-03T00:00:00Z", "lease_seconds": 300, "expires_at": "2099-01-01T00:00:00Z"}
        self.write_json(project / ".agent/work/T-ID-1/lease.json", lease)

    def test_reissue_requires_expected_revision_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._prepare_reissue_project(project)
            reissue = self.write_json(project / "reissue-missing-revision.json", {"task_id": "T-ID-1", "reason": "stale executor", "new_run_id": "RUN-2", "new_attempt_id": "ATTEMPT-2", "new_dispatch_id": "DISPATCH-2"})
            result = run_script("reissue_task_attempt.py", "--project-root", str(project), "--input", str(reissue))
            self.assertEqual(result.returncode, 1)
            self.assertIn("TASK_REISSUE_REJECTED", result.stderr)

    def test_reissue_changes_all_durable_execution_bindings_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._prepare_reissue_project(project)
            old_identity = {"run_id": "RUN-1", "attempt_id": "ATTEMPT-1", "dispatch_id": "DISPATCH-1"}
            reissue = self.write_json(
                project / "reissue.json",
                {"task_id": "T-ID-1", "reason": "stale executor", "new_run_id": "RUN-2", "new_attempt_id": "ATTEMPT-2", "new_dispatch_id": "DISPATCH-2", "expected_revision": 1},
            )

            result = run_script("reissue_task_attempt.py", "--project-root", str(project), "--input", str(reissue))
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = json.loads((project / ".agent/work/T-ID-1/task-state.json").read_text(encoding="utf-8"))
            self.assertEqual({field: updated[field] for field in old_identity}, {"run_id": "RUN-2", "attempt_id": "ATTEMPT-2", "dispatch_id": "DISPATCH-2"})
            updated_queue = json.loads((project / ".agent/runtime/queue.json").read_text(encoding="utf-8"))
            for collection in ("tasks", "task_states", "dispatches"):
                record = next(item for item in updated_queue[collection] if item.get("task_id") == "T-ID-1")
                self.assertEqual({field: record[field] for field in old_identity}, {"run_id": "RUN-2", "attempt_id": "ATTEMPT-2", "dispatch_id": "DISPATCH-2"})
                self.assertEqual(record["revision"], updated["revision"])
                if collection == "dispatches":
                    self.assertEqual(record["task_revision"], updated["revision"])
            updated_lease = json.loads((project / ".agent/work/T-ID-1/lease.json").read_text(encoding="utf-8"))
            self.assertEqual({field: updated_lease[field] for field in old_identity}, {"run_id": "RUN-2", "attempt_id": "ATTEMPT-2", "dispatch_id": "DISPATCH-2"})
            self.assertEqual(updated_lease["task_revision"], updated["revision"])
            operations = (project / ".agent/work/T-ID-1/operations.jsonl").read_text(encoding="utf-8")
            self.assertIn("REISSUE_TASK_ATTEMPT", operations)


if __name__ == "__main__":
    unittest.main()
