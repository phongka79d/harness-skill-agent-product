from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
sys.path.insert(0, str(SCRIPTS))

from create_batch_review import normalize as normalize_batch_review  # noqa: E402
from create_review import _authorize_review_override  # noqa: E402
from resolve_rubric import resolve_rubric  # noqa: E402
from validate_change_request import validate_change_request  # noqa: E402
from validate_change_request import TARGET_ID_FIELDS, validate_operations  # noqa: E402
from apply_change_request import _apply_operation, _find_invalidations, _validate_patch_operation, apply_operations, artifact_hash  # noqa: E402
from validate_transition import validate_transition  # noqa: E402


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
    def _authorized_change_fixture(self, directory: str, *, target_type: str = "MASTER_PLAN") -> tuple[Path, Path, Path, dict, dict]:
        project = Path(directory) / "project"
        self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
        target = {
            "plan_id" if target_type == "MASTER_PLAN" else "task_id": "MP-AUTH" if target_type == "MASTER_PLAN" else "T-AUTH",
            "version": "1.0",
            "revision": 4,
            "title": "Original",
        }
        target_path = project / "target.json"
        target_path.write_text(json.dumps(target), encoding="utf-8")
        change_request = {
            "change_request_id": "CR-AUTH",
            "target_type": target_type,
            "target_id": target["plan_id" if target_type == "MASTER_PLAN" else "task_id"],
            "target_version": "1.0",
            "new_version": "1.1",
            "reason": "authorized change",
            "requested_changes": [{"op": "replace", "path": "/title", "value": "Changed"}],
            "impact": {"risk_flags": {}},
            "status": "APPROVED",
            "requested_by": "primary-agent",
            "approval_id": "APR-AUTH",
            "supersedes_id": f"{target['plan_id'] if target_type == 'MASTER_PLAN' else target['task_id']}@1.0",
        }
        request_path = Path(directory) / "change.json"
        request_path.write_text(json.dumps(change_request), encoding="utf-8")
        approval = {
            "approval_id": "APR-AUTH",
            "target_type": target_type,
            "target_id": change_request["target_id"],
            "decision": "APPROVED",
            "approver": "primary-agent",
            "actor_type": "primary_agent",
            "actor_id": "primary-agent",
            "action": "CHANGE_REQUEST",
            "target_revision": target["revision"],
            "target_hash": artifact_hash(target),
            "policy_version": "1",
            "issued_at": "2026-08-04T00:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "evidence": "persisted change approval",
        }
        approval_path = Path(directory) / "approval.json"
        approval_path.write_text(json.dumps(approval), encoding="utf-8")
        return project, target_path, request_path, approval, change_request

    def test_apply_change_requires_persisted_actor_bound_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, target_path, request_path, approval, _ = self._authorized_change_fixture(directory)
            forged_path = Path(directory) / "forged-approval.json"
            forged = {**approval, "evidence": "forged"}
            forged_path.write_text(json.dumps(forged), encoding="utf-8")
            output_path = project / "changed.json"
            rejected = run_script(
                "apply_change_request.py", "--request", str(request_path), "--target", str(target_path),
                "--approval", str(forged_path), "--output", str(output_path),
                "--actor", "primary-agent", "--actor-type", "primary_agent",
            )
            self.assertNotEqual(rejected.returncode, 0)
            (project / ".agent" / "approvals").mkdir(parents=True, exist_ok=True)
            (project / ".agent" / "approvals" / "MASTER_PLAN-MP-AUTH.json").write_text(json.dumps(approval), encoding="utf-8")
            accepted = run_script(
                "apply_change_request.py", "--request", str(request_path), "--target", str(target_path),
                "--approval", str(approval_path := Path(directory) / "approval.json"), "--output", str(output_path),
                "--actor", "primary-agent", "--actor-type", "primary_agent",
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_uninitialized_change_is_rejected_without_creating_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            target = write_json(directory, "uninitialized-target.json", {
                "plan_id": "MP-UNINITIALIZED",
                "version": "1.0",
                "revision": 1,
                "title": "Original",
            })
            request = write_json(directory, "uninitialized-change.json", {
                "change_request_id": "CR-UNINITIALIZED",
                "target_type": "MASTER_PLAN",
                "target_id": "MP-UNINITIALIZED",
                "target_version": "1.0",
                "new_version": "1.1",
                "reason": "must not initialize implicitly",
                "requested_changes": [{"op": "replace", "path": "/title", "value": "Changed"}],
                "impact": {"risk_flags": {}},
                "status": "APPROVED",
                "requested_by": "primary-agent",
                "approval_id": "APR-UNINITIALIZED",
                "supersedes_id": "MP-UNINITIALIZED@1.0",
            })
            approval = write_json(directory, "uninitialized-approval.json", {
                "approval_id": "APR-UNINITIALIZED",
                "target_type": "CHANGE_REQUEST",
                "target_id": "CR-UNINITIALIZED",
                "decision": "APPROVED",
            })
            result = run_script(
                "apply_change_request.py",
                "--request", str(request),
                "--target", str(target),
                "--approval", str(approval),
                "--output", str(project / "changed.json"),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((project / ".agent").exists())
            self.assertFalse((project / "changed.json").exists())

    def test_task_change_supersedes_history_invalidates_bound_artifacts_and_records_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, target_path, request_path, approval, change_request = self._authorized_change_fixture(directory, target_type="TASK")
            root = project / ".agent"
            (root / "approvals").mkdir(parents=True, exist_ok=True)
            (root / "approvals" / "TASK-T-AUTH.json").write_text(json.dumps(approval), encoding="utf-8")
            (root / "work" / "T-AUTH").mkdir(parents=True)
            bound = {"task_id": "T-AUTH", "task_revision": 4, "plan_revision": 4, "target_hash": approval["target_hash"]}
            for name, value in (
                ("review.json", {**bound, "review_id": "REV-OLD"}),
                ("review-contract.json", {**bound, "contract_id": "RC-OLD"}),
                ("batch-contract.json", {**bound, "contract_id": "BC-OLD"}),
            ):
                path = root / "work" / ("T-AUTH" if name != "batch-contract.json" else "B-OLD") / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value), encoding="utf-8")
            queue = root / "runtime" / "queue.json"
            queue.write_text(json.dumps({"dispatches": [{**bound, "dispatch_id": "DSP-OLD"}]}), encoding="utf-8")
            recovery_artifact = root / "recovery" / "old.json"
            recovery_artifact.parent.mkdir(parents=True, exist_ok=True)
            recovery_artifact.write_text(json.dumps({**bound, "artifact": "outside-family"}), encoding="utf-8")
            approval_path = Path(directory) / "task-approval.json"
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            output_path = project / "task-v1.1.json"
            applied = run_script(
                "apply_change_request.py", "--request", str(request_path), "--target", str(target_path),
                "--approval", str(approval_path), "--output", str(output_path),
                "--actor", "primary-agent", "--actor-type", "primary_agent",
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            historical = json.loads(target_path.read_text(encoding="utf-8"))
            changed = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(historical["status"], "SUPERSEDED")
            self.assertEqual(changed["revision"], 5)
            self.assertRegex(changed["artifact_hash"], r"^[0-9a-f]{64}$")
            for path in (root / "work/T-AUTH/review.json", root / "work/T-AUTH/review-contract.json", root / "work/B-OLD/batch-contract.json", queue):
                self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["invalidated"])
            self.assertNotIn("invalidated", json.loads(recovery_artifact.read_text(encoding="utf-8")))
            events = [json.loads(line) for line in (root / "runtime/events.jsonl").read_text(encoding="utf-8").splitlines()]
            invalidations = [event for event in events if event["type"] == "ARTIFACT_INVALIDATED"]
            self.assertGreaterEqual(len(invalidations), 4)
            self.assertTrue(all(event["data"]["change_request_id"] == change_request["change_request_id"] for event in invalidations))

    def test_change_requests_use_exact_target_id_fields_and_json_patch_operations(self) -> None:
        self.assertEqual(TARGET_ID_FIELDS, {
            "MASTER_PLAN": "plan_id",
            "SUB_PLAN": "sub_plan_id",
            "BATCH": "batch_id",
            "TASK": "task_id",
            "DECISION": "decision_id",
            "RISK": "risk_id",
            "RUBRIC": "rubric_id",
            "PROFILE": "profile_id",
            "CONFIGURATION": "configuration_id",
        })
        operations = validate_operations([
            {"op": "add", "path": "/items/-", "value": 3},
            {"op": "test", "path": "/items/0", "value": 1},
            {"op": "copy", "from": "/name", "path": "/alias"},
            {"op": "move", "from": "/alias", "path": "/display_name"},
            {"op": "replace", "path": "/name", "value": "new"},
            {"op": "remove", "path": "/obsolete"},
        ], applying=True)
        self.assertEqual(apply_operations({"name": "old", "items": [1, 2], "obsolete": True}, operations), {
            "name": "new", "items": [1, 2, 3], "display_name": "old",
        })

    def test_direct_patch_application_rejects_invalid_operations_and_supports_array_end(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown JSON Patch operation"):
            _apply_operation({"value": 1}, {"op": "explode", "path": "/value"})
        with self.assertRaisesRegex(ValueError, "requires value"):
            apply_operations({"value": 1}, [{"op": "replace", "path": "/value"}])
        with self.assertRaisesRegex(ValueError, "JSON Pointer"):
            apply_operations({"value": 1}, [{"op": "remove", "path": "value"}])
        self.assertEqual(
            apply_operations({"items": [1]}, [{"op": "add", "path": "/items/1", "value": 2}]),
            {"items": [1, 2]},
        )

    def test_patch_operations_require_exact_fields_at_direct_and_request_boundaries(self) -> None:
        invalid_operations = [
            {"op": "add", "path": "/value", "value": 1, "from": "/old"},
            {"op": "replace", "path": "/value", "value": 1, "from": "/old"},
            {"op": "test", "path": "/value", "value": 1, "from": "/old"},
            {"op": "remove", "path": "/value", "value": 1},
            {"op": "move", "path": "/value", "from": "/old", "value": 1},
            {"op": "copy", "path": "/value", "from": "/old", "value": 1},
            {"op": "replace", "path": "/value", "value": 1, "extra": True},
            {"op": "replace", "path": "/bad~2pointer", "value": 1},
        ]
        for operation in invalid_operations:
            with self.subTest(operation=operation):
                with self.assertRaises(ValueError):
                    _validate_patch_operation(operation)
                with self.assertRaises(ValueError):
                    validate_operations([operation], applying=True)

    def test_invalidation_requires_coherent_binding_and_only_scans_artifact_families(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, target_path, request_path, approval, change_request = self._authorized_change_fixture(directory, target_type="TASK")
            root = project / ".agent"
            (root / "approvals").mkdir(parents=True, exist_ok=True)
            (root / "approvals" / "TASK-T-AUTH.json").write_text(json.dumps(approval), encoding="utf-8")
            bound = {"task_revision": 4, "target_hash": approval["target_hash"]}
            work = root / "work" / "T-AUTH"
            work.mkdir(parents=True, exist_ok=True)
            (work / "review.json").write_text(json.dumps({**bound, "review_id": "REV-BOUND"}), encoding="utf-8")
            (work / "review-contract-input.json").write_text(json.dumps({
                "task_revision": 4,
                "input_artifact_hashes": {"plan": approval["target_hash"]},
            }), encoding="utf-8")
            (work / "review-coincidental.json").write_text(json.dumps({
                "task_revision": 4,
                "target_hash": "b" * 64,
            }), encoding="utf-8")
            (work / "task-state.json").write_text(json.dumps(bound), encoding="utf-8")
            (work / "lease.json").write_text(json.dumps(bound), encoding="utf-8")
            (work / "checkpoint.json").write_text(json.dumps(bound), encoding="utf-8")
            (work / "operations.json").write_text(json.dumps(bound), encoding="utf-8")
            (work / "unrelated.json").write_text(json.dumps(bound), encoding="utf-8")
            recovery_review = work / "recovery" / "review.json"
            recovery_review.parent.mkdir(parents=True, exist_ok=True)
            recovery_review.write_text(json.dumps(bound), encoding="utf-8")
            queue = root / "runtime" / "queue.json"
            queue.write_text(json.dumps({"dispatches": [{**bound, "dispatch_id": "DSP-BOUND"}]}), encoding="utf-8")
            approval_path = Path(directory) / "task-approval.json"
            approval_path.write_text(json.dumps(approval), encoding="utf-8")
            applied = run_script(
                "apply_change_request.py", "--request", str(request_path), "--target", str(target_path),
                "--approval", str(approval_path), "--output", str(project / "task-v1.1.json"),
                "--actor", "primary-agent", "--actor-type", "primary_agent",
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            invalidated = [work / "review.json", work / "review-contract-input.json", queue, root / "approvals" / "TASK-T-AUTH.json"]
            for path in invalidated:
                self.assertTrue(json.loads(path.read_text(encoding="utf-8")).get("invalidated"), path)
            for path in (work / "review-coincidental.json", work / "task-state.json", work / "lease.json", work / "checkpoint.json", work / "operations.json", work / "unrelated.json", recovery_review):
                self.assertNotIn("invalidated", json.loads(path.read_text(encoding="utf-8")), path)
            events = [json.loads(line) for line in (root / "runtime/events.jsonl").read_text(encoding="utf-8").splitlines()]
            candidates = [event for event in events if event["type"] == "ARTIFACT_INVALIDATED"]
            self.assertEqual(len(candidates), len(invalidated))
            self.assertEqual({event["data"]["artifact_path"] for event in candidates}, {
                path.relative_to(root).as_posix() for path in invalidated
            })

    def test_review_override_uses_exact_persisted_approval_and_approval_bound_actor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".agent"
            approvals = root / "approvals"
            approvals.mkdir(parents=True)
            approval = {
                "approval_id": "APR-REVIEW-OVERRIDE",
                "target_type": "RUBRIC_OVERRIDE",
                "target_id": "T-OVERRIDE",
                "decision": "APPROVED",
                "approver": "primary-agent",
                "actor_type": "primary_agent",
                "actor_id": "primary-agent",
                "action": "REVIEW_OVERRIDE",
                "target_revision": 2,
                "target_hash": "c" * 64,
                "policy_version": "1",
                "issued_at": "2026-08-03T00:00:00Z",
                "expires_at": "2099-01-01T00:00:00Z",
                "evidence": "approved review override",
            }
            (approvals / "RUBRIC_OVERRIDE-T-OVERRIDE.json").write_text(json.dumps(approval), encoding="utf-8")
            self.assertEqual(_authorize_review_override(root, approval["approval_id"]), approval)
            forged = dict(approval)
            forged["target_hash"] = "d" * 64
            (approvals / "RUBRIC_OVERRIDE-T-OVERRIDE.json").write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "target hash"):
                _authorize_review_override(root, approval["approval_id"], expected_target_hash=approval["target_hash"])

    def test_change_request_rejects_type_specific_target_id_mismatch(self) -> None:
        request = {
            "change_request_id": "CR-ID",
            "target_type": "TASK",
            "target_id": "T-EXPECTED",
            "target_version": "1.0",
            "new_version": "1.1",
            "reason": "fence target",
            "requested_changes": [{"op": "replace", "path": "/title", "value": "new"}],
            "impact": {"risk_flags": {}},
            "status": "PROPOSED",
            "requested_by": "primary-agent",
            "approval_id": "APR-ID",
            "supersedes_id": "T-EXPECTED@1.0",
        }
        with self.assertRaisesRegex(ValueError, "task_id"):
            validate_change_request(request, {"approval_id": "APR-ID", "decision": "APPROVED"}, target={"task_id": "T-WRONG"})

    def test_test_operations_are_run_before_a_change_is_published(self) -> None:
        target = {"name": "old", "value": 1}
        operations = [
            {"op": "replace", "path": "/name", "value": "new"},
            {"op": "test", "path": "/value", "value": 99},
        ]
        with self.assertRaisesRegex(ValueError, "test"):
            apply_operations(target, operations)
        self.assertEqual(target, {"name": "old", "value": 1})

    def test_review_transition_guards_fail_closed_for_missing_or_mismatched_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "same_run"):
            validate_transition("COMPLETED", "REVIEWING", actor="reviewer", evidence={})

        identity = {"run_id": "RUN-1", "attempt_id": "ATTEMPT-1", "dispatch_id": "DISPATCH-1"}
        evidence = {
            "task_state": {"task_id": "T-1", **identity},
            "review": {"task_id": "T-1", **identity},
            "lease": {"task_id": "T-1", **identity},
            "dispatch": {"task_id": "T-1", **identity},
        }
        self.assertEqual(
            validate_transition("COMPLETED", "REVIEWING", actor="reviewer", evidence=evidence)["to"],
            "REVIEWING",
        )
        mismatched = json.loads(json.dumps(evidence))
        mismatched["lease"]["attempt_id"] = "ATTEMPT-WRONG"
        with self.assertRaisesRegex(ValueError, "same_attempt"):
            validate_transition("REVIEWING", "ACCEPTED", actor="reviewer", evidence=mismatched)

    def test_invalidation_candidate_cap_is_enforced_during_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, _, _, approval, _ = self._authorized_change_fixture(directory, target_type="TASK")
            work = project / ".agent" / "work" / "T-AUTH"
            work.mkdir(parents=True, exist_ok=True)
            bound = {"task_revision": 4, "target_hash": approval["target_hash"]}
            for index in range(3):
                candidate = project / ".agent" / "work" / f"T-AUTH-{index}" / "review.json"
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text(json.dumps(bound), encoding="utf-8")
            import apply_change_request as change_request_module
            with patch.object(change_request_module, "MAX_INVALIDATION_ARTIFACTS", 2):
                with self.assertRaisesRegex(ValueError, "artifact count limit"):
                    _find_invalidations(
                        project,
                        old_revision=4,
                        old_hash=approval["target_hash"],
                        change_request_id="CR-AUTH",
                    )

    def test_unreadable_invalidation_candidate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, _, _, approval, _ = self._authorized_change_fixture(directory, target_type="TASK")
            work = project / ".agent" / "work" / "T-AUTH"
            work.mkdir(parents=True, exist_ok=True)
            candidate = work / "review.json"
            candidate.write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "candidate.*unreadable"):
                _find_invalidations(
                    project,
                    old_revision=4,
                    old_hash=approval["target_hash"],
                    change_request_id="CR-AUTH",
                )

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

    def _approved_override_review_fixture(self, directory: str, *, approval_target_id: str = "T-OVERRIDE") -> tuple[Path, Path, dict]:
        project = Path(directory) / "project"
        self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
        canonical_result = run_script("resolve_rubric.py", "--profile", "personal", "--task-type", "backend", "--risk-flags", "{}")
        self.assertEqual(canonical_result.returncode, 0, canonical_result.stderr)
        canonical = json.loads(canonical_result.stdout)
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
        task_id = "T-OVERRIDE"
        identity = {
            "run_id": "RUN-OVERRIDE",
            "attempt_id": "ATTEMPT-OVERRIDE",
            "dispatch_id": "DISPATCH-OVERRIDE",
        }
        for index, status in enumerate(("QUEUED", "RUNNING", "COMPLETED")):
            task_input = write_json(directory, f"override-{status.lower()}.json", {
                "task_id": task_id,
                "status": status,
                "review_contract": contract,
                **identity,
                **({"expected_revision": index} if index else {}),
            })
            updated = run_script("update_task_state.py", "--project-root", str(project), "--input", str(task_input))
            self.assertEqual(updated.returncode, 0, updated.stderr)
        current_task = json.loads((project / ".agent" / "work" / task_id / "task-state.json").read_text(encoding="utf-8"))
        (project / ".agent" / "work" / task_id / "lease.json").write_text(
            json.dumps({"task_id": task_id, **identity}),
            encoding="utf-8",
        )
        (project / ".agent" / "runtime" / "queue.json").write_text(
            json.dumps({"dispatches": [{"task_id": task_id, **identity}]}),
            encoding="utf-8",
        )

        override_result = run_script(
            "resolve_rubric.py", "--profile", "personal", "--task-type", "backend", "--risk-flags", "{}",
            "--overrides", json.dumps({
                "threshold_percent": 70,
                "weight_overrides": {"CORRECTNESS": 1},
                "approval_id": "APR-OVERRIDE",
                "approval_decision": "APPROVED",
            }),
        )
        self.assertEqual(override_result.returncode, 0, override_result.stderr)
        override = json.loads(override_result.stdout)
        approval = {
            "approval_id": "APR-OVERRIDE",
            "target_type": "RUBRIC_OVERRIDE",
            "target_id": approval_target_id,
            "decision": "APPROVED",
            "approver": "primary-agent",
            "actor_type": "primary_agent",
            "actor_id": "primary-agent",
            "action": "REVIEW_OVERRIDE",
            "target_revision": current_task["revision"],
            "target_hash": override["rubric_hash"],
            "policy_version": "1",
            "issued_at": "2026-08-03T00:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "evidence": "approved review rubric override",
        }
        approvals = project / ".agent" / "approvals"
        approvals.mkdir(parents=True, exist_ok=True)
        (approvals / f"RUBRIC_OVERRIDE-{approval_target_id}.json").write_text(json.dumps(approval), encoding="utf-8")
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
            for item in override["criteria"]
            if item["id"] in override["resolved_weights"]
        ]
        review = write_json(directory, "override-review.json", {
            "task_id": task_id,
            "resolved_rubric": override,
            "criteria": criteria,
            "hard_fail_checks": [
                {"rule": rule, "triggered": False, "evidence": "rule checked"}
                for rule in override["hard_fail_rules"]
            ],
            "findings": [],
        })
        return project, review, approval

    def test_create_review_accepts_exact_task_bound_approved_rubric_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, review, approval = self._approved_override_review_fixture(directory)
            result = run_script("create_review.py", "--project-root", str(project), "--input", str(review), "--actor", "primary-agent")
            self.assertEqual(result.returncode, 0, result.stderr)
            written = json.loads((project / ".agent" / "work" / "T-OVERRIDE" / "review.json").read_text(encoding="utf-8"))
            self.assertEqual(written["resolved_rubric"]["rubric_hash"], approval["target_hash"])
            self.assertEqual(written["verdict"], "PASS")

    def test_create_review_rejects_approved_override_for_wrong_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, review, _ = self._approved_override_review_fixture(directory, approval_target_id="T-WRONG")
            result = run_script("create_review.py", "--project-root", str(project), "--input", str(review), "--actor", "primary-agent")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("target id", result.stderr.lower())

    def test_create_review_rejects_mismatched_execution_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, review, _ = self._approved_override_review_fixture(directory)
            payload = json.loads(review.read_text(encoding="utf-8"))
            payload["run_id"] = "RUN-WRONG"
            review.write_text(json.dumps(payload), encoding="utf-8")
            result = run_script("create_review.py", "--project-root", str(project), "--input", str(review), "--actor", "primary-agent")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("run_id", result.stderr.lower())

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
            project = Path(directory) / "project"
            initialized = run_script("init_runtime.py", "--project-root", str(project))
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
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
            target = project / "plan.json"
            target_value = {
                "plan_id": "MP-1",
                "version": "1.0",
                "revision": 1,
                "title": "Original",
                "success_criteria": ["initial"],
                "approval_id": "APR-OLD",
                "review_id": "REV-OLD",
            }
            target.write_text(json.dumps(target_value), encoding="utf-8")
            approval_value = {
                "approval_id": "APR-1",
                "target_type": "MASTER_PLAN",
                "target_id": "MP-1",
                "decision": "APPROVED",
                "approver": "primary-agent",
                "actor_type": "primary_agent",
                "actor_id": "primary-agent",
                "action": "CHANGE_REQUEST",
                "target_revision": 1,
                "target_hash": artifact_hash(target_value),
                "policy_version": "1",
                "issued_at": "2026-08-03T00:00:00Z",
                "expires_at": "2099-01-01T00:00:00Z",
                "evidence": "approved recovery scope",
            }
            approval = write_json(directory, "approval.json", approval_value)
            persisted = project / ".agent" / "approvals" / "MASTER_PLAN-MP-1.json"
            persisted.parent.mkdir(parents=True, exist_ok=True)
            persisted.write_text(json.dumps(approval_value), encoding="utf-8")
            rejected = run_script("validate_change_request.py", "--input", str(request))
            self.assertNotEqual(rejected.returncode, 0)
            valid = run_script("validate_change_request.py", "--input", str(request), "--approval", str(approval))
            self.assertEqual(valid.returncode, 0, valid.stderr)

            output = project / "plan-v1.1.json"
            applied = run_script(
                "apply_change_request.py",
                "--request", str(request),
                "--target", str(target),
                "--approval", str(approval),
                "--output", str(output),
                "--actor", "primary-agent",
                "--actor-type", "primary_agent",
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
