from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "agentic-state-tools" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from create_context import normalize  # noqa: E402
from load_config import load_config  # noqa: E402
from reissue_task_attempt import _meaningful_context_delta, _resolve_model_dispatch, _sanitize_context_delta  # noqa: E402
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


class ContextAttemptIsolationTests(unittest.TestCase):
    def write_json(self, path: Path, value: object) -> Path:
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def base_context(self, task_id: str = "T-CONTEXT") -> dict:
        return {
            "task": {"task_id": task_id, "objective": "bounded implementation"},
            "required_documents": ["docs/task.md"],
            "code_context": {"files_to_read": ["src/app.py"], "symbols_to_inspect": [], "existing_patterns": []},
            "constraints": {"inherited": ["preserve API"], "task_specific": []},
            "review_history": [],
            "source_items": ["src/app.py"],
            "forbidden_scope": ["src/other.py"],
            "run_id": "RUN-1",
            "attempt_id": "ATTEMPT-1",
            "dispatch_id": "DISPATCH-1",
        }

    def test_fresh_attempt_gets_lineage_and_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            first = self.write_json(project / "first.json", self.base_context())
            result = run_script("create_context.py", "--project-root", str(project), "--input", str(first))
            self.assertEqual(result.returncode, 0, result.stderr)
            first_saved = json.loads((project / ".agent/work/T-CONTEXT/context.json").read_text(encoding="utf-8"))
            expected_hash = hashlib.sha256(json.dumps("src/app.py", separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            self.assertEqual(first_saved["source_hashes"], [expected_hash])
            second_payload = self.base_context()
            second_payload.update({"run_id": "RUN-2", "attempt_id": "ATTEMPT-2", "dispatch_id": "DISPATCH-2", "context_delta": {"debugging_evidence": "new failing test"}})
            second_payload["previous_context_id"] = first_saved["context_id"]
            second = self.write_json(project / "second.json", second_payload)
            result = run_script("create_context.py", "--project-root", str(project), "--input", str(second))
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads((project / ".agent/work/T-CONTEXT/context.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["context_revision"], 2)
            self.assertEqual(saved["previous_context_id"], first_saved["context_id"])
            self.assertEqual(saved["attempt_id"], "ATTEMPT-2")
            self.assertTrue((project / ".agent/work/T-CONTEXT/contexts" / f"{saved['context_id']}.json").is_file())

    def test_reviewer_context_rejects_private_reasoning_and_hash_mismatch(self) -> None:
        payload = self.base_context()
        payload["recipient_role"] = "REVIEWER"
        payload["Internal_Reasoning"] = "do not persist"
        with self.assertRaisesRegex(ValueError, "private reasoning"):
            normalize(payload)

        clean = self.base_context()
        clean["source_hashes"] = ["0" * 64]
        with self.assertRaisesRegex(ValueError, "source_hashes"):
            normalize(clean)

        sensitive = self.base_context()
        sensitive["source_items"] = [".env"]
        with self.assertRaisesRegex(ValueError, "sensitive path"):
            normalize(sensitive)

    def test_bound_task_requires_complete_context_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            state = {
                "task_id": "T-CONTEXT",
                "status": "RUNNING",
                "run_id": "RUN-1",
                "attempt_id": "ATTEMPT-1",
                "dispatch_id": "DISPATCH-1",
            }
            write_validated(str(project), "work/T-CONTEXT/task-state.json", state, SCRIPTS.parent / "schemas/task-state.schema.json")
            payload = self.base_context()
            payload.pop("run_id")
            payload.pop("attempt_id")
            payload.pop("dispatch_id")
            input_path = self.write_json(project / "unbound.json", payload)
            result = run_script("create_context.py", "--project-root", str(project), "--input", str(input_path))
            self.assertEqual(result.returncode, 1)
            self.assertIn("active task run_id", result.stderr)

    def test_reissue_requires_meaningful_delta(self) -> None:
        self.assertFalse(_meaningful_context_delta(None))
        self.assertFalse(_meaningful_context_delta({"debugging_evidence": ""}))
        self.assertTrue(_meaningful_context_delta({"debugging_evidence": "new regression result"}))
        self.assertTrue(_meaningful_context_delta({"model_escalation": {"from": "context", "to": "implementation"}}))

        config = load_config()
        with self.assertRaisesRegex(ValueError, "private reasoning"):
            _sanitize_context_delta({"debugging_evidence": {"Internal_Reasoning": "private"}}, config)
        with self.assertRaisesRegex(ValueError, "sensitive"):
            _sanitize_context_delta({"added_context": {"token": "secret-value"}}, config)

        deployment = ROOT / "skills" / "agentic-configuration" / "config" / "deployment.test.json"
        with self.assertRaisesRegex(ValueError, "not allowed"):
            _resolve_model_dispatch("forbidden-legacy", {"agent_role": "agent-executor"}, config, str(deployment))

    def test_reissue_with_context_creates_fresh_identity_bound_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            state = {
                "task_id": "T-REISSUE-CONTEXT",
                "status": "REPAIR_REQUIRED",
                "revision": 1,
                "previous_revision": 0,
                "updated_at": "2026-08-05T00:00:00Z",
                "run_id": "RUN-1",
                "attempt_id": "ATTEMPT-1",
                "dispatch_id": "DISPATCH-1",
            }
            write_validated(str(project), "work/T-REISSUE-CONTEXT/task-state.json", state, SCRIPTS.parent / "schemas/task-state.schema.json")
            queue = {
                "schema_version": 1,
                "queue_id": "Q-REISSUE-CONTEXT",
                "revision": 1,
                "tasks": [{"task_id": "T-REISSUE-CONTEXT", "queue_state": "DISPATCHED", "execution_mode": "SYNC", "dependency_snapshot": {"depends_on": [], "accepted_task_ids": []}, "scope_snapshot": {"write_scope": ["src/app.py"]}, "owner": "executor", "revision": 1, "run_id": "RUN-1", "attempt_id": "ATTEMPT-1", "dispatch_id": "DISPATCH-1"}],
                "task_states": [{"task_id": "T-REISSUE-CONTEXT", "status": "REPAIR_REQUIRED", "revision": 1, "run_id": "RUN-1", "attempt_id": "ATTEMPT-1", "dispatch_id": "DISPATCH-1"}],
                "dispatches": [{"task_id": "T-REISSUE-CONTEXT", "dispatch_id": "DISPATCH-1", "run_id": "RUN-1", "attempt_id": "ATTEMPT-1", "task_revision": 1, "plan_revision": 1, "worktree_path": "C:/work/T-REISSUE-CONTEXT", "branch_name": "agent/T-REISSUE-CONTEXT"}],
                "locks": [],
            }
            self.write_json(project / ".agent/runtime/queue.json", queue)
            self.write_json(project / ".agent/work/T-REISSUE-CONTEXT/lease.json", {"task_id": "T-REISSUE-CONTEXT", "owner": "executor", "run_id": "RUN-1", "attempt_id": "ATTEMPT-1", "dispatch_id": "DISPATCH-1", "task_revision": 1, "acquired_at": "2026-08-05T00:00:00Z", "last_heartbeat": "2026-08-05T00:00:00Z", "lease_seconds": 300, "expires_at": "2099-01-01T00:00:00Z"})
            context = self.base_context("T-REISSUE-CONTEXT")
            context.update({"run_id": "RUN-1", "attempt_id": "ATTEMPT-1", "dispatch_id": "DISPATCH-1"})
            context_path = self.write_json(project / "context.json", context)
            self.assertEqual(run_script("create_context.py", "--project-root", str(project), "--input", str(context_path)).returncode, 0)
            old_context = json.loads((project / ".agent/work/T-REISSUE-CONTEXT/context.json").read_text(encoding="utf-8"))

            missing_delta = self.write_json(project / "missing-delta.json", {"task_id": "T-REISSUE-CONTEXT", "reason": "repair", "new_run_id": "RUN-2", "new_attempt_id": "ATTEMPT-2", "new_dispatch_id": "DISPATCH-2", "expected_revision": 1})
            result = run_script("reissue_task_attempt.py", "--project-root", str(project), "--input", str(missing_delta))
            self.assertEqual(result.returncode, 1)
            self.assertIn("context_delta", result.stderr)

            valid = self.write_json(project / "valid-reissue.json", {"task_id": "T-REISSUE-CONTEXT", "reason": "new debugging evidence", "new_run_id": "RUN-2", "new_attempt_id": "ATTEMPT-2", "new_dispatch_id": "DISPATCH-2", "expected_revision": 1, "context_delta": {"debugging_evidence": "regression reproduced"}})
            result = run_script("reissue_task_attempt.py", "--project-root", str(project), "--input", str(valid))
            self.assertEqual(result.returncode, 0, result.stderr)
            new_context = json.loads((project / ".agent/work/T-REISSUE-CONTEXT/context.json").read_text(encoding="utf-8"))
            self.assertEqual(new_context["previous_context_id"], old_context["context_id"])
            self.assertEqual(new_context["context_revision"], old_context["context_revision"] + 1)
            self.assertEqual(new_context["attempt_id"], "ATTEMPT-2")
            self.assertEqual(new_context["context_delta"], {"debugging_evidence": "regression reproduced"})


if __name__ == "__main__":
    unittest.main()
