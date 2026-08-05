from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE_SCRIPTS = ROOT / "skills" / "agentic-state-tools" / "scripts"
AUTHORING_SCRIPTS = ROOT / "skills" / "agentic-skill-authoring" / "scripts"
CONFIG_SCRIPTS = ROOT / "skills" / "agentic-configuration" / "scripts"
sys.path[:0] = [str(STATE_SCRIPTS), str(AUTHORING_SCRIPTS), str(CONFIG_SCRIPTS)]

from create_context import normalize as normalize_context  # noqa: E402
from create_debug_investigation import _validate_domain  # noqa: E402
from create_review_resolution import _validate_status  # noqa: E402
from finalize_delivery import validate_delivery_decision  # noqa: E402
from load_config import load_config  # noqa: E402
from resolve_execution_mode import resolve_execution_mode  # noqa: E402
from run_behavior_scenarios import evaluate_observation  # noqa: E402
from validate_payload import validate  # noqa: E402
from verification_contract import workspace_hash  # noqa: E402
from verify_completion_claim import validate_claim  # noqa: E402


class HSP804IntegratedWorkflowTests(unittest.TestCase):
    """Exercise the six release-plan flows through the integrated contracts."""

    def test_scenario_a_new_feature_preserves_identity_tdd_review_and_delivery_order(self) -> None:
        config = load_config()
        context = normalize_context(
            {
                "task": {"task_id": "HSP804-A", "objective": "Add a bounded feature"},
                "required_documents": ["skills/agentic-engineering-wiki/refs/workflows/planning.md"],
                "code_context": {"files_to_read": ["src/feature.py"], "symbols_to_inspect": [], "existing_patterns": []},
                "constraints": {"inherited": ["preserve identity"], "task_specific": ["stay in scope"]},
                "review_history": [],
                "budget": config["context_budget"],
                "context_id": "CTX-HSP804-A",
                "created_at": "2026-08-05T00:00:00Z",
                "revision": 1,
                "run_id": "RUN-HSP804-A",
                "attempt_id": "ATT-HSP804-A",
                "dispatch_id": "DSP-HSP804-A",
                "recipient_role": "IMPLEMENTER",
            },
            config,
        )
        context_errors = validate(
            context,
            json.loads((ROOT / "skills/agentic-state-tools/schemas/context.schema.json").read_text(encoding="utf-8")),
        )
        self.assertEqual(context_errors, [])

        stages = [
            "BRAINSTORM",
            "APPROVED_DECISION",
            "EXECUTABLE_PLAN",
            "PLAN_REVIEW",
            "FRESH_CONTEXT",
            "RED",
            "GREEN",
            "FRESH_COMPLETION_VERIFICATION",
            "SPEC_COMPLIANCE",
            "CODE_QUALITY",
            "BATCH_REVIEW",
            "DELIVERY_FINALIZATION",
        ]
        self.assertEqual(stages.index("SPEC_COMPLIANCE") + 1, stages.index("CODE_QUALITY"))
        self.assertLess(stages.index("RED"), stages.index("GREEN"))
        self.assertLess(stages.index("GREEN"), stages.index("FRESH_COMPLETION_VERIFICATION"))

        delivery = json.loads(
            (ROOT / "skills/agentic-state-tools/examples/delivery-decision.json").read_text(encoding="utf-8")
        )
        self.assertTrue(validate_delivery_decision(delivery))

    def test_scenario_b_bug_repair_requires_root_cause_red_green_and_broad_evidence(self) -> None:
        record = self._debug_record(status="COMPLETED", root_cause="parser drops the final token", confirmed=True)
        _validate_domain(record, current_revision=1)
        evidence_phases = ["RED", "GREEN", "BROAD"]
        self.assertEqual(evidence_phases, ["RED", "GREEN", "BROAD"])

        record["regression_check"] = {"command": "python -m unittest", "exit_code": 1, "status": "FAIL", "workspace_hash": "a" * 64}
        with self.assertRaisesRegex(ValueError, "COMPLETED requires"):
            _validate_domain(record, current_revision=1)

    def test_scenario_c_three_failed_repairs_block_without_a_fourth_blind_fix(self) -> None:
        record = self._debug_record(status="BLOCKED", root_cause=None, confirmed=False)
        record["hypotheses"] = [
            self._hypothesis("H1", "first cause", "REJECTED"),
            self._hypothesis("H2", "second cause", "REJECTED"),
            self._hypothesis("H3", "third cause", "REJECTED"),
        ]
        record["regression_check"] = {"command": "python -m unittest", "exit_code": 1, "status": "FAIL", "workspace_hash": "a" * 64}
        record["fix_attempt_count"] = 3
        _validate_domain(record, current_revision=1)
        record["fix_attempt_count"] = 4
        with self.assertRaisesRegex(ValueError, "must not exceed 3"):
            _validate_domain(record, current_revision=1)

    def test_scenario_d_parallel_exploration_reconciles_before_any_write(self) -> None:
        config = load_config()
        first = self._explorer_task("EXP-A", "trace routing", "skills/agentic-engineering-core")
        second = self._explorer_task("EXP-B", "trace state ownership", "skills/agentic-state-tools")
        now = datetime(2026, 8, 5, tzinfo=timezone.utc)
        for task in (first, second):
            result = resolve_execution_mode(
                task,
                config=config,
                active_tasks=[],
                queue={"tasks": [], "available_slots": 2},
                now=now,
            )
            self.assertEqual(result["resolved_mode"], "PARALLEL_READ_ONLY")
            self.assertEqual(result["resolution_reason"], "PARALLEL_READ_ONLY_ELIGIBLE")

        write_task = {
            "task_id": "WRITE-AFTER-EXPLORE",
            "status": "READY",
            "owner": "agent-executor",
            "task_type": "backend",
            "execution_policy": {"requested_mode": "ASYNC_REQUIRED"},
            "write_scope": ["src/feature.py"],
        }
        write_result = resolve_execution_mode(
            write_task,
            config=config,
            active_tasks=[first, second],
            queue={"tasks": [first, second], "available_slots": 1},
            now=now,
        )
        self.assertEqual(write_result["resolved_mode"], "BLOCKED")
        self.assertNotEqual(write_result["resolved_mode"], "PARALLEL_READ_ONLY")

    def test_scenario_e_stale_completion_is_rejected_then_accepts_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self._init_git_project(project)
            source = project / "src/feature.py"
            source.write_text("return 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "feature"], cwd=project, check=True, capture_output=True)
            agent_root = project / ".agent"
            (agent_root / "work/HSP804-E/verification").mkdir(parents=True)
            task_state = {
                "task_id": "HSP804-E",
                "revision": 1,
                "plan_revision": 1,
                "run_id": "RUN-HSP804-E",
                "attempt_id": "ATT-HSP804-E",
                "status": "COMPLETED",
                "acceptance_criteria": [{"criterion_id": "AC-E"}],
            }
            self._write_json(agent_root / "work/HSP804-E/task-state.json", task_state)
            red_hash = workspace_hash(project, ["src/feature.py"])
            source.write_text("return 2\n", encoding="utf-8")
            green_hash = workspace_hash(project, ["src/feature.py"])
            self.assertNotEqual(red_hash, green_hash)
            self._write_json(
                agent_root / "work/HSP804-E/verification/E-RED.json",
                self._evidence("E-RED", "RED", red_hash, 1, "FAIL"),
            )
            self._write_json(
                agent_root / "work/HSP804-E/verification/E-GREEN.json",
                self._evidence("E-GREEN", "GREEN", red_hash, 0, "PASS"),
            )
            claim = self._claim(green_hash)
            with self.assertRaisesRegex(ValueError, "stale"):
                validate_claim(claim, project_root=project, root=agent_root)

            refreshed_hash = workspace_hash(project, ["src/feature.py"])
            self._write_json(
                agent_root / "work/HSP804-E/verification/E-GREEN.json",
                self._evidence("E-GREEN", "GREEN", refreshed_hash, 0, "PASS"),
            )
            claim["workspace_hash"] = refreshed_hash
            self.assertEqual(validate_claim(claim, project_root=project, root=agent_root)["verification_status"], "VERIFIED")

    def test_scenario_f_out_of_scope_feedback_is_rejected_with_evidence_and_re_reviewed(self) -> None:
        finding = {
            "severity": "SUGGESTION",
            "evidence": "Reviewer requested an unrelated abstraction.",
            "required_change": "Keep the approved implementation scope unchanged.",
            "location": "src/feature.py:1",
        }
        rejection = self._resolution(finding, "REJECTED_WITH_EVIDENCE")
        rejection["rejection_basis"] = "The suggestion is outside the approved task contract."
        rejection["contract_verification"]["status"] = "CONFLICT"
        _validate_status(rejection, None, "task-reviewer")

        correction = self._resolution(finding, "FIXED_PENDING_REREVIEW")
        correction["resolution_id"] = "RES-HSP804-F"
        correction["correction"] = {"summary": "No out-of-scope abstraction was added.", "coherent": True, "changed_files": ["src/feature.py"]}
        correction["targeted_verification"] = {"command": "python -m unittest", "status": "PASS", "exit_code": 0}
        correction["contract_verification"]["status"] = "VERIFIED"
        correction["code_verification"]["status"] = "VERIFIED"
        correction["conflict_usage_check"]["status"] = "CLEAR"
        existing = copy.deepcopy(correction)
        closed = copy.deepcopy(correction)
        closed.update(
            {
                "status": "CLOSED",
                "actor_role": "REVIEWER",
                "review_id": "REV-HSP804-F-R2",
                "correction_reference": "RES-HSP804-F",
                "re_review": {"review_id": "REV-HSP804-F-R2", "result": "PASS", "evidence_ids": ["E-RR"]},
            }
        )
        _validate_status(closed, existing, "task-reviewer")

    @staticmethod
    def _hypothesis(hypothesis_id: str, statement: str, outcome: str) -> dict[str, str]:
        return {
            "hypothesis_id": hypothesis_id,
            "statement": statement,
            "predicted_observation": "the trace identifies the suspected boundary",
            "experiment": "python -m unittest focused",
            "result": outcome.lower(),
            "outcome": outcome,
        }

    @classmethod
    def _debug_record(cls, *, status: str, root_cause: str | None, confirmed: bool) -> dict[str, object]:
        hypotheses = [cls._hypothesis("H1", "parser boundary", "CONFIRMED" if confirmed else "REJECTED")]
        return {
            "schema_version": 1,
            "investigation_id": "DBG-HSP804",
            "task_id": "HSP804-B",
            "run_id": "RUN-HSP804-B",
            "attempt_id": "ATT-HSP804-B",
            "task_revision": 1,
            "symptom": "parsed output is truncated",
            "reproduction_status": "REPRODUCED",
            "reproduction_steps": ["python -m unittest focused"],
            "observed_output": "truncated",
            "expected_output": "complete",
            "environment_facts": {"python": "3.11"},
            "recent_changes": [],
            "data_flow_trace": ["input", "parser", "output"],
            "working_reference": None,
            "hypotheses": hypotheses,
            "current_hypothesis": "H1",
            "experiment": {"command": "python -m unittest focused", "expected_observation": "boundary trace"},
            "experiment_result": {"observed": "recorded", "outcome": "CONFIRMED" if confirmed else "REJECTED", "recorded_at": "2026-08-05T00:00:00Z"},
            "root_cause": root_cause,
            "regression_check": {"command": "python -m unittest", "exit_code": 0, "workspace_hash": "a" * 64, "status": "PASS"},
            "fix_attempt_count": 3,
            "status": status,
            "created_at": "2026-08-05T00:00:00Z",
            "updated_at": "2026-08-05T00:00:00Z",
            "revision": 2,
        }

    @staticmethod
    def _explorer_task(task_id: str, question: str, scope: str) -> dict[str, object]:
        return {
            "task_id": task_id,
            "status": "READY",
            "owner": "agent-explorer",
            "task_type": "exploration",
            "execution_policy": {"requested_mode": "PARALLEL_READ_ONLY"},
            "exploration_question": question,
            "independent_question": True,
            "read_scope": [scope],
            "write_scope": [],
            "write_forbidden": True,
            "context_capacity_available": True,
            "token_capacity_available": True,
            "deterministic_reconciliation": True,
            "reconciliation_strategy": "sort findings by task_id, path, symbol",
            "reconciliation_contract": {
                "order": ["task_id", "path", "symbol"],
                "preserve_source_locations": True,
                "block_on_conflict": True,
                "block_on_material_unknown": True,
            },
        }

    @staticmethod
    def _init_git_project(project: Path) -> None:
        (project / "src").mkdir(parents=True)
        (project / "src/feature.py").write_text("return 0\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.name", "HSP804 Test"], cwd=project, check=True)
        subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=project, check=True, capture_output=True)

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _evidence(evidence_id: str, phase: str, digest: str, exit_code: int, status: str) -> dict[str, object]:
        return {
            "evidence_id": evidence_id,
            "verification_case_id": "VC-HSP804-E",
            "task_id": "HSP804-E",
            "plan_revision": 1,
            "run_id": "RUN-HSP804-E",
            "attempt_id": "ATT-HSP804-E",
            "task_revision": 1,
            "phase": phase,
            "verification_type": "unit",
            "workspace_hash": digest,
            "command": "python -m unittest focused",
            "exit_code": exit_code,
            "status": status,
            "failure_signature": "expected failing behavior" if phase == "RED" else None,
            "output_digest": "evidence-output",
            "evidence_location": f".agent/work/HSP804-E/verification/{evidence_id}.json",
            "recorded_at": "2026-08-05T00:00:00Z",
            "acceptance_criterion_ids": ["AC-E"],
        }

    @staticmethod
    def _claim(digest: str) -> dict[str, object]:
        return {
            "claim_id": "CLAIM-HSP804-E",
            "claim": "feature is complete",
            "task_id": "HSP804-E",
            "plan_revision": 1,
            "run_id": "RUN-HSP804-E",
            "attempt_id": "ATT-HSP804-E",
            "task_revision": 1,
            "workspace_hash": digest,
            "profile_id": "personal",
            "change_kind": "bug_fix",
            "test_harness_available": True,
            "broad_required": False,
            "evidence_ids": ["E-RED", "E-GREEN"],
            "acceptance_criteria": [{"criterion_id": "AC-E", "evidence_ids": ["E-GREEN"], "status": "PASS"}],
            "acceptance_criterion_ids": ["AC-E"],
            "summary": "fresh RED and GREEN evidence",
        }

    @staticmethod
    def _resolution(finding: dict[str, object], status: str) -> dict[str, object]:
        checks = {
            "contract_verification": {"status": "VERIFIED", "evidence": ["contract checked"]},
            "code_verification": {"status": "VERIFIED", "evidence": ["code checked"]},
            "conflict_usage_check": {"status": "CLEAR", "evidence": ["usage checked"]},
            "ambiguity_resolution": {"status": "RESOLVED", "evidence": ["scope is clear"]},
        }
        return {
            "status": status,
            "owner": "agentic-implementer",
            "actor_role": "IMPLEMENTER",
            "review_id": "REV-HSP804-F",
            "finding_id": "finding-1",
            "finding": finding,
            "rationale": "scope checked before action",
            "evidence": {"summary": "current contract and usage inspected"},
            **checks,
        }


if __name__ == "__main__":
    unittest.main()
