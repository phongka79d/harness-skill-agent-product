from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPTS / name), *args]
    try:
        return subprocess.run(command, cwd=str(SCRIPTS), text=True, capture_output=True, timeout=15)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=exc.stdout or "",
            stderr=f"TIMEOUT: {name} exceeded 15 seconds",
        )


class ReportGapTests(unittest.TestCase):
    def write_json(self, path: Path, value: object) -> Path:
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def init_project(self, directory: str) -> Path:
        project = Path(directory)
        result = run_script("init_runtime.py", "--project-root", str(project))
        self.assertEqual(result.returncode, 0, result.stderr)
        return project

    def advance_to_completed(self, project: Path) -> None:
        for revision, status in enumerate(("QUEUED", "RUNNING", "COMPLETED")):
            payload = {"task_id": "T-001", "title": "Example", "status": status}
            if revision:
                payload["expected_revision"] = revision
            input_path = self.write_json(project / f"{status.lower()}.json", payload)
            result = run_script("update_task_state.py", "--project-root", str(project), "--input", str(input_path))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_planning_validator_accepts_contracts_and_rejects_scope_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            valid = {
                "master_plan": {
                    "plan_id": "MP-001",
                    "version": "1.0",
                    "title": "Runtime",
                    "objective": "Build runtime",
                    "requirements": [{"requirement_id": "REQ-1", "description": "Validate plans"}],
                    "in_scope": ["contracts"],
                    "out_of_scope": ["dashboard"],
                    "architecture": "Primary controlled",
                    "workstreams": ["runtime"],
                    "milestones": ["M1"],
                    "dependencies": [],
                    "constraints": [],
                    "success_criteria": ["REQ-1"],
                    "risks": [],
                    "completion_conditions": ["tests pass"],
                },
                "sub_plans": [{
                    "sub_plan_id": "SP-001",
                    "master_plan_id": "MP-001",
                    "version": "1.0",
                    "title": "Runtime",
                    "objective": "Implement runtime",
                    "dependencies": [],
                    "outputs": ["contracts"],
                    "batches": ["B-001"],
                    "risks": [],
                }],
                "batches": [{
                    "batch_id": "B-001",
                    "sub_plan_id": "SP-001",
                    "version": "1.0",
                    "objective": "Add contracts",
                    "depends_on": [],
                    "tasks": ["T-001"],
                    "integration_criteria": ["validator runs"],
                    "definition_of_done": ["tests pass"],
                    "review_profile": "quick_change",
                    "commit_conditions": ["review passes"],
                }],
                "tasks": [{
                    "task_id": "T-001",
                    "batch_id": "B-001",
                    "version": "1.0",
                    "title": "Add validator",
                    "objective": "Validate plans",
                    "context": "Runtime package",
                    "depends_on": [],
                    "execution_mode": "sync",
                    "task_type": "tooling",
                    "requirement_ids": ["REQ-1"],
                    "read_scope": ["skills/"],
                    "write_scope": ["skills/agentic-state-tools/"],
                    "inputs": [],
                    "required_outputs": ["validator"],
                    "acceptance_criteria": ["Reject overlap"],
                    "verification": ["unit test"],
                    "out_of_scope": [],
                    "risk_flags": {"architecture_change": False},
                    "blocker_policy": {"hard_blockers": []},
                    "execution_budget": {"max_files_changed": 5, "max_new_dependencies": 0, "allow_schema_change": True, "allow_architecture_change": False},
                    "architecture_decisions": [],
                }],
                "decisions": [],
                "assumptions": [],
                "risks": [],
                "change_requests": [],
            }
            input_path = self.write_json(Path(directory) / "planning.json", valid)
            result = run_script("validate_planning.py", "--input", str(input_path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PLANNING_VALID", result.stdout)

            invalid = json.loads(input_path.read_text(encoding="utf-8"))
            invalid["tasks"].append({**invalid["tasks"][0], "task_id": "T-002"})
            invalid["batches"][0]["tasks"].append("T-002")
            invalid_path = self.write_json(Path(directory) / "invalid-planning.json", invalid)
            result = run_script("validate_planning.py", "--input", str(invalid_path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("overlapping write scope", result.stderr)

    def test_profile_and_rubric_resolvers_emit_immutable_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = run_script("resolve_project_profile.py", "--profile", "personal")
            self.assertEqual(profile.returncode, 0, profile.stderr)
            profile_value = json.loads(profile.stdout)
            self.assertEqual(profile_value["profile_id"], "personal")
            self.assertRegex(profile_value["profile_hash"], r"^[0-9a-f]{64}$")

            rubric = run_script(
                "resolve_rubric.py",
                "--profile",
                "personal",
                "--task-type",
                "quick_change",
                "--risk-flags",
                '{"external_input":true}',
            )
            self.assertEqual(rubric.returncode, 0, rubric.stderr)
            rubric_value = json.loads(rubric.stdout)
            self.assertTrue(rubric_value["rubric_id"])
            self.assertRegex(rubric_value["rubric_hash"], r"^[0-9a-f]{64}$")
            self.assertIn("resolved_weights", rubric_value)
            self.assertIn("applicability", rubric_value)

    def test_review_score_rejects_criteria_that_do_not_match_resolved_rubric(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rubric_result = run_script("resolve_rubric.py", "--profile", "personal", "--task-type", "quick_change")
            self.assertEqual(rubric_result.returncode, 0, rubric_result.stderr)
            rubric = json.loads(rubric_result.stdout)
            criteria = [
                {"id": criterion_id, "score": 4, "weight": weight, "mandatory": True, "minimum_score": 3, "applicability": "APPLICABLE", "evidence": "targeted test passed"}
                for criterion_id, weight in rubric["resolved_weights"].items()
            ]
            review = {
                "review_id": "REV-T-001",
                "task_id": "T-001",
                "resolved_rubric": rubric,
                "criteria": criteria,
                "findings": [],
            }
            input_path = self.write_json(Path(directory) / "review.json", review)
            result = run_script("calculate_rubric_score.py", "--input", str(input_path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"verdict": "PASS"', result.stdout)

            review["criteria"][0]["weight"] = 99
            invalid_path = self.write_json(Path(directory) / "invalid-review.json", review)
            result = run_script("calculate_rubric_score.py", "--input", str(invalid_path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match resolved rubric", result.stderr)

    def test_terminal_review_clears_action_and_owned_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.init_project(directory)
            self.advance_to_completed(project)
            reviewing = self.write_json(
                project / "reviewing.json",
                {"task_id": "T-001", "title": "Example", "status": "REVIEWING", "expected_revision": 3},
            )
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(reviewing)).returncode, 0)
            heartbeat = self.write_json(
                project / "heartbeat.json",
                {"task_id": "T-001", "owner": "executor", "run_id": "RUN-001", "lease_seconds": 60},
            )
            self.assertEqual(run_script("record_heartbeat.py", "--project-root", str(project), "--input", str(heartbeat)).returncode, 0)
            lock = self.write_json(
                project / "lock.json",
                {"kind": "task", "key": "T-001", "task_id": "T-001", "run_id": "RUN-001", "owner": "executor", "lease_seconds": 60},
            )
            self.assertEqual(run_script("acquire_lock.py", "--project-root", str(project), "--input", str(lock)).returncode, 0)
            review = self.write_json(
                project / "review.json",
                {
                    "review_id": "REV-T-001",
                    "task_id": "T-001",
                    "legacy_migration": True,
                    "criteria": [{"id": "CORRECTNESS", "score": 4, "weight": 100, "mandatory": True, "evidence": "test passed"}],
                    "findings": [],
                },
            )
            result = run_script("create_review.py", "--project-root", str(project), "--input", str(review))
            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads((project / ".agent/work/T-001/task-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "ACCEPTED")
            self.assertEqual(state.get("next_action"), "none")
            self.assertFalse((project / ".agent/work/T-001/lease.json").exists())
            self.assertEqual(list((project / ".agent/locks/tasks").glob("*.json")), [])

    def test_expired_named_lock_is_reclaimed_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.init_project(directory)
            payload = self.write_json(
                project / "lock.json",
                {"kind": "resource", "key": "shared", "run_id": "RUN-001", "owner": "dead", "lease_seconds": 60},
            )
            self.assertEqual(run_script("acquire_lock.py", "--project-root", str(project), "--input", str(payload)).returncode, 0)
            lock_path = next((project / ".agent/locks/resources").glob("*.json"))
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["expires_at"] = "2000-01-01T00:00:00Z"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            replacement = self.write_json(
                project / "replacement.json",
                {"kind": "resource", "key": "shared", "run_id": "RUN-002", "owner": "new", "lease_seconds": 60},
            )
            result = run_script("acquire_lock.py", "--project-root", str(project), "--input", str(replacement))
            self.assertEqual(result.returncode, 0, result.stderr)
            journal = (project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8")
            self.assertIn("LOCK_RECLAIMED", journal)

    def test_recovery_detects_git_workspace_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "src").mkdir()
            (project / ".gitignore").write_text(".agent/\n", encoding="utf-8")
            (project / "src/example.py").write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True, text=True)
            base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, check=True, capture_output=True, text=True).stdout.strip()
            self.init_project(directory)
            queued = self.write_json(project / "queued.json", {"task_id": "T-001", "title": "Example", "status": "QUEUED"})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(queued)).returncode, 0)
            running = self.write_json(project / "resume.json", {"task_id": "T-001", "status": "RUNNING", "expected_revision": 1})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(running)).returncode, 0)
            checkpoint = self.write_json(
                project / "checkpoint.json",
                {"task_id": "T-001", "current_step": "resume", "pending_steps": ["verify"], "resume_safe": True, "base_commit": base_commit, "files_modified": ["src/example.py"]},
            )
            self.assertEqual(run_script("create_checkpoint.py", "--project-root", str(project), "--input", str(checkpoint)).returncode, 0)
            heartbeat = self.write_json(project / "heartbeat.json", {"task_id": "T-001", "owner": "executor", "run_id": "RUN-001", "lease_seconds": 60})
            self.assertEqual(run_script("record_heartbeat.py", "--project-root", str(project), "--input", str(heartbeat)).returncode, 0)
            (project / "src/other.py").write_text("unexpected = True\n", encoding="utf-8")
            result = run_script("inspect_recovery.py", "--project-root", str(project), "--task-id", "T-001")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"classification": "NEEDS_RECONCILIATION"', result.stdout)
            self.assertIn("workspace", result.stdout)

    def test_handoff_accepts_reconciliation_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self.init_project(directory)
            handoff = self.write_json(
                project / "handoff.json",
                {"status": "NEEDS_RECONCILIATION", "summary": "workspace differs", "files_read": [], "files_changed": [], "findings": [], "implementation_details": [], "validation_results": [], "risks": ["workspace mismatch"], "next_steps": ["inspect diff"]},
            )
            result = run_script("create_handoff.py", "--project-root", str(project), "--task-id", "T-001", "--input", str(handoff))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_runnable_task_resolver_respects_dependencies_and_scope_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = {
                "tasks": [
                    {"task_id": "T-001", "status": "ACCEPTED", "depends_on": [], "execution_mode": "auto", "write_scope": ["src/a.py"]},
                    {"task_id": "T-002", "status": "READY", "depends_on": ["T-001"], "execution_mode": "auto", "write_scope": ["src/d.py"]},
                    {"task_id": "T-003", "status": "READY", "depends_on": ["T-999"], "execution_mode": "auto", "write_scope": ["src/c.py"]},
                    {"task_id": "T-004", "status": "READY", "depends_on": [], "execution_mode": "auto", "write_scope": ["src/b.py"]},
                ],
                "active_write_scopes": ["src/b.py"],
            }
            input_path = self.write_json(Path(directory) / "queue.json", queue)
            result = run_script("resolve_runnable_tasks.py", "--input", str(input_path))
            self.assertEqual(result.returncode, 0, result.stderr)
            resolved = json.loads(result.stdout)
            self.assertEqual([item["task_id"] for item in resolved["runnable"]], ["T-002"])
            self.assertEqual(resolved["runnable"][0]["execution_mode"], "ASYNC")
            self.assertIn("T-003", resolved["blocked_task_ids"])
            self.assertIn("T-004", resolved["conflicted_task_ids"])

    def test_approval_schema_and_wiki_routing_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            approval = self.write_json(
                Path(directory) / "approval.json",
                {"approval_id": "APR-001", "target_type": "MASTER_PLAN", "target_id": "MP-001", "decision": "APPROVED", "approver": "primary", "evidence": "plan review passed", "created_at": "2026-08-02T00:00:00Z", "revision": 1},
            )
            result = run_script("validate_payload.py", "--input", str(approval), "--schema", str(SKILL_ROOT / "schemas/approval.schema.json"))
            self.assertEqual(result.returncode, 0, result.stderr)
            project = self.init_project(directory)
            result = run_script("record_approval.py", "--project-root", str(project), "--input", str(approval))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((project / ".agent/approvals/MASTER_PLAN-MP-001.json").is_file())
            wiki = (SKILL_ROOT.parent / "agentic-engineering-core" / "references" / "wiki.md")
            self.assertTrue(wiki.is_file())
            self.assertIn("validate_planning.py", wiki.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
