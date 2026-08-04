from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
sys.path.insert(0, str(SCRIPTS))

from create_batch_review import normalize as normalize_batch_review  # noqa: E402
from resolve_rubric import resolve_rubric  # noqa: E402
from validate_change_request import validate_change_request  # noqa: E402


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
    def test_resolved_rubric_contains_canonical_contract_fields(self) -> None:
        rubric = resolve_rubric("personal", "backend", {})
        self.assertEqual(rubric["risk_flags"], {})
        self.assertEqual(rubric["review_policy_version"], "1")

    def test_risk_flags_use_the_canonical_vocabulary(self) -> None:
        rubric = resolve_rubric("personal", "backend", {"authentication": True, "database": False})
        self.assertEqual(rubric["risk_flags"], {"authentication": True, "database": False})
        self.assertEqual(rubric["applicability"]["SECURITY"]["status"], "APPLICABLE")

    def test_risk_flags_reject_non_boolean_values_and_unknown_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "boolean"):
            resolve_rubric("personal", "backend", {"authentication": "yes"})
        with self.assertRaisesRegex(ValueError, "unknown"):
            resolve_rubric("personal", "backend", {"database_write": True})

    def test_change_request_rejects_legacy_risk_flags(self) -> None:
        request = {
            "change_request_id": "CR-RISK",
            "target_type": "MASTER_PLAN",
            "target_id": "MP-1",
            "target_version": "1.0",
            "new_version": "1.1",
            "reason": "risk contract",
            "requested_changes": [{"op": "replace", "path": "/title", "value": "new"}],
            "impact": {"risk_flags": {"database_write": True}},
            "status": "PROPOSED",
            "requested_by": "primary-agent",
            "approval_id": "APR-RISK",
            "supersedes_id": "MP-1@1.0",
        }
        with self.assertRaisesRegex(ValueError, "unknown risk flag"):
            validate_change_request(request, {"approval_id": "APR-RISK", "decision": "APPROVED"})
        request["impact"] = {"database_write": True}
        with self.assertRaisesRegex(ValueError, "schema validation"):
            validate_change_request(request, {"approval_id": "APR-RISK", "decision": "APPROVED"})

        request["impact"] = {"risk_flags": {}}
        request["requested_changes"] = [{"op": "replace", "path": "/risk_flags", "value": {"database_write": True}}]
        with self.assertRaisesRegex(ValueError, "unknown risk flag"):
            validate_change_request(request, {"approval_id": "APR-RISK", "decision": "APPROVED", "target_id": "CR-RISK"})

    def test_rubric_schema_uses_canonical_risk_flag_ref(self) -> None:
        schema = json.loads((SCHEMAS / "rubric.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["risk_flags"]["$ref"], "risk-flags.schema.json")

    def _resolved_review(self, directory: str, *, score: int = 4) -> tuple[dict, Path]:
        result = run_script("resolve_rubric.py", "--profile", "personal", "--task-type", "backend", "--risk-flags", "{}")
        self.assertEqual(result.returncode, 0, result.stderr)
        rubric = json.loads(result.stdout)
        criteria = [
            {
                "id": definition["id"],
                "score": score,
                "weight": definition["weight"],
                "mandatory": definition["mandatory"],
                "minimum_score": definition["minimum_score"],
                "applicability": "APPLICABLE",
                "evidence": "verification evidence",
            }
            for definition in rubric["criteria"]
            if definition["id"] in rubric["resolved_weights"]
        ]
        path = write_json(directory, "resolved-review.json", {
            "review_id": "REV-INTEGRITY",
            "task_id": "T-INTEGRITY",
            "resolved_rubric": rubric,
            "criteria": criteria,
            "hard_fail_checks": [
                {"rule": rule, "triggered": False, "evidence": "rule checked against the task evidence"}
                for rule in rubric["hard_fail_rules"]
            ],
            "findings": [],
        })
        return rubric, path

    def test_review_payload_cannot_lower_threshold_or_mandatory_minimum_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rubric, path = self._resolved_review(directory, score=0)
            review = json.loads(path.read_text(encoding="utf-8"))
            review["pass_threshold_percent"] = 0
            for criterion in review["criteria"]:
                criterion["mandatory"] = False
                criterion["minimum_score"] = 0
            path.write_text(json.dumps(review), encoding="utf-8")
            result = run_script("calculate_rubric_score.py", "--input", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("canonical", result.stderr.lower())

    def test_resolved_rubric_cannot_replace_canonical_policy_with_a_new_self_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rubric, path = self._resolved_review(directory, score=4)
            review = json.loads(path.read_text(encoding="utf-8"))
            rubric["pass_threshold_percent"] = 0
            without_hash = dict(rubric)
            without_hash.pop("rubric_hash", None)
            rubric["rubric_hash"] = hashlib.sha256(
                json.dumps(without_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            review["resolved_rubric"] = rubric
            path.write_text(json.dumps(review), encoding="utf-8")
            result = run_script("calculate_rubric_score.py", "--input", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("canonical", result.stderr.lower())

    def test_create_review_rejects_a_valid_rubric_from_the_wrong_task_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            canonical_result = run_script("resolve_rubric.py", "--profile", "personal", "--task-type", "backend", "--risk-flags", "{}")
            wrong_result = run_script("resolve_rubric.py", "--profile", "prototype", "--task-type", "backend", "--risk-flags", "{}")
            self.assertEqual(canonical_result.returncode, 0, canonical_result.stderr)
            self.assertEqual(wrong_result.returncode, 0, wrong_result.stderr)
            canonical = json.loads(canonical_result.stdout)
            wrong = json.loads(wrong_result.stdout)
            contract = {
                "project_profile": canonical["profile_id"],
                "profile_hash": canonical["profile_hash"],
                "task_type": canonical["task_type"],
                "risk_flags": canonical["risk_flags"],
                "review_type": canonical["review_type"],
                "rubric_id": canonical["rubric_id"],
                "rubric_version": canonical["rubric_version"],
                "rubric_hash": canonical["rubric_hash"],
                "review_policy_version": canonical["review_policy_version"],
            }
            for index, status in enumerate(("QUEUED", "RUNNING", "COMPLETED")):
                payload = {"task_id": "T-CONTRACT", "status": status, "review_contract": contract}
                if index:
                    payload["expected_revision"] = index
                task_input = write_json(directory, f"{status.lower()}.json", payload)
                updated = run_script("update_task_state.py", "--project-root", str(project), "--input", str(task_input))
                self.assertEqual(updated.returncode, 0, updated.stderr)
            criteria = [
                {
                    "id": item["id"],
                    "score": 4,
                    "weight": item["weight"],
                    "mandatory": item["mandatory"],
                    "minimum_score": item["minimum_score"],
                    "applicability": "APPLICABLE",
                    "evidence": "verified",
                }
                for item in wrong["criteria"]
                if item["id"] in wrong["resolved_weights"]
            ]
            review = write_json(directory, "wrong-review.json", {"task_id": "T-CONTRACT", "resolved_rubric": wrong, "criteria": criteria, "findings": []})
            result = run_script("create_review.py", "--project-root", str(project), "--input", str(review))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("contract", result.stderr.lower())

    def test_batch_review_requires_integration_regression_and_scope_checks(self) -> None:
        result = run_script("resolve_rubric.py", "--profile", "personal", "--task-type", "standard", "--review-type", "batch", "--risk-flags", "{}")
        self.assertEqual(result.returncode, 0, result.stderr)
        rubric = json.loads(result.stdout)
        criteria = [
            {
                "id": item["id"],
                "score": 4,
                "weight": item["weight"],
                "mandatory": item["mandatory"],
                "minimum_score": item["minimum_score"],
                "applicability": "APPLICABLE",
                "evidence": "verified",
            }
            for item in rubric["criteria"]
            if item["id"] in rubric["resolved_weights"]
        ]
        with self.assertRaises(ValueError):
            normalize_batch_review({
                "batch_id": "B-CHECKS",
                "task_reviews": ["REV-1"],
                "integration_checks": [{"kind": "integration", "name": "integration", "result": "PASS", "evidence": "verified"}],
                "findings": [],
                "resolved_rubric": rubric,
                "criteria": criteria,
            })

    def test_duplicate_review_criteria_are_rejected_instead_of_inflating_score(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, path = self._resolved_review(directory)
            review = json.loads(path.read_text(encoding="utf-8"))
            review["criteria"].append(dict(review["criteria"][0]))
            path.write_text(json.dumps(review), encoding="utf-8")
            result = run_script("calculate_rubric_score.py", "--input", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate", result.stderr.lower())

    def test_canonical_hard_fail_rule_cannot_be_omitted_from_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, path = self._resolved_review(directory)
            review = json.loads(path.read_text(encoding="utf-8"))
            review["hard_fail_rules"] = []
            review["findings"] = [{
                "rule": "acceptance_criteria_not_met",
                "severity": "MINOR",
                "evidence": "acceptance criterion is not met",
                "required_change": "repair the implementation",
                "resolved": False,
            }]
            path.write_text(json.dumps(review), encoding="utf-8")
            result = run_script("calculate_rubric_score.py", "--input", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hard", result.stderr.lower())

    def test_canonical_hard_fail_rules_require_explicit_evidence_and_trigger_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rubric, path = self._resolved_review(directory)
            review = json.loads(path.read_text(encoding="utf-8"))
            review.pop("hard_fail_checks")
            path.write_text(json.dumps(review), encoding="utf-8")
            missing = run_script("calculate_rubric_score.py", "--input", str(path))
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("hard_fail_checks", missing.stderr)

            review["hard_fail_checks"] = [
                {"rule": rule, "triggered": rule == rubric["hard_fail_rules"][0], "evidence": "rule checked against the task evidence"}
                for rule in rubric["hard_fail_rules"]
            ]
            path.write_text(json.dumps(review), encoding="utf-8")
            triggered = run_script("calculate_rubric_score.py", "--input", str(path))
            self.assertEqual(triggered.returncode, 0, triggered.stderr)
            self.assertIn('"verdict": "REPAIR_REQUIRED"', triggered.stdout)

    def test_rubric_and_change_approval_schemas_exist(self) -> None:
        self.assertTrue((SCHEMAS / "rubric.schema.json").is_file())
        self.assertTrue((SCHEMAS / "change-approval.schema.json").is_file())
        self.assertTrue((SCHEMAS / "review-contract.schema.json").is_file())

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

    def test_user_is_required_for_architecture_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            initialized = run_script("init_runtime.py", "--project-root", str(project))
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            approval = write_json(
                directory,
                "architecture-approval.json",
                {"target_type": "ARCHITECTURE_CHANGE", "target_id": "DEC-1", "decision": "APPROVED", "approver": "alice", "actor_type": "user", "actor_id": "alice", "action": "ARCHITECTURE_CHANGE", "target_revision": 1, "target_hash": "0" * 64, "policy_version": "1", "expires_at": "2026-08-04T00:00:00Z", "evidence": "reviewed"},
            )
            denied = run_script("record_approval.py", "--project-root", str(project), "--input", str(approval), "--actor", "task-reviewer")
            self.assertNotEqual(denied.returncode, 0)
            accepted = run_script("record_approval.py", "--project-root", str(project), "--input", str(approval), "--actor", "alice", "--actor-type", "user")
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
                    "requested_changes": [{"op": "add", "path": "/success_criteria/-", "value": "recovery release criterion"}],
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
                    "actor_type": "primary_agent",
                    "actor_id": "primary-agent",
                    "action": "CHANGE_REQUEST",
                    "target_revision": 1,
                    "target_hash": "0" * 64,
                    "policy_version": "1",
                    "expires_at": "2026-08-04T00:00:00Z",
                    "evidence": "approved recovery scope",
                    "created_at": "2026-08-02T00:00:00Z",
                    "revision": 1,
                },
            )
            rejected = run_script("validate_change_request.py", "--input", str(request))
            self.assertNotEqual(rejected.returncode, 0)
            valid = run_script("validate_change_request.py", "--input", str(request), "--approval", str(approval))
            self.assertEqual(valid.returncode, 0, valid.stderr)

            target = write_json(
                directory,
                "plan.json",
                {
                    "plan_id": "MP-1",
                    "version": "1.0",
                    "title": "Original",
                    "success_criteria": ["initial"],
                    "approval_id": "APR-OLD",
                    "review_id": "REV-OLD",
                },
            )
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
            self.assertEqual(new_plan["success_criteria"], ["initial", "recovery release criterion"])
            self.assertNotIn("approval_id", new_plan)
            self.assertNotIn("review_id", new_plan)
            self.assertRegex(new_plan.get("artifact_hash", ""), r"^[0-9a-f]{64}$")
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
            review = {"review_id": "REV-1", "task_id": "T-1", "resolved_rubric": rubric, "criteria": criteria, "hard_fail_checks": [{"rule": rule, "triggered": False, "evidence": "rule checked"} for rule in rubric["hard_fail_rules"]], "findings": []}
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
                "hard_fail_checks": [{"rule": rule, "triggered": False, "evidence": "rule checked"} for rule in stale_rubric["hard_fail_rules"]],
                "findings": [],
            }
            stale_path = write_json(directory, "stale-review.json", stale_review)
            stale = run_script("calculate_rubric_score.py", "--input", str(stale_path))
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("hash", stale.stderr.lower())


if __name__ == "__main__":
    unittest.main()
