from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
CONFIG_VALUE = json.loads(
    (SKILL_ROOT.parent / "agentic-configuration" / "config" / "agentic-config.yaml").read_text(encoding="utf-8")
)
EXECUTOR_MODEL = CONFIG_VALUE["agents"]["agent-executor"]["model_dispatch"]


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def init_git_project(project: Path) -> None:
    (project / ".gitignore").write_text(".agent/\n", encoding="utf-8")
    (project / "src").mkdir()
    (project / "src/feature.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True, text=True)


def planning_bundle() -> dict:
    return {
        "master_plan": {
            "plan_id": "MP-V1",
            "version": "1.0",
            "title": "V1 runtime",
            "objective": "Validate the integrated runtime",
            "requirements": [{"requirement_id": "REQ-1", "description": "Runtime is auditable"}],
            "in_scope": ["runtime"],
            "out_of_scope": ["distributed state"],
            "architecture": "Model A with Primary-controlled routing",
            "workstreams": ["runtime"],
            "milestones": ["release gate"],
            "dependencies": [],
            "constraints": ["Python standard library"],
            "success_criteria": ["REQ-1"],
            "risks": [],
            "completion_conditions": ["all tests pass"],
        },
        "sub_plans": [{
            "sub_plan_id": "SP-V1",
            "master_plan_id": "MP-V1",
            "version": "1.0",
            "title": "Runtime sub-plan",
            "objective": "Exercise runtime",
            "dependencies": [],
            "outputs": ["evidence"],
            "batches": ["B-V1"],
            "risks": [],
        }],
        "batches": [{
            "batch_id": "B-V1",
            "sub_plan_id": "SP-V1",
            "version": "1.0",
            "objective": "Run workflow",
            "depends_on": [],
            "tasks": ["T-V1"],
            "integration_criteria": ["workflow passes"],
            "definition_of_done": ["review accepted"],
            "review_profile": "personal",
            "commit_conditions": ["batch passes"],
        }],
        "tasks": [{
            "task_id": "T-V1",
            "batch_id": "B-V1",
            "version": "1.0",
            "title": "Run V1 workflow",
            "objective": "Exercise runtime",
            "context": "Integrated test",
            "depends_on": [],
            "execution_mode": "auto",
            "task_type": "backend",
            "requirement_ids": ["REQ-1"],
            "read_scope": ["skills/agentic-state-tools/"],
            "write_scope": ["src/feature.py"],
            "inputs": [],
            "required_outputs": ["review"],
            "acceptance_criteria": ["workflow passes"],
            "verification": ["python run_tests.py"],
            "out_of_scope": ["remote state"],
            "risk_flags": {"architecture_change": False},
            "blocker_policy": {"hard_blockers": ["failed verification"]},
            "execution_budget": {"max_files_changed": 2, "max_new_dependencies": 0, "allow_schema_change": False, "allow_architecture_change": False},
            "architecture_decisions": [],
        }],
        "decisions": [],
        "assumptions": [],
        "risks": [],
        "change_requests": [],
    }


class V1WorkflowTests(unittest.TestCase):
    def test_bundled_v1_examples_exist_for_release_gate(self) -> None:
        examples = SKILL_ROOT / "examples"
        for name in ("v1-planning-bundle.json", "v1-dispatch.json", "v1-recovery.json"):
            self.assertTrue((examples / name).is_file(), name)

    def test_planning_to_recovery_integrated_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            init_git_project(project)
            planning = write_json(project / "planning.json", planning_bundle())
            result = run_script("validate_planning.py", "--input", str(planning))
            self.assertEqual(result.returncode, 0, result.stderr)

            rubric = project / "task-rubric.json"
            result = run_script("resolve_rubric.py", "--profile", "personal", "--task-type", "backend", "--risk-flags", "{}", "--output", str(rubric))
            self.assertEqual(result.returncode, 0, result.stderr)
            task_rubric = json.loads(rubric.read_text(encoding="utf-8"))
            queue = write_json(project / "queue.json", {"tasks": [{"task_id": "T-V1", "status": "READY", "depends_on": [], "execution_mode": "auto", "write_scope": ["src/feature.py"]}]})
            result = run_script("resolve_runnable_tasks.py", "--input", str(queue))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["runnable"][0]["execution_mode"], "ASYNC")

            init = run_script("init_runtime.py", "--project-root", str(project))
            self.assertEqual(init.returncode, 0, init.stderr)
            approval = write_json(project / "approval.json", {"target_type": "TASK", "target_id": "T-V1", "decision": "APPROVED", "approver": "primary-agent", "evidence": "task contract accepted"})
            self.assertEqual(run_script("record_approval.py", "--project-root", str(project), "--input", str(approval)).returncode, 0)
            dispatch = write_json(project / "dispatch.json", {"dispatch_id": "DSP-V1", "task_id": "T-V1", "agent_role": "agent-executor", "selected_mode": "ASYNC", "selected_owner": "primary-agent", "selected_model": EXECUTOR_MODEL, "input_revisions": {"queue": 1, "task": 0}, "approval_references": ["APR-TASK-T-V1-1"], "evidence": {"reason": "independent", "architecture_owner": "primary-agent"}})
            dispatched = run_script("dispatch_task.py", "--input", str(dispatch))
            self.assertEqual(dispatched.returncode, 0, dispatched.stderr)

            queued = write_json(project / "queued.json", {"task_id": "T-V1", "batch_id": "B-V1", "title": "V1", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            running = write_json(project / "running.json", {"task_id": "T-V1", "status": "RUNNING", "expected_revision": 1})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(running)).returncode, 0)
            lock = write_json(project / "lock.json", {"kind": "file", "key": "src/feature.py", "task_id": "T-V1", "run_id": "RUN-V1", "owner": "executor", "lease_seconds": 120})
            self.assertEqual(run_script("acquire_lock.py", "--project-root", str(project), "--input", str(lock)).returncode, 0)
            heartbeat = write_json(project / "heartbeat.json", {"task_id": "T-V1", "owner": "executor", "run_id": "RUN-V1", "lease_seconds": 120})
            self.assertEqual(run_script("record_heartbeat.py", "--project-root", str(project), "--input", str(heartbeat)).returncode, 0)
            (project / "src/feature.py").write_text("value = 2\n", encoding="utf-8")
            checkpoint = write_json(project / "checkpoint.json", {"task_id": "T-V1", "current_step": "verify", "pending_steps": ["review"], "resume_safe": True, "files_modified": ["src/feature.py"]})
            self.assertEqual(run_script("create_checkpoint.py", "--project-root", str(project), "--input", str(checkpoint)).returncode, 0)
            (project / "unexpected.py").write_text("unexpected = True\n", encoding="utf-8")
            recovery = run_script("inspect_recovery.py", "--project-root", str(project), "--task-id", "T-V1")
            self.assertEqual(recovery.returncode, 0, recovery.stderr)
            recovery_value = json.loads(recovery.stdout)["results"][0]
            self.assertEqual(recovery_value["classification"], "NEEDS_RECONCILIATION")
            (project / "unexpected.py").unlink()

            completed = write_json(project / "completed.json", {"task_id": "T-V1", "status": "COMPLETED", "expected_revision": 2})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(completed)).returncode, 0)
            criteria = [{"id": criterion_id, "score": 4, "weight": weight, "mandatory": True, "minimum_score": 3, "applicability": "APPLICABLE", "evidence": "verification passed"} for criterion_id, weight in task_rubric["resolved_weights"].items()]
            review = write_json(project / "review.json", {"review_id": "REV-T-V1", "task_id": "T-V1", "resolved_rubric": task_rubric, "criteria": criteria, "findings": []})
            reviewed = run_script("create_review.py", "--project-root", str(project), "--input", str(review))
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
            batch_rubric = project / "batch-rubric.json"
            result = run_script("resolve_rubric.py", "--profile", "personal", "--task-type", "standard", "--review-type", "batch", "--risk-flags", "{}", "--output", str(batch_rubric))
            self.assertEqual(result.returncode, 0, result.stderr)
            batch = write_json(project / "batch-review.json", {"batch_id": "B-V1", "task_reviews": ["REV-T-V1"], "integration_checks": [{"name": "v1", "result": "PASS", "evidence": "integrated workflow passed"}], "findings": [], "resolved_rubric": json.loads(batch_rubric.read_text(encoding="utf-8"))})
            batch_result = run_script("create_batch_review.py", "--project-root", str(project), "--input", str(batch))
            self.assertEqual(batch_result.returncode, 0, batch_result.stderr)
            self.assertIn("BATCH_REVIEW_WRITTEN", batch_result.stdout)
            self.assertEqual(run_script("validate_state.py", "--project-root", str(project)).returncode, 0)

    def test_v1_faults_are_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            result = run_script("init_runtime.py", "--project-root", str(project))
            self.assertEqual(result.returncode, 0, result.stderr)
            queued = write_json(project / "queued.json", {"task_id": "T-V1", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            stale = write_json(project / "stale.json", {"task_id": "T-V1", "status": "RUNNING", "expected_revision": 0})
            self.assertNotEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(stale)).returncode, 0)
            rejected = write_json(project / "rejected.json", {"task_id": "T-V1", "status": "ACCEPTED", "expected_revision": 1})
            self.assertNotEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(rejected)).returncode, 0)
            malformed_event = write_json(project / "event.json", {"type": "UNKNOWN_EVENT", "actor": "primary-agent"})
            result = run_script("append_event.py", "--project-root", str(project), "--input", str(malformed_event))
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
            operation = write_json(project / "operation.json", {"task_id": "T-V1", "run_id": "RUN-V1", "type": "OTHER", "status": "STARTED", "command": "external"})
            self.assertEqual(run_script("record_operation.py", "--project-root", str(project), "--input", str(operation)).returncode, 0)
            result = run_script("inspect_recovery.py", "--project-root", str(project), "--task-id", "T-V1")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"classification": "NEEDS_RECONCILIATION"', result.stdout)


if __name__ == "__main__":
    unittest.main()
