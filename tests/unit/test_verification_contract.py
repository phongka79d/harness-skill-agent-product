from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "agentic-state-tools"
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
sys.path.insert(0, str(SCRIPTS))


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class VerificationContractTests(unittest.TestCase):
    def test_profiles_expose_machine_readable_verification_policy(self) -> None:
        result = run_script("resolve_project_profile.py", "--profile", "production")
        self.assertEqual(result.returncode, 0, result.stderr)
        profile = json.loads(result.stdout)
        self.assertEqual(profile["verification_policy"]["tdd_mode"], "MANDATORY")
        self.assertEqual(profile["verification_policy"]["broad_suite_mode"], "MANDATORY")

    def test_planning_task_accepts_structured_verification_case(self) -> None:
        task = {
            "task_id": "T-VERIFY",
            "batch_id": "B-VERIFY",
            "version": "1.0",
            "title": "Evidence contract",
            "objective": "Record fresh verification evidence",
            "context": "verification",
            "owner": "primary-agent",
            "depends_on": [],
            "execution_mode": "sync",
            "task_type": "testing",
            "requirement_ids": ["REQ-VERIFY"],
            "read_scope": ["skills"],
            "write_scope": ["skills/agentic-state-tools"],
            "inputs": [],
            "required_outputs": ["evidence"],
            "acceptance_criteria": [{
                "criterion_id": "AC-VERIFY",
                "text": "Fresh evidence is required",
                "requirement_ids": ["REQ-VERIFY"],
            }],
            "verification": ["python -m unittest"],
            "verification_cases": [{
                "verification_case_id": "VC-VERIFY",
                "acceptance_criterion_ids": ["AC-VERIFY"],
                "verification_type": "behavior_change",
                "red_required": True,
                "red_command": "python -m unittest focused",
                "green_command": "python -m unittest focused",
                "broad_command": "python run_tests.py --group unit",
                "status": "PLANNED",
            }],
            "out_of_scope": [],
            "risk_flags": {},
            "blocker_policy": {"hard_blockers": []},
            "execution_budget": {
                "max_files_changed": 10,
                "max_new_dependencies": 0,
                "allow_schema_change": True,
                "allow_architecture_change": False,
            },
            "architecture_decisions": [],
        }
        payload = write_json(Path(tempfile.mkdtemp()) / "task.json", task)
        result = run_script(
            "validate_payload.py",
            "--input",
            str(payload),
            "--schema",
            str(SCHEMAS / "planning-task.schema.json"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def _runtime_with_task(self, directory: str) -> Path:
        project = Path(directory) / "project"
        initialized = run_script("init_runtime.py", "--project-root", str(project))
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        write_json(
            project / ".agent" / "work" / "T-VERIFY" / "task-state.json",
            {
                "task_id": "T-VERIFY",
                "plan_revision": 1,
                "revision": 1,
                "status": "RUNNING",
                "run_id": "RUN-VERIFY",
                "attempt_id": "ATT-VERIFY",
            },
        )
        return project

    def _record(self, project: Path, *, phase: str, exit_code: int, evidence_id: str, relevant_files: list[str] | None = None) -> dict:
        payload = write_json(
            project.parent / f"{evidence_id}.json",
            {
                "evidence_id": evidence_id,
                "verification_case_id": "VC-VERIFY",
                "task_id": "T-VERIFY",
                "plan_revision": 1,
                "run_id": "RUN-VERIFY",
                "attempt_id": "ATT-VERIFY",
                "task_revision": 1,
                "phase": phase,
                "verification_type": "behavior_change",
                "command": "python -m unittest focused",
                "exit_code": exit_code,
                "status": "FAIL" if exit_code else "PASS",
                "failure_signature": "expected missing behavior" if phase == "RED" else None,
                "acceptance_criterion_ids": ["AC-VERIFY"],
                "relevant_files": relevant_files or [],
            },
        )
        result = run_script(
            "record_verification_evidence.py",
            "--project-root",
            str(project),
            "--input",
            str(payload),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads((project / ".agent" / "work" / "T-VERIFY" / "verification" / f"{evidence_id}.json").read_text(encoding="utf-8"))

    def test_completion_gate_accepts_current_red_green_and_broad_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._runtime_with_task(directory)
            red = self._record(project, phase="RED", exit_code=1, evidence_id="E-RED")
            green = self._record(project, phase="GREEN", exit_code=0, evidence_id="E-GREEN")
            broad = self._record(project, phase="BROAD", exit_code=0, evidence_id="E-BROAD")
            claim = write_json(
                project.parent / "claim.json",
                {
                    "claim_id": "C-VERIFY",
                    "claim": "complete",
                    "task_id": "T-VERIFY",
                    "plan_revision": 1,
                    "run_id": "RUN-VERIFY",
                    "attempt_id": "ATT-VERIFY",
                    "task_revision": 1,
                    "workspace_hash": green["workspace_hash"],
                    "profile_id": "production",
                    "change_kind": "behavior_change",
                    "evidence_ids": [red["evidence_id"], green["evidence_id"], broad["evidence_id"]],
                    "acceptance_criteria": [{
                        "criterion_id": "AC-VERIFY",
                        "evidence_ids": [red["evidence_id"], green["evidence_id"], broad["evidence_id"]],
                    }],
                },
            )
            result = run_script(
                "verify_completion_claim.py",
                "--project-root",
                str(project),
                "--input",
                str(claim),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("COMPLETION_CLAIM_ACCEPTED", result.stdout)

    def test_red_baseline_may_differ_from_current_green_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._runtime_with_task(directory)
            source = project / "src.py"
            source.write_text("value = 1\n", encoding="utf-8")
            red = self._record(project, phase="RED", exit_code=1, evidence_id="E-BASELINE", relevant_files=["src.py"])
            source.write_text("value = 2\n", encoding="utf-8")
            green = self._record(project, phase="GREEN", exit_code=0, evidence_id="E-CURRENT", relevant_files=["src.py"])
            broad = self._record(project, phase="BROAD", exit_code=0, evidence_id="E-BROAD-CURRENT", relevant_files=["src.py"])
            claim = write_json(
                project.parent / "baseline-claim.json",
                {
                    "claim_id": "C-BASELINE",
                    "claim": "complete",
                    "task_id": "T-VERIFY",
                    "plan_revision": 1,
                    "run_id": "RUN-VERIFY",
                    "attempt_id": "ATT-VERIFY",
                    "task_revision": 1,
                    "workspace_hash": green["workspace_hash"],
                    "profile_id": "production",
                    "change_kind": "behavior_change",
                    "evidence_ids": [red["evidence_id"], green["evidence_id"], broad["evidence_id"]],
                    "acceptance_criteria": [{
                        "criterion_id": "AC-VERIFY",
                        "evidence_ids": [red["evidence_id"], green["evidence_id"], broad["evidence_id"]],
                    }],
                },
            )
            result = run_script("verify_completion_claim.py", "--project-root", str(project), "--input", str(claim))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_completion_gate_rejects_prior_attempt_and_summary_only_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._runtime_with_task(directory)
            evidence = self._record(project, phase="GREEN", exit_code=0, evidence_id="E-GREEN")
            stale_claim = write_json(
                project.parent / "stale.json",
                {
                    "claim_id": "C-STALE",
                    "claim": "complete",
                    "task_id": "T-VERIFY",
                    "plan_revision": 1,
                    "run_id": "RUN-OLD",
                    "attempt_id": "ATT-OLD",
                    "task_revision": 1,
                    "workspace_hash": evidence["workspace_hash"],
                    "profile_id": "production",
                    "change_kind": "behavior_change",
                    "evidence_ids": [evidence["evidence_id"]],
                    "acceptance_criteria": [{"criterion_id": "AC-VERIFY", "evidence_ids": [evidence["evidence_id"]]}],
                },
            )
            stale = run_script("verify_completion_claim.py", "--project-root", str(project), "--input", str(stale_claim))
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("run_id", stale.stderr)

            summary_claim = write_json(
                project.parent / "summary.json",
                {
                    "claim_id": "C-SUMMARY",
                    "claim": "complete",
                    "task_id": "T-VERIFY",
                    "plan_revision": 1,
                    "run_id": "RUN-VERIFY",
                    "attempt_id": "ATT-VERIFY",
                    "task_revision": 1,
                    "workspace_hash": evidence["workspace_hash"],
                    "profile_id": "production",
                    "change_kind": "behavior_change",
                    "summary": "tests passed",
                },
            )
            summary = run_script("verify_completion_claim.py", "--project-root", str(project), "--input", str(summary_claim))
            self.assertNotEqual(summary.returncode, 0)
            self.assertIn("evidence", summary.stderr.lower())

    def test_evidence_writer_rejects_supplied_stale_workspace_hash_without_partial_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._runtime_with_task(directory)
            payload = write_json(
                project.parent / "stale-evidence.json",
                {
                    "evidence_id": "E-STALE",
                    "verification_case_id": "VC-VERIFY",
                    "task_id": "T-VERIFY",
                    "plan_revision": 1,
                    "run_id": "RUN-VERIFY",
                    "attempt_id": "ATT-VERIFY",
                    "task_revision": 1,
                    "phase": "GREEN",
                    "verification_type": "behavior_change",
                    "workspace_hash": "0" * 64,
                    "command": "python -m unittest focused",
                    "exit_code": 0,
                    "status": "PASS",
                    "acceptance_criterion_ids": ["AC-VERIFY"],
                },
            )
            result = run_script("record_verification_evidence.py", "--project-root", str(project), "--input", str(payload))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((project / ".agent/work/T-VERIFY/verification/E-STALE.json").exists())

    def test_completion_gate_rejects_content_edit_and_hidden_skips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._runtime_with_task(directory)
            source = project / "src.py"
            source.write_text("value = 1\n", encoding="utf-8")
            evidence = self._record(project, phase="GREEN", exit_code=0, evidence_id="E-FRESH", relevant_files=["src.py"])
            source.write_text("value = 2\n", encoding="utf-8")
            claim = {
                "claim_id": "C-STALE-CONTENT",
                "claim": "complete",
                "task_id": "T-VERIFY",
                "plan_revision": 1,
                "run_id": "RUN-VERIFY",
                "attempt_id": "ATT-VERIFY",
                "task_revision": 1,
                "workspace_hash": evidence["workspace_hash"],
                "profile_id": "personal",
                "change_kind": "documentation",
                "evidence_ids": [evidence["evidence_id"]],
                "acceptance_criteria": [{"criterion_id": "AC-VERIFY", "evidence_ids": [evidence["evidence_id"]]}],
            }
            claim_path = write_json(project.parent / "stale-content.json", claim)
            stale = run_script("verify_completion_claim.py", "--project-root", str(project), "--input", str(claim_path))
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("stale", stale.stderr.lower())

            source.write_text("value = 1\n", encoding="utf-8")
            evidence_path = project / ".agent/work/T-VERIFY/verification/E-FRESH.json"
            recorded = json.loads(evidence_path.read_text(encoding="utf-8"))
            recorded["output"] = "1 skipped"
            evidence_path.write_text(json.dumps(recorded), encoding="utf-8")
            hidden = run_script("verify_completion_claim.py", "--project-root", str(project), "--input", str(claim_path))
            self.assertNotEqual(hidden.returncode, 0)
            self.assertIn("skipped", hidden.stderr.lower())

    def test_legacy_handoff_is_marked_and_strict_handoff_is_rejected(self) -> None:
        def handoff_payload(**extra: object) -> dict:
            return {
                "run_id": "RUN-VERIFY",
                "attempt_id": "ATT-VERIFY",
                "task_revision": 1,
                "plan_revision": 1,
                "from_role": "implementer",
                "to_role": "reviewer",
                "input_artifact_hashes": {},
                "output_artifact_hashes": {"result": "b" * 64},
                "evidence": {"summary": "implementation verified"},
                "status": "COMPLETE",
                "summary": "legacy handoff",
                "files_read": [],
                "files_changed": [],
                "findings": [],
                "implementation_details": [],
                "validation_results": [],
                "risks": [],
                "next_steps": [],
                **extra,
            }

        with tempfile.TemporaryDirectory() as directory:
            project = self._runtime_with_task(directory)
            payload = write_json(project.parent / "handoff.json", handoff_payload())
            result = run_script("create_handoff.py", "--project-root", str(project), "--task-id", "T-VERIFY", "--input", str(payload))
            self.assertEqual(result.returncode, 0, result.stderr)
            handoff = json.loads((project / ".agent/work/T-VERIFY/handoff.json").read_text(encoding="utf-8"))
            self.assertEqual(handoff["verification_status"], "LEGACY_UNVERIFIED")

        with tempfile.TemporaryDirectory() as directory:
            project = self._runtime_with_task(directory)
            payload = write_json(project.parent / "strict-handoff.json", handoff_payload(profile_id="production"))
            result = run_script("create_handoff.py", "--project-root", str(project), "--task-id", "T-VERIFY", "--input", str(payload))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("strict", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
