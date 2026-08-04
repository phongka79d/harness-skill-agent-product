from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from write_artifact import write_validated  # noqa: E402
import authorization  # noqa: E402
import reissue_task_attempt  # noqa: E402
import create_batch_contract  # noqa: E402
import commit_batch  # noqa: E402
import dispatch_task  # noqa: E402
from create_batch_contract import _resolve_documents  # noqa: E402
from create_batch_review import load_batch_contract  # noqa: E402
from commit_batch import CommitRejected, validate_batch_contract_pin, validate_batch_review_artifact  # noqa: E402
from create_batch_review import artifact_hash as batch_review_artifact_hash  # noqa: E402
from update_task_state import synchronize_queue  # noqa: E402
from risk_flags import normalize_risk_flags  # noqa: E402
from resolve_rubric import resolve_rubric  # noqa: E402
from review_contract import contract_from_rubric  # noqa: E402
from validate_planning import validate_manifest, requirement_report  # noqa: E402


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
    def test_apply_change_request_synchronizes_master_plan_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.write_json(root / "change.json", {
                "change_request_id": "CR-1",
                "target_type": "MASTER_PLAN",
                "target_id": "MP-1",
                "target_version": "1.0",
                "reason": "Change plan objective",
                "requested_changes": [{"op": "replace", "path": "/title", "value": "Changed"}],
                "impact": {"risk_level": "low", "architecture_change": False},
                "status": "APPROVED",
                "requested_by": "primary-agent",
                "approval_id": "APR-1",
                "supersedes_id": "MP-1@1.0",
                "new_version": "1.1",
            })
            approval = self.write_json(root / "approval.json", {
                "approval_id": "APR-1",
                "target_type": "CHANGE_REQUEST",
                "target_id": "CR-1",
                "decision": "APPROVED",
            })
            target = self.write_json(root / "plan.json", {
                "plan_id": "MP-1",
                "version": "1.0",
                "revision": 4,
                "title": "Original",
                "master_plan": {"plan_id": "MP-1", "revision": 4, "title": "Original"},
            })
            output = root / "changed-plan.json"

            result = run_script(
                "apply_change_request.py",
                "--request", str(request),
                "--target", str(target),
                "--approval", str(approval),
                "--output", str(output),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            changed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(changed["revision"], 5)
            self.assertEqual(changed["master_plan"]["revision"], 5)

    def test_master_plan_authorization_requires_primary_agent(self) -> None:
        target = {
            "target_type": "MASTER_PLAN",
            "target_id": "MP-1",
            "revision": 1,
            "target_hash": "a" * 64,
        }
        approval = {
            "approval_id": "APR-MP-1",
            "target_type": "MASTER_PLAN",
            "target_id": "MP-1",
            "decision": "APPROVED",
            "approver": "agent-1",
            "actor_type": "agent",
            "actor_id": "agent-1",
            "action": "MASTER_PLAN",
            "target_revision": 1,
            "target_hash": "a" * 64,
            "policy_version": "1",
            "expires_at": "2099-01-01T00:00:00Z",
            "evidence": "forged plan approval",
        }
        with self.assertRaises(authorization.AuthorizationError):
            authorization.authorize(
                "MASTER_PLAN",
                target,
                approval,
                actor={"actor_type": "agent", "actor_id": "agent-1"},
            )

    def test_batch_contract_master_plan_approval_uses_shared_authorizer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".agent"
            approval = {
                "approval_id": "APR-MP-1",
                "target_type": "MASTER_PLAN",
                "target_id": "MP-1",
                "decision": "APPROVED",
                "approver": "primary-agent",
                "actor_type": "primary_agent",
                "actor_id": "primary-agent",
                "action": "MASTER_PLAN",
                "target_revision": 1,
                "target_hash": "a" * 64,
                "policy_version": "1",
                "expires_at": "2099-01-01T00:00:00Z",
                "evidence": "approved plan",
            }
            approval_path = root / "approvals" / "MASTER_PLAN-MP-1.json"
            approval_path.parent.mkdir(parents=True)
            approval_path.write_text(json.dumps(approval), encoding="utf-8")

            with patch.object(create_batch_contract, "authorize", wraps=authorization.authorize) as authorizer:
                result = create_batch_contract._approval(root, "MP-1", 1, "a" * 64, "primary-agent")

            self.assertEqual(result, approval)
            authorizer.assert_called_once_with(
                "MASTER_PLAN",
                {
                    "target_type": "MASTER_PLAN",
                    "target_id": "MP-1",
                    "revision": 1,
                    "target_hash": "a" * 64,
                },
                approval,
                actor={"actor_type": "primary_agent", "actor_id": "primary-agent"},
            )

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

    def test_batch_contract_writer_cli_creates_canonical_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            plan = self.write_json(project / "planning.json", {
                "master_plan": {
                    "plan_id": "MP-1", "revision": 1, "version": "1.0", "title": "Plan", "objective": "Test",
                    "requirements": [{"requirement_id": "REQ-1", "description": "Test"}],
                    "in_scope": ["src"], "out_of_scope": [], "architecture": "A",
                    "workstreams": ["runtime"], "milestones": ["m1"], "dependencies": [],
                    "constraints": [], "success_criteria": ["REQ-1"], "risks": [],
                    "completion_conditions": ["tests pass"],
                },
                "sub_plans": [{
                    "sub_plan_id": "SP-1", "master_plan_id": "MP-1", "version": "1.0",
                    "title": "Sub", "objective": "Test", "dependencies": [], "outputs": ["x"],
                    "batches": ["B-1"], "risks": [],
                }],
                "batches": [{
                    "batch_id": "B-1", "sub_plan_id": "SP-1", "version": "1.0",
                    "objective": "Test", "depends_on": [], "tasks": ["T-1"],
                    "integration_criteria": ["pass"], "definition_of_done": ["done"],
                    "review_profile": "personal", "commit_conditions": ["approved"],
                }],
                "tasks": [{
                    "task_id": "T-1", "batch_id": "B-1", "version": "1.0", "title": "Task", "owner": "agent-executor",
                    "objective": "Test", "context": "Test", "depends_on": [], "execution_mode": "sync",
                    "task_type": "backend", "requirement_ids": ["REQ-1"], "read_scope": ["src"],
                    "write_scope": ["src/app.py"], "inputs": [], "required_outputs": ["result"],
                    "acceptance_criteria": [{"criterion_id": "AC-1", "text": "pass", "requirement_ids": ["REQ-1"]}], "verification": ["tests"], "out_of_scope": [],
                    "risk_flags": {}, "blocker_policy": {"hard_blockers": []},
                    "execution_budget": {"max_files_changed": 1, "max_new_dependencies": 0,
                        "allow_schema_change": False, "allow_architecture_change": False},
                    "architecture_decisions": [],
                }],
                "decisions": [], "assumptions": [], "risks": [], "change_requests": [],
            })
            missing_revision_plan = json.loads(plan.read_text(encoding="utf-8"))
            missing_revision_plan["master_plan"].pop("revision")
            missing_revision_path = self.write_json(project / "missing-revision-plan.json", missing_revision_plan)
            missing_revision = run_script(
                "create_batch_contract.py", "--project-root", str(project), "--plan", str(missing_revision_path),
                "--plan-id", "MP-1", "--plan-revision", "1", "--batch-id", "B-1",
                "--expected-revision", "0", "--actor", "primary-agent",
            )
            self.assertNotEqual(missing_revision.returncode, 0)
            self.assertIn("master_plan.revision", missing_revision.stderr)
            plan_hash = hashlib.sha256(json.dumps(json.loads(plan.read_text(encoding="utf-8")), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            approval = self.write_json(project / "approval.json", {
                "target_type": "MASTER_PLAN", "target_id": "MP-1", "decision": "APPROVED",
                "approver": "primary-agent", "actor_type": "primary_agent", "actor_id": "primary-agent",
                "action": "MASTER_PLAN", "target_revision": 1, "target_hash": plan_hash,
                "policy_version": "1", "expires_at": "2099-01-01T00:00:00Z", "evidence": "approved",
            })
            self.assertEqual(run_script("record_approval.py", "--project-root", str(project), "--input", str(approval)).returncode, 0)
            rubric_path = project / "task-rubric.json"
            self.assertEqual(run_script("resolve_rubric.py", "--profile", "personal", "--task-type", "backend", "--risk-flags", "{}", "--output", str(rubric_path)).returncode, 0)
            rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
            task_contract = {"project_profile": rubric["profile_id"], "profile_hash": rubric["profile_hash"], "task_type": rubric["task_type"], "risk_flags": rubric["risk_flags"], "review_type": rubric["review_type"], "rubric_id": rubric["rubric_id"], "rubric_version": rubric["rubric_version"], "rubric_hash": rubric["rubric_hash"], "review_policy_version": rubric["review_policy_version"]}
            task_state = {"task_id": "T-1", "batch_id": "B-1", "status": "COMPLETED", "revision": 1, "previous_revision": 0, "updated_at": "2026-08-03T00:00:00Z", "review_contract": task_contract}
            write_validated(str(project), "work/T-1/task-state.json", task_state, SCHEMAS / "task-state.schema.json")
            result = run_script(
                "create_batch_contract.py", "--project-root", str(project), "--plan", str(plan),
                "--plan-id", "MP-1", "--plan-revision", "1", "--batch-id", "B-1",
                "--expected-revision", "0", "--actor", "primary-agent",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            contract = json.loads((project / ".agent/work/B-1/batch-contract.json").read_text(encoding="utf-8"))
            self.assertEqual(contract["plan_id"], "MP-1")
            self.assertEqual(contract["batch_id"], "B-1")
            self.assertEqual([item["task_id"] for item in contract["tasks"]], ["T-1"])
            self.assertRegex(contract["contract_hash"], r"^[0-9a-f]{64}$")
            self.assertIn("BATCH_CONTRACT_CREATED", (project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8"))
            contract_path = project / ".agent/work/B-1/batch-contract.json"
            original_contract = contract_path.read_bytes()
            tampered_contract = dict(contract)
            tampered_contract["contract_hash"] = "0" * 64
            contract_path.write_text(json.dumps(tampered_contract), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_batch_contract(project / ".agent", "B-1")
            contract_path.write_bytes(original_contract)

            duplicate_contract = dict(contract)
            duplicate_contract["tasks"] = [
                dict(contract["tasks"][0]),
                {**contract["tasks"][0], "task_revision": 2},
            ]
            duplicate_contract["contract_hash"] = create_batch_contract.artifact_hash(duplicate_contract, "contract_hash")
            contract_path.write_text(json.dumps(duplicate_contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate task IDs"):
                load_batch_contract(project / ".agent", "B-1")
            contract_path.write_bytes(original_contract)

            stale_revision = run_script(
                "create_batch_contract.py", "--project-root", str(project), "--plan", str(plan),
                "--plan-id", "MP-1", "--plan-revision", "1", "--batch-id", "B-1",
                "--expected-revision", "0", "--actor", "primary-agent",
            )
            self.assertNotEqual(stale_revision.returncode, 0)
            self.assertIn("stale revision", stale_revision.stderr)

            wrong_actor = run_script(
                "create_batch_contract.py", "--project-root", str(project), "--plan", str(plan),
                "--plan-id", "MP-1", "--plan-revision", "1", "--batch-id", "B-1",
                "--expected-revision", "1", "--actor", "agent-executor",
            )
            self.assertNotEqual(wrong_actor.returncode, 0)
            self.assertIn("primary-agent", wrong_actor.stderr)

            changed_plan = json.loads(plan.read_text(encoding="utf-8"))
            changed_plan["batches"][0]["objective"] = "changed"
            changed_plan_path = self.write_json(project / "changed-plan.json", changed_plan)
            stale_approval = run_script(
                "create_batch_contract.py", "--project-root", str(project), "--plan", str(changed_plan_path),
                "--plan-id", "MP-1", "--plan-revision", "1", "--batch-id", "B-1",
                "--expected-revision", "1", "--actor", "primary-agent",
            )
            self.assertNotEqual(stale_approval.returncode, 0)
            self.assertIn("approval", stale_approval.stderr.lower())

            tracked_paths = [
                project / ".agent/work/B-1/batch-contract.json",
                project / ".agent/work/B-1/operations.jsonl",
                project / ".agent/runtime/events.jsonl",
                project / ".agent/runtime/state.json",
            ]
            before = {path: path.read_bytes() for path in tracked_paths}
            original_append = create_batch_contract.append_event_for_root
            calls = 0

            def fail_operation_event(root, event):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("controlled operation event failure")
                return original_append(root, event)

            with patch.object(create_batch_contract, "append_event_for_root", side_effect=fail_operation_event):
                with self.assertRaises(OSError):
                    create_batch_contract.create_batch_contract(
                        project, json.loads(plan.read_text(encoding="utf-8")), plan_id="MP-1",
                        plan_revision=1, batch_id="B-1", actor="primary-agent", expected_revision=1,
                    )
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content)

    def test_commit_boundary_rejects_stale_batch_contract_pin(self) -> None:
        current_contract = {"revision": 2, "contract_hash": "c" * 64, "review_contract": {}}
        review = {
            "verdict": "PASS",
            "batch_contract_revision": 1,
            "batch_contract_hash": "a" * 64,
        }
        with self.assertRaisesRegex(CommitRejected, "batch contract pin"):
            validate_batch_contract_pin(review, current_contract)
        matching_review = {
            **review,
            "batch_contract_revision": current_contract["revision"],
            "batch_contract_hash": current_contract["contract_hash"],
            "review_contract": current_contract["review_contract"],
        }
        self.assertIsNone(validate_batch_contract_pin(matching_review, current_contract))

    def test_batch_contract_loader_rejects_path_traversal_batch_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "batch_id"):
                load_batch_contract(Path(directory), "../B-1")

    def test_commit_cli_commits_approved_batch_and_records_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            source = project / "src/app.py"
            source.parent.mkdir(parents=True)
            source.write_text("value = 1\n", encoding="utf-8")

            task_dir = project / ".agent/work/T-1"
            task_dir.mkdir(parents=True)
            self.write_json(task_dir / "review.json", {
                "review_id": "REV-T-1",
                "task_id": "T-1",
                "verdict": "PASS",
            })
            self.write_json(task_dir / "task-state.json", {
                "task_id": "T-1",
                "status": "ACCEPTED",
            })
            batch_dir = project / ".agent/work/B-1"
            batch_dir.mkdir(parents=True)
            review = self.write_json(batch_dir / "review.json", {
                "review_id": "BATCH-REV-B-1-1",
                "batch_id": "B-1",
                "revision": 1,
                "task_reviews": ["REV-T-1"],
                "integration_checks": [
                    {"kind": "integration", "name": "integration", "result": "PASS", "evidence": "checked"},
                    {"kind": "regression", "name": "regression", "result": "PASS", "evidence": "checked"},
                    {"kind": "scope", "name": "scope", "result": "PASS", "evidence": "checked"},
                ],
                "findings": [],
                "scope_valid": True,
                "legacy_migration": True,
                "verdict": "PASS",
            })
            review_value = json.loads(review.read_text(encoding="utf-8"))
            review_value["artifact_hash"] = batch_review_artifact_hash(review_value)
            review.write_text(json.dumps(review_value), encoding="utf-8")
            approval = {
                "approval_id": "APR-B-1-COMMIT",
                "target_type": "BATCH",
                "target_id": "B-1",
                "decision": "APPROVED",
                "approver": "alice",
                "actor_type": "user",
                "actor_id": "alice",
                "action": "BATCH_COMMIT",
                "target_revision": 1,
                "target_hash": review_value["artifact_hash"],
                "policy_version": "1",
                "expires_at": "2099-01-01T00:00:00Z",
                "evidence": "batch review approved",
            }
            approval_path = project / ".agent/approvals/BATCH-B-1.json"
            approval_path.parent.mkdir(parents=True)
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            approval_input = self.write_json(project / "approval.json", approval)

            subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Codex Test"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.email", "codex-test@example.invalid"], cwd=project, check=True)
            with patch.dict(os.environ, {
                "GIT_AUTHOR_NAME": "Codex Test",
                "GIT_AUTHOR_EMAIL": "codex-test@example.invalid",
                "GIT_COMMITTER_NAME": "Codex Test",
                "GIT_COMMITTER_EMAIL": "codex-test@example.invalid",
            }):
                result = run_script(
                    "commit_batch.py",
                    "--project-root", str(project),
                    "--batch-id", "B-1",
                    "--approval", str(approval_input),
                    "--actor", "alice",
                    "--actor-type", "user",
                    "--message", "commit approved batch",
                    "--path", "src/app.py",
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"status": "COMMITTED"', result.stdout)
            commit_subject = subprocess.run(
                ["git", "log", "-1", "--format=%s"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(commit_subject, "commit approved batch")
            operations = [
                json.loads(line)
                for line in (batch_dir / "operations.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(any(item.get("status") == "COMPLETED" for item in operations))

    def test_commit_boundary_validates_current_batch_review_artifact(self) -> None:
        review = {
            "review_id": "BATCH-REV-B-1-1",
            "batch_id": "B-1",
            "task_reviews": ["REV-T-1"],
            "integration_checks": [
                {"kind": "integration", "name": "integration", "result": "PASS", "evidence": "checked"},
                {"kind": "regression", "name": "regression", "result": "PASS", "evidence": "checked"},
                {"kind": "scope", "name": "scope", "result": "PASS", "evidence": "checked"},
            ],
            "findings": [],
            "verdict": "PASS",
        }
        review["artifact_hash"] = batch_review_artifact_hash(review)
        self.assertIsNone(validate_batch_review_artifact(review, "B-1"))

        with self.assertRaisesRegex(CommitRejected, "batch_id"):
            validate_batch_review_artifact({**review, "batch_id": "B-2"}, "B-1")
        tampered_verdict = {**review, "verdict": "REPAIR_REQUIRED"}
        with self.assertRaisesRegex(CommitRejected, "artifact_hash"):
            validate_batch_review_artifact(tampered_verdict, "B-1")
        tampered_legacy_flag = {**review, "legacy_migration": True}
        with self.assertRaisesRegex(CommitRejected, "artifact_hash"):
            validate_batch_review_artifact(tampered_legacy_flag, "B-1")

    def test_commit_boundary_rejects_rehashed_pass_review_with_failing_integration_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            batch_dir = project / ".agent/work/B-1"
            batch_dir.mkdir(parents=True)
            review = {
                "review_id": "BATCH-REV-B-1-1",
                "batch_id": "B-1",
                "revision": 1,
                "task_reviews": [],
                "integration_checks": [
                    {"kind": "integration", "name": "integration", "result": "FAIL", "evidence": "integration failed"},
                    {"kind": "regression", "name": "regression", "result": "PASS", "evidence": "regression checked"},
                    {"kind": "scope", "name": "scope", "result": "PASS", "evidence": "scope checked"},
                ],
                "findings": [],
                "scope_valid": True,
                "legacy_migration": True,
                "verdict": "PASS",
            }
            review["artifact_hash"] = batch_review_artifact_hash(review)
            (batch_dir / "review.json").write_text(json.dumps(review), encoding="utf-8")
            approval = {
                "approval_id": "APR-B-1-COMMIT",
                "target_type": "BATCH",
                "target_id": "B-1",
                "decision": "APPROVED",
                "approver": "alice",
                "actor_type": "user",
                "actor_id": "alice",
                "action": "BATCH_COMMIT",
                "target_revision": 1,
                "target_hash": review["artifact_hash"],
                "policy_version": "1",
                "expires_at": "2099-01-01T00:00:00Z",
                "evidence": "batch review approved",
            }
            approval_path = project / ".agent/approvals/BATCH-B-1.json"
            approval_path.parent.mkdir(parents=True)
            approval_path.write_text(json.dumps(approval), encoding="utf-8")

            with self.assertRaisesRegex(CommitRejected, "integration check failed"):
                commit_batch.commit_batch(
                    project,
                    "B-1",
                    approval,
                    actor={"actor_type": "user", "actor_id": "alice"},
                    paths=["src/app.py"],
                    message="commit batch",
                    dry_run=True,
                )

    def test_commit_boundary_rejects_rehashed_review_with_mismatched_review_contract(self) -> None:
        review_contract = {
            "project_profile": "personal",
            "profile_hash": "a" * 64,
            "task_type": "standard",
            "risk_flags": {},
            "review_type": "batch",
            "rubric_id": "BATCH-1",
            "rubric_version": "1",
            "rubric_hash": "b" * 64,
            "review_policy_version": "1",
        }
        current_contract = {
            "revision": 2,
            "contract_hash": "c" * 64,
            "review_contract": review_contract,
        }
        review = {
            "review_id": "BATCH-REV-B-1-1",
            "batch_id": "B-1",
            "task_reviews": ["REV-T-1"],
            "integration_checks": [
                {"kind": "integration", "name": "integration", "result": "PASS", "evidence": "checked"},
                {"kind": "regression", "name": "regression", "result": "PASS", "evidence": "checked"},
                {"kind": "scope", "name": "scope", "result": "PASS", "evidence": "checked"},
            ],
            "findings": [],
            "verdict": "PASS",
            "batch_contract_revision": 2,
            "batch_contract_hash": "c" * 64,
            "review_contract": {**review_contract, "rubric_id": "BATCH-2"},
        }
        review["artifact_hash"] = batch_review_artifact_hash(review)
        self.assertIsNone(validate_batch_review_artifact(review, "B-1"))

        with self.assertRaisesRegex(CommitRejected, "review_contract"):
            validate_batch_contract_pin(review, current_contract)
        with self.assertRaisesRegex(CommitRejected, "review_contract"):
            validate_batch_contract_pin(review, current_contract, allow_legacy=False)

    def test_batch_contract_writer_rejects_invalid_or_mismatched_task_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            plan = self.write_json(project / "planning.json", {
                "master_plan": {
                    "plan_id": "MP-1", "revision": 1, "version": "1.0", "title": "Plan", "objective": "Test",
                    "requirements": [{"requirement_id": "REQ-1", "description": "Test"}],
                    "in_scope": ["src"], "out_of_scope": [], "architecture": "A", "workstreams": ["runtime"],
                    "milestones": ["m1"], "dependencies": [], "constraints": [], "success_criteria": ["REQ-1"],
                    "risks": [], "completion_conditions": ["tests pass"],
                },
                "sub_plans": [{
                    "sub_plan_id": "SP-1", "master_plan_id": "MP-1", "version": "1.0", "title": "Sub",
                    "objective": "Test", "dependencies": [], "outputs": ["x"], "batches": ["B-1"], "risks": [],
                }],
                "batches": [{
                    "batch_id": "B-1", "sub_plan_id": "SP-1", "version": "1.0", "objective": "Test",
                    "depends_on": [], "tasks": ["T-1"], "integration_criteria": ["pass"],
                    "definition_of_done": ["done"], "review_profile": "personal", "commit_conditions": ["approved"],
                }],
                "tasks": [{
                    "task_id": "T-1", "batch_id": "B-1", "version": "1.0", "title": "Task", "objective": "Test", "owner": "agent-executor",
                    "context": "Test", "depends_on": [], "execution_mode": "sync", "task_type": "backend",
                    "requirement_ids": ["REQ-1"], "read_scope": ["src"], "write_scope": ["src/app.py"],
                    "inputs": [], "required_outputs": ["result"], "acceptance_criteria": [{"criterion_id": "AC-1", "text": "pass", "requirement_ids": ["REQ-1"]}],
                    "verification": ["tests"], "out_of_scope": [], "risk_flags": {},
                    "blocker_policy": {"hard_blockers": []},
                    "execution_budget": {"max_files_changed": 1, "max_new_dependencies": 0,
                                         "allow_schema_change": False, "allow_architecture_change": False},
                    "architecture_decisions": [],
                }],
                "decisions": [], "assumptions": [], "risks": [], "change_requests": [],
            })
            plan_hash = hashlib.sha256(json.dumps(json.loads(plan.read_text(encoding="utf-8")), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            approval = self.write_json(project / "approval.json", {
                "target_type": "MASTER_PLAN", "target_id": "MP-1", "decision": "APPROVED",
                "approver": "primary-agent", "actor_type": "primary_agent", "actor_id": "primary-agent",
                "action": "MASTER_PLAN", "target_revision": 1, "target_hash": plan_hash,
                "policy_version": "1", "expires_at": "2099-01-01T00:00:00Z", "evidence": "approved",
            })
            self.assertEqual(run_script("record_approval.py", "--project-root", str(project), "--input", str(approval)).returncode, 0)
            rubric_path = project / "task-rubric.json"
            self.assertEqual(run_script("resolve_rubric.py", "--profile", "personal", "--task-type", "backend", "--risk-flags", "{}", "--output", str(rubric_path)).returncode, 0)
            rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
            task_contract = {
                "project_profile": rubric["profile_id"], "profile_hash": rubric["profile_hash"],
                "task_type": rubric["task_type"], "risk_flags": rubric["risk_flags"],
                "review_type": rubric["review_type"], "rubric_id": rubric["rubric_id"],
                "rubric_version": rubric["rubric_version"], "rubric_hash": rubric["rubric_hash"],
                "review_policy_version": rubric["review_policy_version"],
            }
            state = {"task_id": "T-1", "batch_id": "B-1", "status": "COMPLETED", "revision": 1,
                     "previous_revision": 0, "updated_at": "2026-08-03T00:00:00Z", "review_contract": task_contract}
            state_path = project / ".agent/work/T-1/task-state.json"
            write_validated(str(project), "work/T-1/task-state.json", state, SCHEMAS / "task-state.schema.json")

            invalid_state = dict(state)
            invalid_state.pop("status")
            state_path.write_text(json.dumps(invalid_state), encoding="utf-8")
            invalid = run_script(
                "create_batch_contract.py", "--project-root", str(project), "--plan", str(plan),
                "--plan-id", "MP-1", "--plan-revision", "1", "--batch-id", "B-1",
                "--expected-revision", "0", "--actor", "primary-agent",
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("task state is invalid", invalid.stderr)

            for field, value in (("task_id", "T-2"), ("batch_id", "B-2")):
                mismatched = dict(state)
                mismatched[field] = value
                state_path.write_text(json.dumps(mismatched), encoding="utf-8")
                result = run_script(
                    "create_batch_contract.py", "--project-root", str(project), "--plan", str(plan),
                    "--plan-id", "MP-1", "--plan-revision", "1", "--batch-id", "B-1",
                    "--expected-revision", "0", "--actor", "primary-agent",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("identity", result.stderr)

    def test_legacy_batch_review_pin_is_allowed_only_without_current_contract(self) -> None:
        legacy_review = {"legacy_migration": True}
        self.assertIsNone(validate_batch_contract_pin(legacy_review, None, allow_legacy=True))
        with self.assertRaisesRegex(CommitRejected, "batch contract pin"):
            validate_batch_contract_pin(legacy_review, {"revision": 1, "contract_hash": "a" * 64}, allow_legacy=False)

    def test_batch_contract_rejects_non_bidirectional_membership(self) -> None:
        base = {
            "master_plan": {"plan_id": "MP-1"},
            "sub_plans": [{"sub_plan_id": "SP-1", "master_plan_id": "MP-1", "batches": ["B-1"]}],
            "batches": [{"batch_id": "B-1", "sub_plan_id": "SP-1", "tasks": ["T-1"]}],
            "tasks": [{"task_id": "T-1", "batch_id": "B-1"}],
        }
        cases = {
            "missing task": lambda value: value["batches"][0].update({"tasks": ["T-MISSING"]}),
            "duplicate task": lambda value: value["batches"][0].update({"tasks": ["T-1", "T-1"]}),
            "wrong reverse membership": lambda value: value["tasks"][0].update({"batch_id": "B-2"}),
            "missing sub-plan membership": lambda value: value["sub_plans"][0].update({"batches": []}),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                value = json.loads(json.dumps(base))
                mutate(value)
                with self.assertRaises(ValueError):
                    _resolve_documents(value, "B-1")

    def test_batch_contract_rejects_incomplete_sub_plan_batch_membership(self) -> None:
        base = {
            "master_plan": {"plan_id": "MP-1"},
            "sub_plans": [{"sub_plan_id": "SP-1", "master_plan_id": "MP-1", "batches": ["B-1", "B-2"]}],
            "batches": [
                {"batch_id": "B-1", "sub_plan_id": "SP-1", "tasks": ["T-1"]},
                {"batch_id": "B-2", "sub_plan_id": "SP-1", "tasks": ["T-2"]},
            ],
            "tasks": [
                {"task_id": "T-1", "batch_id": "B-1"},
                {"task_id": "T-2", "batch_id": "B-2"},
            ],
        }
        cases = {
            "duplicate sub-plan batch ID": lambda value: value["sub_plans"][0].update({"batches": ["B-1", "B-1"]}),
            "nonexistent sibling batch ID": lambda value: value["sub_plans"][0].update({"batches": ["B-1", "B-MISSING"]}),
            "omitted sibling batch ID": lambda value: value["sub_plans"][0].update({"batches": ["B-1"]}),
            "listed sibling references another sub-plan": lambda value: value["batches"][1].update({"sub_plan_id": "SP-2"}),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                value = json.loads(json.dumps(base))
                mutate(value)
                with self.assertRaises(ValueError):
                    _resolve_documents(value, "B-1")

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
        contract = contract_from_rubric(resolve_rubric("personal", "backend", {}))
        task = {
            "task_id": "T-DISPATCH-RETRY",
            "title": "dispatch retry identity",
            "status": "QUEUED",
            "revision": 1,
            "previous_revision": 0,
            "updated_at": "2026-08-03T00:00:00Z",
            "review_contract": contract,
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
                "review_contract": contract,
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

    def test_dispatch_rejects_task_state_without_pinned_review_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            dispatch_path = self._prepare_dispatch_retry(project)
            task_path = project / ".agent/work/T-DISPATCH-RETRY/task-state.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            task.pop("review_contract", None)
            task_path.write_text(json.dumps(task), encoding="utf-8")
            result = run_script(
                "dispatch_task.py",
                "--project-root", str(project),
                "--input", str(dispatch_path),
                "--deployment", str(DEPLOYMENT_PATH),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("review_contract", result.stderr)

    def test_dispatch_rejects_legacy_risk_flags_in_nested_review_contract(self) -> None:
        contract = contract_from_rubric(resolve_rubric("personal", "backend", {}))
        dispatch = {
            "dispatch_id": "DSP-NESTED-RISK",
            "task_id": "T-NESTED-RISK",
            "agent_role": "agent-executor",
            "selected_mode": "SYNC",
            "selected_owner": "primary-agent",
            "selected_model": EXECUTOR_MODEL,
            "input_revisions": {"task": 1},
            "approval_references": [],
            "evidence": {"reason": "nested risk check"},
            "review_contract": contract,
            "planning_task": {
                "owner": "agent-executor",
                "risk_flags": {},
                "review_contract": {**contract, "risk_flags": {"database_write": True}},
            },
        }
        config = dispatch_task.load_config()
        deployment = dispatch_task.load_deployment_config(str(DEPLOYMENT_PATH), config)
        with self.assertRaisesRegex(ValueError, "unknown risk flag"):
            dispatch_task.normalize_dispatch(dispatch, config, deployment)

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


class PlanningIntegrityTests(unittest.TestCase):
    def write_json(self, path: Path, value: object) -> Path:
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def planning_bundle(self, *, task_type: str = "backend_change") -> dict:
        contract = contract_from_rubric(resolve_rubric("personal", "backend", {}))
        return {
            "master_plan": {
                "plan_id": "MP-1", "version": "1.0", "title": "Plan", "objective": "Test",
                "requirements": [
                    {"requirement_id": "REQ-1", "description": "First"},
                    {"requirement_id": "REQ-2", "description": "Second"},
                ],
                "in_scope": ["src"], "out_of_scope": [], "architecture": "A",
                "workstreams": ["runtime"], "milestones": ["m1"], "dependencies": [],
                "constraints": [], "success_criteria": ["REQ-1"], "risks": [],
                "completion_conditions": ["tests pass"],
            },
            "sub_plans": [{
                "sub_plan_id": "SP-1", "master_plan_id": "MP-1", "version": "1.0",
                "title": "Sub", "objective": "Test", "dependencies": [], "outputs": ["x"],
                "batches": ["B-1"], "risks": [],
            }],
            "batches": [{
                "batch_id": "B-1", "sub_plan_id": "SP-1", "version": "1.0",
                "objective": "Test", "depends_on": [], "tasks": ["T-1"],
                "integration_criteria": ["pass"], "definition_of_done": ["done"],
                "review_profile": "personal", "commit_conditions": ["approved"],
            }],
            "tasks": [{
                "task_id": "T-1", "batch_id": "B-1", "version": "1.0", "title": "Task",
                "objective": "Test", "context": "Test", "owner": "agent-executor",
                "depends_on": [], "execution_mode": "sync", "task_type": task_type,
                "requirement_ids": ["REQ-1"], "read_scope": ["src"],
                "write_scope": ["src/app.py"], "inputs": [], "required_outputs": ["result"],
                "acceptance_criteria": [{"criterion_id": "AC-1", "text": "pass", "requirement_ids": ["REQ-1"]}],
                "verification": ["tests"], "out_of_scope": [], "risk_flags": {},
                "review_contract": contract, "blocker_policy": {"hard_blockers": []},
                "execution_budget": {"max_files_changed": 1, "max_new_dependencies": 0,
                    "allow_schema_change": False, "allow_architecture_change": False},
                "architecture_decisions": [],
            }],
            "decisions": [], "assumptions": [], "risks": [], "change_requests": [],
        }

    def assert_planning_invalid(self, bundle: dict, text: str) -> None:
        errors = validate_manifest(bundle)
        self.assertTrue(errors, bundle)
        self.assertTrue(any(text.lower() in error.lower() for error in errors), errors)

    def test_task_owner_is_required_known_and_capable(self) -> None:
        alias = self.planning_bundle()
        alias["tasks"][0]["owner"] = "implementer"
        alias["master_plan"]["requirements"] = [{"requirement_id": "REQ-1", "description": "First"}]
        self.assertFalse(validate_manifest(alias), validate_manifest(alias))

        missing = self.planning_bundle()
        missing["tasks"][0].pop("owner")
        self.assert_planning_invalid(missing, "owner")

        unknown = self.planning_bundle()
        unknown["tasks"][0]["owner"] = "agent-missing"
        self.assert_planning_invalid(unknown, "owner")

        under_capable = self.planning_bundle()
        under_capable["tasks"][0]["owner"] = "agent-review"
        self.assert_planning_invalid(under_capable, "capab")

    def test_approved_task_requires_a_fully_pinned_review_contract(self) -> None:
        bundle = self.planning_bundle()
        bundle["status"] = "APPROVED"
        bundle["tasks"][0].pop("review_contract")
        self.assert_planning_invalid(bundle, "review_contract")

    def test_reverse_batch_and_sub_plan_membership_is_exact_and_unique(self) -> None:
        cases = []
        batch_missing_task = self.planning_bundle()
        batch_missing_task["batches"][0]["tasks"] = []
        cases.append(batch_missing_task)
        task_missing_batch = self.planning_bundle()
        task_missing_batch["tasks"][0]["batch_id"] = "B-2"
        cases.append(task_missing_batch)
        duplicate_batch_task = self.planning_bundle()
        duplicate_batch_task["batches"][0]["tasks"] = ["T-1", "T-1"]
        cases.append(duplicate_batch_task)
        duplicate_sub_plan_batch = self.planning_bundle()
        duplicate_sub_plan_batch["sub_plans"][0]["batches"] = ["B-1", "B-1"]
        cases.append(duplicate_sub_plan_batch)
        for bundle in cases:
            with self.subTest(bundle=bundle):
                self.assertTrue(any("membership" in error.lower() or "duplicate" in error.lower() for error in validate_manifest(bundle)))

    def test_requirement_ids_are_unique_known_not_deprecated_and_traced(self) -> None:
        duplicate = self.planning_bundle()
        duplicate["master_plan"]["requirements"].append({"requirement_id": "REQ-1", "description": "Duplicate"})
        self.assert_planning_invalid(duplicate, "duplicate")

        unknown = self.planning_bundle()
        unknown["tasks"][0]["requirement_ids"] = ["REQ-UNKNOWN"]
        self.assert_planning_invalid(unknown, "unknown requirement")

        deprecated = self.planning_bundle()
        deprecated["master_plan"]["requirements"][0]["deprecated"] = True
        self.assert_planning_invalid(deprecated, "deprecated")

        untraced = self.planning_bundle()
        untraced["tasks"][0]["requirement_ids"] = ["REQ-1"]
        untraced["tasks"][0]["acceptance_criteria"] = [{"criterion_id": "AC-1", "text": "only first", "requirement_ids": ["REQ-1"]}]
        self.assert_planning_invalid(untraced, "untraceable")

    def test_structured_acceptance_criteria_cannot_reference_untraced_requirements(self) -> None:
        bundle = self.planning_bundle()
        bundle["tasks"][0]["acceptance_criteria"] = [{"criterion_id": "AC-1", "text": "wrong", "requirement_ids": ["REQ-2"]}]
        self.assert_planning_invalid(bundle, "acceptance")

    def test_string_acceptance_criteria_are_rejected_without_requirement_trace(self) -> None:
        bundle = self.planning_bundle()
        bundle["tasks"][0]["acceptance_criteria"] = ["unstructured"]
        self.assert_planning_invalid(bundle, "acceptance_criteria")

    def test_dependency_ordered_overlaps_are_sequential_and_unordered_are_conflicts(self) -> None:
        sequential = self.planning_bundle()
        sequential["tasks"].append(dict(sequential["tasks"][0], task_id="T-2", depends_on=["T-1"]))
        sequential["batches"][0]["tasks"].append("T-2")
        self.assertFalse(any("overlap" in error.lower() or "conflict" in error.lower() for error in validate_manifest(sequential)), validate_manifest(sequential))

        conflict = self.planning_bundle()
        conflict["tasks"].append(dict(conflict["tasks"][0], task_id="T-2"))
        conflict["batches"][0]["tasks"].append("T-2")
        self.assert_planning_invalid(conflict, "conflict")

    def test_shared_write_requires_sync_group_and_persisted_approval(self) -> None:
        bundle = self.planning_bundle()
        second = dict(bundle["tasks"][0], task_id="T-2")
        for task in (bundle["tasks"][0], second):
            task["shared_write_group"] = "GROUP-1"
            task["shared_write_approval_id"] = "APR-SHARED"
            task["execution_mode"] = "sync"
        bundle["tasks"].append(second)
        bundle["batches"][0]["tasks"].append("T-2")
        bundle["approvals"] = [{"approval_id": "APR-SHARED", "target_type": "SHARED_WRITE", "target_id": "GROUP-1", "decision": "APPROVED"}]
        self.assert_planning_invalid(bundle, "approval")

        bundle["approvals"] = []
        self.assert_planning_invalid(bundle, "approval")

        bundle["approvals"] = [{"approval_id": "APR-SHARED", "decision": "APPROVED"}]
        self.assert_planning_invalid(bundle, "approval")

        sequential = self.planning_bundle()
        second = dict(sequential["tasks"][0], task_id="T-2", depends_on=["T-1"])
        second["requirement_ids"] = ["REQ-2"]
        second["acceptance_criteria"] = [{"criterion_id": "AC-2", "text": "pass", "requirement_ids": ["REQ-2"]}]
        for task in (sequential["tasks"][0], second):
            task["shared_write_group"] = "GROUP-1"
            task["shared_write_approval_id"] = "APR-SHARED"
            task["execution_mode"] = "sync"
        sequential["tasks"].append(second)
        sequential["batches"][0]["tasks"].append("T-2")
        sequential["approvals"] = [{"approval_id": "APR-SHARED", "decision": "APPROVED"}]
        self.assert_planning_invalid(sequential, "shared")

        persisted = self.planning_bundle()
        persisted_second = dict(persisted["tasks"][0], task_id="T-2", depends_on=["T-1"])
        persisted_second["requirement_ids"] = ["REQ-2"]
        persisted_second["acceptance_criteria"] = [{"criterion_id": "AC-2", "text": "pass", "requirement_ids": ["REQ-2"]}]
        for task in (persisted["tasks"][0], persisted_second):
            task["shared_write_group"] = "GROUP-1"
            task["shared_write_approval_id"] = "APR-SHARED"
            task["execution_mode"] = "sync"
        persisted["tasks"].append(persisted_second)
        persisted["batches"][0]["tasks"].append("T-2")
        with tempfile.TemporaryDirectory() as directory:
            approval_root = Path(directory) / ".agent"
            (approval_root / "approvals").mkdir(parents=True)
            self.assertTrue(any("approval" in error.lower() for error in validate_manifest(persisted, approval_root)))
            self.write_json(approval_root / "approvals/SHARED_WRITE-GROUP-1.json", {
                "approval_id": "APR-SHARED",
                "target_type": "SHARED_WRITE",
                "target_id": "GROUP-1",
                "decision": "APPROVED",
                "approver": "primary-agent",
                "actor_type": "primary_agent",
                "actor_id": "primary-agent",
                "action": "SHARED_WRITE",
                "target_revision": 1,
                "target_hash": "a" * 64,
                "policy_version": "1",
                "expires_at": "2099-01-01T00:00:00Z",
                "evidence": "approved shared write group",
                "created_at": "2026-08-03T00:00:00Z",
                "revision": 1,
            })
            self.assertFalse(validate_manifest(persisted, approval_root), validate_manifest(persisted, approval_root))

    def test_shared_write_rejects_inline_approval_without_persisted_artifact(self) -> None:
        bundle = self.planning_bundle()
        second = dict(bundle["tasks"][0], task_id="T-2")
        for task in (bundle["tasks"][0], second):
            task["shared_write_group"] = "GROUP-1"
            task["shared_write_approval_id"] = "APR-SHARED"
            task["execution_mode"] = "sync"
        bundle["tasks"].append(second)
        bundle["batches"][0]["tasks"].append("T-2")
        bundle["approvals"] = [{
            "approval_id": "APR-SHARED",
            "target_type": "SHARED_WRITE",
            "target_id": "GROUP-1",
            "decision": "APPROVED",
        }]
        errors = validate_manifest(bundle)
        self.assertTrue(any("persist" in error.lower() or "approval" in error.lower() for error in errors), errors)

    def test_shared_write_approval_uses_the_official_persisted_artifact(self) -> None:
        bundle = self.planning_bundle()
        second = dict(bundle["tasks"][0], task_id="T-2", depends_on=["T-1"])
        second["requirement_ids"] = ["REQ-2"]
        second["acceptance_criteria"] = [{"criterion_id": "AC-2", "text": "pass", "requirement_ids": ["REQ-2"]}]
        for task in (bundle["tasks"][0], second):
            task["shared_write_group"] = "GROUP-1"
            task["shared_write_approval_id"] = "APR-SHARED"
            task["execution_mode"] = "sync"
        bundle["tasks"].append(second)
        bundle["batches"][0]["tasks"].append("T-2")
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            approval = self.write_json(project / "shared-write-approval.json", {
                "approval_id": "APR-SHARED",
                "target_type": "SHARED_WRITE",
                "target_id": "GROUP-1",
                "decision": "APPROVED",
                "approver": "primary-agent",
                "actor_type": "primary_agent",
                "actor_id": "primary-agent",
                "action": "SHARED_WRITE",
                "target_revision": 1,
                "target_hash": "a" * 64,
                "policy_version": "1",
                "expires_at": "2099-01-01T00:00:00Z",
                "evidence": "approved shared write group",
            })
            result = run_script("record_approval.py", "--project-root", str(project), "--input", str(approval))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(validate_manifest(bundle, project / ".agent"), validate_manifest(bundle, project / ".agent"))

    def test_acceptance_criteria_use_stable_ids_and_text(self) -> None:
        bundle = self.planning_bundle()
        bundle["master_plan"]["requirements"] = [{"requirement_id": "REQ-1", "description": "First"}]
        bundle["tasks"][0]["acceptance_criteria"] = [{
            "criterion_id": "AC-1",
            "text": "pass",
            "requirement_ids": ["REQ-1"],
        }]
        self.assertFalse(validate_manifest(bundle), validate_manifest(bundle))
        report = requirement_report(bundle)
        self.assertEqual(report[0]["acceptance_criteria"], ["T-1[AC-1]"])

    def test_dispatch_rejects_legacy_risk_flags(self) -> None:
        contract = contract_from_rubric(resolve_rubric("personal", "backend", {}))
        dispatch = {
            "dispatch_id": "DSP-RISK",
            "task_id": "T-RISK",
            "agent_role": "agent-executor",
            "selected_mode": "SYNC",
            "selected_owner": "primary-agent",
            "selected_model": EXECUTOR_MODEL,
            "input_revisions": {"task": 1},
            "approval_references": [],
            "evidence": {"reason": "risk check"},
            "risk_flags": {"database_write": True},
            "review_contract": contract,
        }
        config = dispatch_task.load_config()
        deployment = dispatch_task.load_deployment_config(str(DEPLOYMENT_PATH), config)
        with self.assertRaisesRegex(ValueError, "unknown risk flag|additional property"):
            dispatch_task.normalize_dispatch(dispatch, config, deployment)
        embedded = dict(dispatch)
        embedded.pop("risk_flags")
        embedded["planning_task"] = {"owner": "agent-executor", "risk_flags": {"database_write": True}}
        with self.assertRaisesRegex(ValueError, "unknown risk flag"):
            dispatch_task.normalize_dispatch(embedded, config, deployment)
        task_alias = dict(dispatch)
        task_alias.pop("risk_flags")
        task_alias["task"] = {"owner": "agent-executor", "risk_flags": {"database_write": True}}
        with self.assertRaisesRegex(ValueError, "unknown risk flag"):
            dispatch_task.normalize_dispatch(task_alias, config, deployment)
        both_nested = dict(dispatch)
        both_nested.pop("risk_flags")
        both_nested["planning_task"] = {"owner": "agent-executor", "risk_flags": {}}
        both_nested["task"] = {"owner": "agent-executor", "risk_flags": {"database_write": True}}
        with self.assertRaisesRegex(ValueError, "unknown risk flag"):
            dispatch_task.normalize_dispatch(both_nested, config, deployment)

    def test_scope_detector_cli_emits_classification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = self.write_json(Path(directory) / "overlap.json", {
                "tasks": [
                    {"task_id": "T-1", "depends_on": [], "write_scope": ["src/config.py"]},
                    {"task_id": "T-2", "depends_on": [], "write_scope": ["src/config.py"]},
                ],
            })
            conflict = run_script("detect_scope_overlap.py", "--input", str(input_path))
            self.assertEqual(conflict.returncode, 1)
            self.assertEqual(json.loads(conflict.stdout)["overlaps"][0]["classification"], "CONFLICT")

            ordered = json.loads(input_path.read_text(encoding="utf-8"))
            ordered["tasks"][1]["depends_on"] = ["T-1"]
            input_path.write_text(json.dumps(ordered), encoding="utf-8")
            sequential = run_script("detect_scope_overlap.py", "--input", str(input_path))
            self.assertEqual(sequential.returncode, 0)
            self.assertEqual(json.loads(sequential.stdout)["overlaps"][0]["classification"], "SEQUENTIAL_OVERLAP")

    def test_read_only_intersections_are_not_scope_conflicts(self) -> None:
        bundle = self.planning_bundle()
        second = dict(bundle["tasks"][0], task_id="T-2", write_scope=["src/other.py"], read_scope=["src/app.py"])
        bundle["tasks"].append(second)
        bundle["batches"][0]["tasks"].append("T-2")
        self.assertFalse(any("conflict" in error.lower() or "overlap" in error.lower() for error in validate_manifest(bundle)), validate_manifest(bundle))

    def test_requirement_report_is_deterministic_and_has_required_columns(self) -> None:
        bundle = self.planning_bundle()
        report = requirement_report(bundle)
        self.assertEqual([row["requirement"] for row in report], ["REQ-1", "REQ-2"])
        self.assertEqual(set(report[0]), {"requirement", "tasks", "acceptance_criteria", "status"})
        self.assertEqual(report[0]["tasks"], ["T-1"])
        self.assertEqual(report[0]["status"], "TRACED")

    def test_canonical_risk_flags_reject_legacy_vocabulary(self) -> None:
        self.assertEqual(normalize_risk_flags({"database": False, "authentication": True}), {"authentication": True, "database": False})
        with self.assertRaisesRegex(ValueError, "unknown"):
            normalize_risk_flags({"database_write": True})
        with self.assertRaisesRegex(ValueError, "boolean"):
            normalize_risk_flags({"database": 1})


if __name__ == "__main__":
    unittest.main()
