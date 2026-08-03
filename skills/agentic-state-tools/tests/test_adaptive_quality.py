from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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
    )


def write_json(directory: str, name: str, value: object) -> Path:
    path = Path(directory) / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class AdaptiveQualityTests(unittest.TestCase):
    def test_rubric_and_change_approval_schemas_exist(self) -> None:
        self.assertTrue((SCHEMAS / "rubric.schema.json").is_file())
        self.assertTrue((SCHEMAS / "change-approval.schema.json").is_file())

    def test_profile_aliases_resolve_to_one_canonical_definition(self) -> None:
        canonical = run_script("resolve_project_profile.py", "--profile", "quick_change")
        alias = run_script("resolve_project_profile.py", "--profile", "quick-change")
        self.assertEqual(canonical.returncode, 0, canonical.stderr)
        self.assertEqual(alias.returncode, 0, alias.stderr)
        canonical_value = json.loads(canonical.stdout)
        alias_value = json.loads(alias.stdout)
        self.assertEqual(alias_value["profile_id"], canonical_value["profile_id"])
        self.assertEqual(alias_value["profile_hash"], canonical_value["profile_hash"])

    def test_task_type_extension_is_recorded_in_resolved_rubric(self) -> None:
        result = run_script("resolve_rubric.py", "--profile", "personal", "--task-type", "backend", "--risk-flags", "{}")
        self.assertEqual(result.returncode, 0, result.stderr)
        rubric = json.loads(result.stdout)
        self.assertIn("backend", rubric["extension_ids"])
        self.assertIn("API_COMPATIBILITY", rubric["resolved_weights"])
        self.assertEqual(rubric["review_type"], "task")

    def test_risky_override_requires_approved_record(self) -> None:
        denied = run_script(
            "resolve_rubric.py",
            "--profile", "personal",
            "--task-type", "general",
            "--risk-flags", "{}",
            "--overrides", '{"threshold_percent":70}',
        )
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("approval", denied.stderr.lower())

        approved = run_script(
            "resolve_rubric.py",
            "--profile", "personal",
            "--task-type", "general",
            "--risk-flags", "{}",
            "--overrides", '{"threshold_percent":70,"approval_id":"APR-1","approval_decision":"APPROVED"}',
        )
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.assertEqual(json.loads(approved.stdout)["pass_threshold_percent"], 70)

    def test_primary_agent_is_required_for_architecture_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            initialized = run_script("init_runtime.py", "--project-root", str(project))
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            approval = write_json(
                directory,
                "architecture-approval.json",
                {"target_type": "ARCHITECTURE_CHANGE", "target_id": "DEC-1", "decision": "APPROVED", "approver": "reviewer", "evidence": "reviewed"},
            )
            denied = run_script("record_approval.py", "--project-root", str(project), "--input", str(approval), "--actor", "task-reviewer")
            self.assertNotEqual(denied.returncode, 0)
            accepted = run_script("record_approval.py", "--project-root", str(project), "--input", str(approval), "--actor", "primary-agent")
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_new_review_without_rubric_is_rejected_without_legacy_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            review = write_json(directory, "new-review.json", {"task_id": "T-1", "criteria": [], "findings": []})
            result = run_script("create_review.py", "--project-root", str(project), "--input", str(review))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("resolved_rubric", result.stderr)

    def test_change_request_requires_approval_and_applies_as_new_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = write_json(
                directory,
                "change.json",
                {
                    "change_request_id": "CR-1",
                    "target_type": "MASTER_PLAN",
                    "target_id": "MP-1",
                    "target_version": "1.0",
                    "reason": "Add recovery gate",
                    "requested_changes": ["Add a recovery release criterion"],
                    "impact": {"risk_level": "medium", "architecture_change": False},
                    "status": "APPROVED",
                    "requested_by": "primary-agent",
                    "approval_id": "APR-1",
                    "supersedes_id": "MP-1@1.0",
                    "new_version": "1.1",
                },
            )
            approval = write_json(
                directory,
                "approval.json",
                {
                    "approval_id": "APR-1",
                    "target_type": "CHANGE_REQUEST",
                    "target_id": "CR-1",
                    "decision": "APPROVED",
                    "approver": "primary-agent",
                    "evidence": "approved recovery scope",
                    "created_at": "2026-08-02T00:00:00Z",
                    "revision": 1,
                },
            )
            rejected = run_script("validate_change_request.py", "--input", str(request))
            self.assertNotEqual(rejected.returncode, 0)
            valid = run_script("validate_change_request.py", "--input", str(request), "--approval", str(approval))
            self.assertEqual(valid.returncode, 0, valid.stderr)

            target = write_json(directory, "plan.json", {"plan_id": "MP-1", "version": "1.0", "title": "Original"})
            output = Path(directory) / "plan-v1.1.json"
            applied = run_script(
                "apply_change_request.py",
                "--request", str(request),
                "--target", str(target),
                "--approval", str(approval),
                "--output", str(output),
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            new_plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(new_plan["version"], "1.1")
            self.assertEqual(new_plan["supersedes_id"], "MP-1@1.0")
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["version"], "1.0")

    def test_review_rubric_rejects_stale_hash_and_omitted_applicable_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rubric_result = run_script("resolve_rubric.py", "--profile", "personal", "--task-type", "backend", "--risk-flags", "{}")
            self.assertEqual(rubric_result.returncode, 0, rubric_result.stderr)
            rubric = json.loads(rubric_result.stdout)
            criteria = [
                {"id": criterion_id, "score": 4, "weight": weight, "mandatory": True, "minimum_score": 3, "applicability": "APPLICABLE", "evidence": "verified"}
                for criterion_id, weight in rubric["resolved_weights"].items()
            ]
            criteria.pop()
            review = {"review_id": "REV-1", "task_id": "T-1", "resolved_rubric": rubric, "criteria": criteria, "findings": []}
            input_path = write_json(directory, "review.json", review)
            missing = run_script("calculate_rubric_score.py", "--input", str(input_path))
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("missing", missing.stderr.lower())
            stale_rubric = json.loads(rubric_result.stdout)
            stale_rubric["pass_threshold_percent"] = 99
            stale_review = {
                "review_id": "REV-2",
                "task_id": "T-1",
                "resolved_rubric": stale_rubric,
                "criteria": [
                    {"id": criterion_id, "score": 4, "weight": weight, "mandatory": True, "minimum_score": 3, "applicability": "APPLICABLE", "evidence": "verified"}
                    for criterion_id, weight in stale_rubric["resolved_weights"].items()
                ],
                "findings": [],
            }
            stale_path = write_json(directory, "stale-review.json", stale_review)
            stale = run_script("calculate_rubric_score.py", "--input", str(stale_path))
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("hash", stale.stderr.lower())


if __name__ == "__main__":
    unittest.main()
