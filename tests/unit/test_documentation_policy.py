from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
STATE_SCRIPTS = ROOT / "skills/agentic-state-tools/scripts"
sys.path.insert(0, str(STATE_SCRIPTS))
import validate_examples  # noqa: E402
from validate_examples import (  # noqa: E402
    _init_project,
    _negative_outcome,
    _positive_batch_contract_errors,
    _positive_runtime_errors,
    _project_cli,
    _run_command,
    _write_json,
    validate_all_examples,
)


POLICY_DOCUMENTS = [
    ROOT / "skills/agentic-engineering-wiki/refs/contracts/planning.md",
    ROOT / "skills/agentic-engineering-wiki/refs/contracts/handoff.md",
    ROOT / "skills/agentic-engineering-wiki/refs/contracts/rubric.md",
    ROOT / "skills/agentic-engineering-wiki/refs/contracts/batch.md",
    ROOT / "skills/agentic-engineering-wiki/refs/contracts/async-execution.md",
    ROOT / "skills/agentic-engineering-wiki/refs/contracts/transactions.md",
    ROOT / "skills/agentic-engineering-wiki/refs/contracts/authorization.md",
    ROOT / "skills/agentic-engineering-wiki/refs/contracts/packaging.md",
    ROOT / "skills/agentic-engineering-wiki/refs/contracts/testing.md",
    ROOT / "skills/agentic-engineering-wiki/schemas/index.md",
    ROOT / "skills/agentic-state-tools/SKILL.md",
    ROOT / "skills/agentic-state-tools/references/artifact-contracts.md",
    ROOT / "skills/agentic-task-reviewer/references/review-contract.md",
    ROOT / "skills/agentic-batch-reviewer/references/batch-contract.md",
    ROOT / "skills/agentic-engineering-core/references/architecture/architecture.md",
    ROOT / "skills/agentic_engineering_system_complete_specification.md",
]
STATUS_NAMES = ("ENFORCED", "VALIDATED_ONLY", "DECLARATIVE_ONLY", "NOT_IMPLEMENTED")
STATUS_PATTERN = re.compile(r"^Policy status:\s*(?:" + "|".join(STATUS_NAMES) + r")\b", re.MULTILINE)
ENFORCED_SCRIPT_PATTERN = re.compile(r"enforced by [`']([^`']+)[`']", re.IGNORECASE)
FEATURE_REFERENCE_PATTERN = re.compile(r"\b(command|schema)=([^\s;]+)", re.IGNORECASE)
APPROVED_SCRIPT_ROOTS = (
    ROOT / "skills/agentic-state-tools/scripts",
    ROOT / "skills/agentic-engineering-wiki/scripts",
)


def _read_example(name: str) -> dict:
    path = ROOT / "skills/agentic-state-tools/examples" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _read_project_json(project: Path, relative_path: str) -> dict:
    return json.loads((project / relative_path).read_text(encoding="utf-8"))


def _build_master_plan_approval(plan_hash: str) -> dict:
    return {
        "approval_id": "APR-MP-V1-1",
        "target_type": "MASTER_PLAN",
        "target_id": "MP-V1",
        "decision": "APPROVED",
        "approver": "primary-agent",
        "actor_type": "primary_agent",
        "actor_id": "primary-agent",
        "action": "MASTER_PLAN",
        "target_revision": 1,
        "target_hash": plan_hash,
        "policy_version": "1",
        "issued_at": "2026-08-04T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "evidence": "non-legacy CLI smoke test",
        "created_at": "2026-08-04T00:00:00Z",
        "revision": 1,
    }


def _build_task_state(
    task_id: str,
    batch_id: str,
    status: str,
    task_contract: dict,
    *,
    include_runtime_identity: bool = False,
) -> dict:
    state = {
        "task_id": task_id,
        "batch_id": batch_id,
        "plan_revision": 1,
        "revision": 1,
        "owner": "agent-executor",
        "status": status,
        "review_contract": task_contract,
    }
    if include_runtime_identity:
        state.update(
            {
                "run_id": "RUN-V1",
                "attempt_id": "ATTEMPT-V1",
                "dispatch_id": "DSP-V1",
            }
        )
    return state


def policy_errors(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    statuses = [match.group(0).split(":", 1)[1].strip().split()[0] for match in STATUS_PATTERN.finditer(text)]
    if len(statuses) != 1:
        errors.append(
            f"{path}: expected exactly one policy status, found {len(statuses)}"
        )
    elif statuses[0] == "ENFORCED":
        match = ENFORCED_SCRIPT_PATTERN.search(text)
        if not match:
            errors.append(f"{path}: ENFORCED must name the enforcing script or validator")
        else:
            referenced = match.group(1)
            candidate = ROOT / referenced
            if not candidate.is_file():
                errors.append(f"{path}: ENFORCED references missing script or validator {referenced}")
            elif candidate.suffix != ".py" or not any(candidate.parent == root for root in APPROVED_SCRIPT_ROOTS):
                errors.append(
                    f"{path}: ENFORCED must reference a Python script in an approved scripts directory: {referenced}"
                )
    for line in text.splitlines():
        if not line.lstrip().startswith("- Feature:"):
            continue
        references = FEATURE_REFERENCE_PATTERN.findall(line)
        if not references:
            errors.append(f"{path}: documented feature has no command or schema: {line.strip()}")
            continue
        for kind, raw_reference in references:
            reference = raw_reference.strip("`'\".,")
            if reference.casefold() == "none":
                if "STATUS=NOT_IMPLEMENTED" not in line.upper():
                    errors.append(f"{path}: {kind} reference must name an existing repository path: {reference}")
                continue
            candidate = (ROOT / reference).resolve()
            try:
                candidate.relative_to(ROOT.resolve())
            except ValueError:
                errors.append(f"{path}: {kind} reference escapes the repository: {reference}")
                continue
            if not candidate.is_file():
                errors.append(f"{path}: references missing {kind} path {reference}")
    return errors


class DocumentationPolicyTests(unittest.TestCase):
    def test_examples_agree_with_declared_runtime_results(self) -> None:
        errors = validate_all_examples(
            ROOT / "skills/agentic-state-tools/examples",
            deployment_path=ROOT / "skills/agentic-configuration/config/deployment.test.json",
        )
        self.assertEqual(errors, [])

    def test_context_positive_example_uses_its_owning_cli(self) -> None:
        payload = _read_example("context.json")
        self.assertEqual(_positive_runtime_errors(Path("context.json"), payload), [])

    def test_task_state_positive_uses_update_task_state_cli(self) -> None:
        payload = _read_example("task-state.json")
        self.assertEqual(_positive_runtime_errors(Path("task-state.json"), payload), [])

    def test_run_command_converts_timeout_to_structured_failure(self) -> None:
        timeout = subprocess.TimeoutExpired(cmd=["python", "fixture.py"], timeout=20)
        with patch("validate_examples.subprocess.run", side_effect=timeout):
            self.assertEqual(_run_command(["python", "fixture.py"]), (124, "fixture.py: timed out"))

    def test_batch_contract_positive_binds_the_provided_value(self) -> None:
        payload = _read_example("batch-contract.json")
        payload["batch_id"] = "MUTATED-BATCH"
        self.assertTrue(_positive_batch_contract_errors(payload))

    def test_context_adapter_passes_custom_examples_root_payload_to_cli(self) -> None:
        payload = _read_example("context.json")
        payload["task"]["objective"] = "custom objective reaches create_context.py"
        with tempfile.TemporaryDirectory() as directory:
            examples_root = Path(directory)
            _write_json(examples_root / "context.json", payload)
            errors = validate_all_examples(
                examples_root,
                deployment_path=ROOT / "skills/agentic-configuration/config/deployment.test.json",
            )
        self.assertEqual(errors, [])

    def _assert_mutated_adapter_rejected(self, name: str, mutate) -> None:
        path = ROOT / "skills/agentic-state-tools/examples" / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutate(payload)
        self.assertTrue(_positive_runtime_errors(Path(name), payload))

    def test_operation_adapter_rejects_mutated_command(self) -> None:
        self._assert_mutated_adapter_rejected("operation.json", lambda payload: payload.__setitem__("command", ""))

    def test_isolation_adapter_rejects_mutated_branch(self) -> None:
        self._assert_mutated_adapter_rejected(
            "isolation-proof.json",
            lambda payload: payload.__setitem__("branch_name", ""),
        )

    def test_transaction_adapter_rejects_mutated_operation_type(self) -> None:
        self._assert_mutated_adapter_rejected(
            "transaction.json",
            lambda payload: payload.__setitem__("operation_type", ""),
        )

    def test_recovery_adapter_rejects_mutated_workspace_evidence(self) -> None:
        self._assert_mutated_adapter_rejected(
            "v1-recovery.json",
            lambda payload: payload["workspace"].__setitem__("mismatch", False),
        )

    def test_release_report_template_has_required_restriction(self) -> None:
        template = (ROOT / "docs/release-report-template.md").read_text(encoding="utf-8")
        for heading in (
            "## Modified Files",
            "## New Files",
            "## Contract Changes",
            "## Test Results",
            "## Remaining Limitations",
            "## Final Verdict",
        ):
            self.assertEqual(template.count(heading), 1)
        for header in (
            "| File | Change | Reason |",
            "| File | Role |",
            "| Contract | Before | After |",
            "| Test group | Passed | Failed | Skipped | Duration |",
        ):
            self.assertEqual(template.count(header), 1)
        self.assertIn(
            "READY is forbidden when runtime identity, async isolation, or release tests are failing",
            template,
        )
        self.assertEqual(
            template.count("`READY`, `READY_WITH_RESTRICTIONS`, or `NOT_READY`"),
            1,
        )

    def test_nonlegacy_review_and_batch_review_cli_smoke(self) -> None:
        scripts = STATE_SCRIPTS

        def resolve_rubric(project: Path, *, task_type: str, review_type: str) -> dict:
            code, output = _run_command(
                [
                    sys.executable,
                    str(scripts / "resolve_rubric.py"),
                    "--profile",
                    "personal",
                    "--task-type",
                    task_type,
                    "--review-type",
                    review_type,
                    "--risk-flags",
                    "{}",
                ],
                cwd=project,
            )
            self.assertEqual(code, 0, output)
            return json.loads(output)

        def contract_from_rubric(rubric: dict) -> dict:
            return {
                "project_profile": rubric["profile_id"],
                "profile_hash": rubric["profile_hash"],
                "task_type": rubric["task_type"],
                "risk_flags": rubric["risk_flags"],
                "review_type": rubric["review_type"],
                "rubric_id": rubric["rubric_id"],
                "rubric_version": rubric["rubric_version"],
                "rubric_hash": rubric["rubric_hash"],
                "review_policy_version": rubric["review_policy_version"],
            }

        def passing_criteria(rubric: dict) -> list[dict]:
            criteria = []
            applicable_ids = set(rubric["resolved_weights"])
            for definition in rubric["criteria"]:
                if definition["id"] not in applicable_ids:
                    continue
                criterion = dict(definition)
                criterion["score"] = 4
                criterion["evidence"] = "non-legacy CLI smoke test passed"
                if criterion.get("applicability") == "NOT_APPLICABLE":
                    criterion["reason"] = "not applicable to this smoke test"
                criteria.append(criterion)
            return criteria

        def assert_passing_score(review: dict, rubric: dict) -> None:
            denominator = sum(rubric["resolved_weights"].values())
            self.assertEqual(review["score_percent"], 100.0)
            self.assertEqual(review["threshold_percent"], rubric["pass_threshold_percent"])
            self.assertEqual(review["denominator_weight"], denominator)
            self.assertFalse(review["hard_fail"])
            self.assertFalse(review["insufficient_context"])
            self.assertFalse(review["unresolved_severe_findings"])
            self.assertFalse(review["mandatory_failure"])
            self.assertEqual(review["verdict"], "PASS")

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _init_project(project)
            task_id = "T-V1"
            batch_id = "B-V1"
            plan = _read_example("v1-planning-bundle.json")
            plan["master_plan"]["revision"] = 1
            plan_path = project / "planning.json"
            _write_json(plan_path, plan)
            plan_hash = hashlib.sha256(
                json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            _write_json(
                project / ".agent/approvals/MASTER_PLAN-MP-V1.json",
                _build_master_plan_approval(plan_hash),
            )
            task = plan["tasks"][0]
            task_rubric = resolve_rubric(project, task_type="backend", review_type="task")
            task_contract = contract_from_rubric(task_rubric)
            self.assertEqual(task_contract, task["review_contract"])
            _write_json(
                project / ".agent/work" / task_id / "task-state.json",
                _build_task_state(task_id, batch_id, "READY", task_contract),
            )
            _write_json(
                project / ".agent/work" / task_id / "lease.json",
                {
                    "task_id": task_id,
                    "owner": "agent-executor",
                    "run_id": "RUN-V1",
                    "attempt_id": "ATTEMPT-V1",
                    "dispatch_id": "DSP-V1",
                    "task_revision": 1,
                    "owner_identity": "agent-executor:RUN-V1",
                    "acquired_at": "2026-08-04T00:00:00Z",
                    "last_heartbeat": "2026-08-04T00:00:00Z",
                    "lease_seconds": 3600,
                    "expires_at": "2099-01-01T00:00:00Z",
                },
            )
            _write_json(
                project / ".agent/runtime/queue.json",
                {
                    "schema_version": 1,
                    "queue_id": "RUNTIME-QUEUE",
                    "revision": 0,
                    "tasks": [],
                    "task_states": [],
                    "dispatches": [
                        {
                            "task_id": task_id,
                            "run_id": "RUN-V1",
                            "attempt_id": "ATTEMPT-V1",
                            "dispatch_id": "DSP-V1",
                        }
                    ],
                    "locks": [],
                },
            )
            code, output = _run_command(
                [
                    sys.executable,
                    str(scripts / "create_batch_contract.py"),
                    "--project-root",
                    str(project),
                    "--plan",
                    str(plan_path),
                    "--plan-id",
                    "MP-V1",
                    "--plan-revision",
                    "1",
                    "--batch-id",
                    batch_id,
                    "--expected-revision",
                    "0",
                    "--actor",
                    "primary-agent",
                ],
                cwd=project,
            )
            self.assertEqual(code, 0, output)
            batch_contract = _read_project_json(
                project,
                f".agent/work/{batch_id}/batch-contract.json",
            )

            _write_json(
                project / ".agent/work" / task_id / "task-state.json",
                _build_task_state(
                    task_id,
                    batch_id,
                    "COMPLETED",
                    task_contract,
                    include_runtime_identity=True,
                ),
            )
            task_review = {
                "review_id": "REV-NONLEGACY-T-V1",
                "task_id": task_id,
                "run_id": "RUN-V1",
                "attempt_id": "ATTEMPT-V1",
                "dispatch_id": "DSP-V1",
                "resolved_rubric": task_rubric,
                "criteria": passing_criteria(task_rubric),
                "hard_fail_checks": [
                    {"rule": rule, "triggered": False, "evidence": "rule checked"}
                    for rule in task_rubric["hard_fail_rules"]
                ],
                "findings": [],
            }
            code, output = _project_cli("create_review.py", project, task_review, "--actor", "task-reviewer")
            self.assertEqual(code, 0, output)
            persisted_task_review = _read_project_json(
                project,
                f".agent/work/{task_id}/review.json",
            )
            self.assertEqual(persisted_task_review["review_contract"], task_contract)
            assert_passing_score(persisted_task_review, task_rubric)

            code, output = _run_command(
                [
                    sys.executable,
                    str(scripts / "create_batch_contract.py"),
                    "--project-root",
                    str(project),
                    "--plan",
                    str(plan_path),
                    "--plan-id",
                    "MP-V1",
                    "--plan-revision",
                    "1",
                    "--batch-id",
                    batch_id,
                    "--expected-revision",
                    "1",
                    "--actor",
                    "primary-agent",
                ],
                cwd=project,
            )
            self.assertEqual(code, 0, output)
            batch_contract = _read_project_json(
                project,
                f".agent/work/{batch_id}/batch-contract.json",
            )

            batch_rubric = resolve_rubric(project, task_type="standard", review_type="batch")
            batch_review = {
                "batch_id": batch_id,
                "task_reviews": [persisted_task_review["review_id"]],
                "integration_checks": [
                    {"kind": kind, "name": f"{kind} check", "result": "PASS", "evidence": "check passed"}
                    for kind in ("integration", "regression", "scope")
                ],
                "findings": [],
                "scope_valid": True,
                "resolved_rubric": batch_rubric,
                "criteria": passing_criteria(batch_rubric),
                "hard_fail_checks": [
                    {"rule": rule, "triggered": False, "evidence": "rule checked"}
                    for rule in batch_rubric["hard_fail_rules"]
                ],
            }
            code, output = _project_cli("create_batch_review.py", project, batch_review, "--actor", "batch-reviewer")
            self.assertEqual(code, 0, output)
            persisted_batch_review = _read_project_json(
                project,
                f".agent/work/{batch_id}/review.json",
            )
            self.assertEqual(persisted_batch_review["review_contract"], batch_contract["review_contract"])
            self.assertEqual(persisted_batch_review["batch_contract_revision"], batch_contract["revision"])
            self.assertEqual(persisted_batch_review["batch_contract_hash"], batch_contract["contract_hash"])
            score_input = project / "batch-review-score-input.json"
            _write_json(score_input, batch_review)
            code, score_output = _run_command(
                [
                    sys.executable,
                    str(scripts / "calculate_rubric_score.py"),
                    "--input",
                    str(score_input),
                ],
                cwd=project,
            )
            self.assertEqual(code, 0, score_output)
            assert_passing_score(json.loads(score_output), batch_rubric)

    def test_every_policy_document_has_one_status_and_enforced_claims_are_backed(self) -> None:
        errors: list[str] = []
        for path in POLICY_DOCUMENTS:
            self.assertTrue(path.is_file(), f"missing policy document: {path}")
            errors.extend(policy_errors(path, path.read_text(encoding="utf-8")))
        self.assertEqual(errors, [])

    def test_documented_feature_without_command_or_schema_is_rejected(self) -> None:
        planning_text = (
            ROOT / "skills/agentic-engineering-wiki/refs/contracts/planning.md"
        ).read_text(encoding="utf-8")
        planning_feature_lines = [line for line in planning_text.splitlines() if line.lstrip().startswith("- Feature:")]
        self.assertTrue(planning_feature_lines)
        self.assertEqual(policy_errors(Path("planning.md"), planning_text), [])
        errors = policy_errors(
            Path("synthetic.md"),
            "Policy status: DECLARATIVE_ONLY\n- Feature: orphaned capability\n",
        )
        self.assertIn("documented feature has no command or schema", "\n".join(errors))

    def test_documented_feature_reference_must_exist(self) -> None:
        errors = policy_errors(
            Path("synthetic.md"),
            "Policy status: DECLARATIVE_ONLY\n"
            "- Feature: missing command=`skills/agentic-state-tools/scripts/does_not_exist.py`\n",
        )
        self.assertIn("references missing command path", "\n".join(errors))

    def test_checklist_is_explicitly_documentation_only_and_unknown_files_are_not_skipped(self) -> None:
        checklist = ROOT / "skills/agentic-state-tools/examples/checklist.md"
        self.assertEqual(validate_examples.EXAMPLE_CLASSIFICATIONS.get("checklist.md"), "DOCUMENTATION_ONLY")
        self.assertIn("Example classification: DOCUMENTATION_ONLY", checklist.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as directory:
            examples_root = Path(directory)
            (examples_root / "checklist.md").write_text(checklist.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(
                validate_all_examples(
                    examples_root,
                    deployment_path=ROOT / "skills/agentic-configuration/config/deployment.test.json",
                ),
                [],
            )
            (examples_root / "unclassified.md").write_text("unclassified\n", encoding="utf-8")
            errors = validate_all_examples(
                examples_root,
                deployment_path=ROOT / "skills/agentic-configuration/config/deployment.test.json",
            )
        self.assertIn("no example classification is registered", "\n".join(errors))

    def test_wrong_handoff_negative_changes_run_and_attempt_identity(self) -> None:
        payload = validate_examples._wrong_run_attempt_handoff_payload()
        self.assertEqual(payload["run_id"], "RUN-WRONG")
        self.assertEqual(payload["attempt_id"], "ATTEMPT-WRONG")
        planning = _read_example("v1-planning-bundle.json")
        outcome = _negative_outcome("wrong-run-attempt-handoff", planning)
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome[0], "REJECT")


if __name__ == "__main__":
    unittest.main()
