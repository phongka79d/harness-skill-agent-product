from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from write_artifact import write_validated  # noqa: E402
import reissue_task_attempt  # noqa: E402
from update_task_state import synchronize_queue  # noqa: E402


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
DEPLOYMENT_PATH = SKILL_ROOT.parent / "agentic-configuration" / "config" / "deployment.test.json"
EXECUTOR_MODEL = json.loads(DEPLOYMENT_PATH.read_text(encoding="utf-8"))["model_ids"]["implementation"]


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
    def test_queued_transition_synchronizes_queue_enum_and_revision(self) -> None:
        queue = {
            "schema_version": 1,
            "queue_id": "Q-1",
            "revision": 3,
            "tasks": [{"task_id": "T-1", "queue_state": "READY", "execution_mode": "SYNC", "dependency_snapshot": {"depends_on": [], "accepted_task_ids": []}, "scope_snapshot": {"write_scope": []}, "owner": "executor", "revision": 1}],
            "task_states": [{"task_id": "T-1", "status": "READY", "revision": 1}],
            "dispatches": [],
        }
        result = synchronize_queue(queue, {"task_id": "T-1", "status": "QUEUED", "revision": 2})
        self.assertEqual(result["revision"], 4)
        self.assertEqual(result["tasks"][0]["queue_state"], "DISPATCHED")
        self.assertEqual(result["tasks"][0]["revision"], 2)
        self.assertEqual(result["task_states"][0]["status"], "QUEUED")
        self.assertEqual(result["task_states"][0]["revision"], 2)

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

    def test_rich_heartbeat_and_checkpoint_persist_all_execution_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.initialize_task(project)
            running = self.write_json(project / "running-rich.json", {"task_id": "T-ID-1", "status": "RUNNING", "expected_revision": 1})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(running)).returncode, 0)
            heartbeat = self.write_json(project / "heartbeat-rich.json", {"task_id": "T-ID-1", "owner": "executor", "lease_seconds": 60})
            self.assertEqual(run_script("record_heartbeat.py", "--project-root", str(project), "--input", str(heartbeat)).returncode, 0)
            lease = json.loads((project / ".agent/work/T-ID-1/lease.json").read_text(encoding="utf-8"))
            self.assertEqual({field: lease[field] for field in ("run_id", "attempt_id", "dispatch_id")}, {field: self.identity()[field] for field in ("run_id", "attempt_id", "dispatch_id")})
            checkpoint = self.write_json(project / "checkpoint-rich.json", {"task_id": "T-ID-1", "current_step": "verify", "pending_steps": []})
            self.assertEqual(run_script("create_checkpoint.py", "--project-root", str(project), "--input", str(checkpoint)).returncode, 0)
            saved = json.loads((project / ".agent/work/T-ID-1/checkpoint.json").read_text(encoding="utf-8"))
            for field in ("run_id", "attempt_id", "dispatch_id"):
                self.assertEqual(saved[field], self.identity()[field])
            self.assertEqual(saved["task_revision"], 2)
            self.assertEqual(saved["input_artifact_hashes"], self.identity()["input_artifact_hashes"])

            lease["dispatch_id"] = "DISPATCH-WRONG"
            (project / ".agent/work/T-ID-1/lease.json").write_text(json.dumps(lease), encoding="utf-8")
            rejected_checkpoint = self.write_json(
                project / "checkpoint-wrong-lease.json",
                {"task_id": "T-ID-1", "current_step": "verify", "pending_steps": []},
            )
            checkpoint_result = run_script("create_checkpoint.py", "--project-root", str(project), "--input", str(rejected_checkpoint))
            self.assertNotEqual(checkpoint_result.returncode, 0)
            self.assertIn("dispatch_id", checkpoint_result.stderr)
            rejected = run_script("record_heartbeat.py", "--project-root", str(project), "--input", str(heartbeat))
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("dispatch_id", rejected.stderr)

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

    def test_reissue_accepts_cli_only_expected_revision_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._prepare_reissue_project(project)
            reissue = self.write_json(project / "reissue-cli-only.json", {"task_id": "T-ID-1", "reason": "stale executor", "new_run_id": "RUN-2", "new_attempt_id": "ATTEMPT-2", "new_dispatch_id": "DISPATCH-2"})
            result = run_script("reissue_task_attempt.py", "--project-root", str(project), "--input", str(reissue), "--expected-revision", "1")
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = json.loads((project / ".agent/work/T-ID-1/task-state.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["revision"], 2)

    def test_reissue_rejects_conflicting_cli_and_payload_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._prepare_reissue_project(project)
            reissue = self.write_json(project / "reissue-conflict.json", {"task_id": "T-ID-1", "reason": "stale executor", "new_run_id": "RUN-2", "new_attempt_id": "ATTEMPT-2", "new_dispatch_id": "DISPATCH-2", "expected_revision": 2})
            result = run_script("reissue_task_attempt.py", "--project-root", str(project), "--input", str(reissue), "--expected-revision", "1")
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
                record = next(item for item in updated_queue[collection] if item.get("task_id") == "T-ID-1" and item.get("dispatch_id") == "DISPATCH-2")
                self.assertEqual({field: record[field] for field in old_identity}, {"run_id": "RUN-2", "attempt_id": "ATTEMPT-2", "dispatch_id": "DISPATCH-2"})
                if collection == "dispatches":
                    self.assertEqual(record["task_revision"], updated["revision"])
                else:
                    self.assertEqual(record["revision"], updated["revision"])
            updated_lease = json.loads((project / ".agent/work/T-ID-1/lease.json").read_text(encoding="utf-8"))
            self.assertEqual({field: updated_lease[field] for field in old_identity}, {"run_id": "RUN-2", "attempt_id": "ATTEMPT-2", "dispatch_id": "DISPATCH-2"})
            self.assertEqual(updated_lease["task_revision"], updated["revision"])
            operations = (project / ".agent/work/T-ID-1/operations.jsonl").read_text(encoding="utf-8")
            self.assertIn("REISSUE_TASK_ATTEMPT", operations)

    def test_reissue_preserves_historical_dispatches_and_appends_current_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._prepare_reissue_project(project)
            queue_path = project / ".agent/runtime/queue.json"
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            current_dispatch = queue["dispatches"][0]
            current_dispatch.update(
                {"idempotency_key": "T-ID-1:current", "operation_id": "OP-T-ID-1-CURRENT"}
            )
            historical_dispatch = {
                "task_id": "T-ID-1",
                "dispatch_id": "DISPATCH-HISTORICAL",
                "run_id": "RUN-HISTORICAL",
                "attempt_id": "ATTEMPT-HISTORICAL",
                "task_revision": 0,
                "idempotency_key": "T-ID-1:historical",
                "operation_id": "OP-T-ID-1-HISTORICAL",
                "plan_revision": 4,
                "worktree_path": "C:/work/T-ID-1",
                "branch_name": "agent/T-ID-1-r4",
            }
            queue["dispatches"] = [historical_dispatch, current_dispatch]
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            original_dispatches = json.loads(json.dumps(queue["dispatches"]))
            reissue = self.write_json(
                project / "reissue-with-history.json",
                {"task_id": "T-ID-1", "reason": "stale executor", "new_run_id": "RUN-2", "new_attempt_id": "ATTEMPT-2", "new_dispatch_id": "DISPATCH-2", "expected_revision": 1},
            )

            result = run_script("reissue_task_attempt.py", "--project-root", str(project), "--input", str(reissue))
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = json.loads((project / ".agent/work/T-ID-1/task-state.json").read_text(encoding="utf-8"))
            updated_queue = json.loads(queue_path.read_text(encoding="utf-8"))

            self.assertEqual(updated_queue["dispatches"][:2], original_dispatches)
            self.assertEqual(len(updated_queue["dispatches"]), 3)
            appended = updated_queue["dispatches"][2]
            self.assertEqual(
                {field: appended[field] for field in ("run_id", "attempt_id", "dispatch_id")},
                {"run_id": "RUN-2", "attempt_id": "ATTEMPT-2", "dispatch_id": "DISPATCH-2"},
            )
            self.assertEqual(appended["task_revision"], updated["revision"])
            self.assertNotEqual(appended["idempotency_key"], current_dispatch["idempotency_key"])
            self.assertNotEqual(appended["operation_id"], current_dispatch["operation_id"])

            running = self.write_json(
                project / "running.json",
                {"task_id": "T-ID-1", "status": "RUNNING", "expected_revision": updated["revision"], "progress": 40},
            )
            transition = run_script("update_task_state.py", "--project-root", str(project), "--input", str(running))
            self.assertEqual(transition.returncode, 0, transition.stderr)
            current_state = json.loads((project / ".agent/work/T-ID-1/task-state.json").read_text(encoding="utf-8"))
            self.assertEqual(current_state["status"], "RUNNING")
            self.assertEqual(
                {field: current_state[field] for field in ("run_id", "attempt_id", "dispatch_id")},
                {"run_id": "RUN-2", "attempt_id": "ATTEMPT-2", "dispatch_id": "DISPATCH-2"},
            )
            updated_queue = json.loads(queue_path.read_text(encoding="utf-8"))
            task_entry = next(item for item in updated_queue["tasks"] if item.get("task_id") == "T-ID-1")
            state_entry = next(item for item in updated_queue["task_states"] if item.get("task_id") == "T-ID-1")
            active_dispatch = next(item for item in updated_queue["dispatches"] if item.get("dispatch_id") == "DISPATCH-2")
            self.assertEqual(task_entry["revision"], current_state["revision"])
            self.assertEqual(state_entry["revision"], current_state["revision"])
            self.assertEqual(active_dispatch["task_revision"], current_state["revision"])
            self.assertEqual(json.loads((project / ".agent/work/T-ID-1/lease.json").read_text(encoding="utf-8"))["task_revision"], current_state["revision"])

    def test_reissue_rejects_identity_reuse_from_dispatch_history(self) -> None:
        for field, value in (("new_run_id", "RUN-1"), ("new_attempt_id", "ATTEMPT-1"), ("new_dispatch_id", "DISPATCH-1")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self._prepare_reissue_project(project)
                reissue = self.write_json(
                    project / f"reissue-reused-{field}.json",
                    {"task_id": "T-ID-1", "reason": "identity reuse", "new_run_id": "RUN-2", "new_attempt_id": "ATTEMPT-2", "new_dispatch_id": "DISPATCH-2", "expected_revision": 1, field: value},
                )
                result = run_script("reissue_task_attempt.py", "--project-root", str(project), "--input", str(reissue))
                self.assertEqual(result.returncode, 1)
                self.assertIn(field.removeprefix("new_"), result.stderr)

    def _prepare_dispatch_retry(self, project: Path) -> Path:
        self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
        task = {
            "task_id": "T-DISPATCH-RETRY",
            "title": "dispatch retry identity",
            "status": "QUEUED",
            "revision": 1,
            "previous_revision": 0,
            "updated_at": "2026-08-03T00:00:00Z",
        }
        write_validated(str(project), "work/T-DISPATCH-RETRY/task-state.json", task, SCHEMAS / "task-state.schema.json")
        return self.write_json(
            project / "dispatch.json",
            {
                "dispatch_id": "DISPATCH-RETRY",
                "task_id": "T-DISPATCH-RETRY",
                "agent_role": "agent-executor",
                "selected_mode": "SYNC",
                "selected_owner": "primary-agent",
                "selected_model": EXECUTOR_MODEL,
                "input_revisions": {"task": 1, "queue": 0},
                "approval_references": [],
                "evidence": {"reason": "retry identity", "architecture_owner": "primary-agent"},
                "plan_revision": 4,
                "worktree_path": "C:/work/T-DISPATCH-RETRY",
                "branch_name": "agent/T-DISPATCH-RETRY-r4",
                "input_artifact_hashes": {"plan": "b" * 64},
                "idempotency_key": "dispatch-retry-identity",
            },
        )

    def test_dispatch_retry_rejects_conflicting_supplied_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            dispatch_path = self._prepare_dispatch_retry(project)
            first = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch_path), "--deployment", str(DEPLOYMENT_PATH))
            self.assertEqual(first.returncode, 0, first.stderr)
            retry = json.loads(dispatch_path.read_text(encoding="utf-8"))
            retry["run_id"] = "RUN-CONFLICT"
            retry_path = self.write_json(project / "retry-run-conflict.json", retry)

            result = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(retry_path), "--deployment", str(DEPLOYMENT_PATH))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("run_id", result.stderr)

    def test_dispatch_retry_rejects_conflicting_supplied_attempt_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            dispatch_path = self._prepare_dispatch_retry(project)
            first = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch_path), "--deployment", str(DEPLOYMENT_PATH))
            self.assertEqual(first.returncode, 0, first.stderr)
            retry = json.loads(dispatch_path.read_text(encoding="utf-8"))
            retry["attempt_id"] = "ATTEMPT-CONFLICT"
            retry_path = self.write_json(project / "retry-attempt-conflict.json", retry)

            result = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(retry_path), "--deployment", str(DEPLOYMENT_PATH))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("attempt_id", result.stderr)

    def test_dispatch_retry_accepts_omitted_legacy_bindings_and_rejects_changed_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            dispatch_path = self._prepare_dispatch_retry(project)
            first = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch_path), "--deployment", str(DEPLOYMENT_PATH))
            self.assertEqual(first.returncode, 0, first.stderr)

            retry = json.loads(dispatch_path.read_text(encoding="utf-8"))
            retry_result = run_script(
                "dispatch_task.py", "--project-root", str(project), "--input", str(self.write_json(project / "retry.json", retry)), "--deployment", str(DEPLOYMENT_PATH)
            )
            self.assertEqual(retry_result.returncode, 0, retry_result.stderr)

            retry["plan_revision"] = 99
            changed = self.write_json(project / "retry-plan-conflict.json", retry)
            result = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(changed), "--deployment", str(DEPLOYMENT_PATH))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("plan_revision", result.stderr)

    def test_reissue_failure_restores_events_snapshot_and_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._prepare_reissue_project(project)
            payload = self.write_json(
                project / "reissue-failure.json",
                {"task_id": "T-ID-1", "reason": "append failure", "new_run_id": "RUN-2", "new_attempt_id": "ATTEMPT-2", "new_dispatch_id": "DISPATCH-2", "expected_revision": 1},
            )
            root = project / ".agent"
            before = {name: (root / name).read_bytes() for name in ("runtime/events.jsonl", "runtime/state.json", "checklist.md")}
            before_task = json.loads((root / "work/T-ID-1/task-state.json").read_text(encoding="utf-8"))
            before_queue = json.loads((root / "runtime/queue.json").read_text(encoding="utf-8"))
            before_lease = json.loads((root / "work/T-ID-1/lease.json").read_text(encoding="utf-8"))
            original_append = reissue_task_attempt.append_event_for_root
            calls = 0

            def fail_second_append(runtime_root, event):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("controlled append failure")
                return original_append(runtime_root, event)

            with patch.object(reissue_task_attempt, "append_event_for_root", side_effect=fail_second_append), patch.object(
                sys, "argv", ["reissue_task_attempt.py", "--project-root", str(project), "--input", str(payload)]
            ):
                self.assertEqual(reissue_task_attempt.main(), 1)

            self.assertEqual(json.loads((root / "work/T-ID-1/task-state.json").read_text(encoding="utf-8")), before_task)
            self.assertEqual(json.loads((root / "runtime/queue.json").read_text(encoding="utf-8")), before_queue)
            self.assertEqual(json.loads((root / "work/T-ID-1/lease.json").read_text(encoding="utf-8")), before_lease)
            for name, content in before.items():
                self.assertEqual((root / name).read_bytes(), content)
            self.assertIn("FAILED", (root / "work/T-ID-1/operations.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
