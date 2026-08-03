from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
PYTHON = sys.executable
sys.path.insert(0, str(SCRIPTS))

from distributed_store import FileStateStore  # noqa: E402
from rollback import (  # noqa: E402
    ApprovalRequired,
    FencingConflict,
    RollbackRequestError,
    build_rollback_plan,
    execute_rollback,
)
from validate_payload import validate  # noqa: E402


BASE_TIME = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def operations() -> list[dict[str, object]]:
    return [
        {
            "operation_id": "OP-T-001-1",
            "task_id": "T-001",
            "type": "DELETE",
            "status": "COMPLETED",
            "command": "provider.delete",
        },
        {
            "operation_id": "OP-T-001-2",
            "task_id": "T-001",
            "type": "EXTERNAL_RESOURCE",
            "status": "COMPLETED",
            "command": "provider.revoke",
        },
    ]


def request(*, destructive: bool = False, include_second: bool = False) -> dict[str, object]:
    actions: list[dict[str, object]] = [
        {
            "action_id": "COMP-001",
            "operation_id": "OP-T-001-1",
            "kind": "DESTRUCTIVE" if destructive else "REVERSIBLE",
            "provider": "test-provider",
            "description": "reverse the first operation",
            "depends_on": [],
        }
    ]
    if include_second:
        actions.append(
            {
                "action_id": "COMP-002",
                "operation_id": "OP-T-001-2",
                "kind": "REVERSIBLE",
                "provider": "test-provider",
                "description": "reverse the second operation",
                "depends_on": ["COMP-001"],
            }
        )
    return {
        "plan_id": "RB-T-001-001",
        "task_id": "T-001",
        "rollback_requested": True,
        "requested_by": "primary-agent",
        "reason": "explicit side-effect recovery request",
        "actions": actions,
    }


def approval(plan_id: str = "RB-T-001-001") -> dict[str, object]:
    return {
        "approval_id": f"APR-ROLLBACK-{plan_id}-1",
        "target_type": "ROLLBACK",
        "target_id": plan_id,
        "decision": "APPROVED",
        "approver": "primary-agent",
        "evidence": "explicit compensation approval",
    }


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([PYTHON, str(SCRIPTS / name), *args], text=True, capture_output=True, check=False, timeout=20)


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class RollbackTests(unittest.TestCase):
    def test_rollback_contracts_and_event_types_exist(self) -> None:
        for name in (
            "compensation-action.schema.json",
            "rollback-plan.schema.json",
            "rollback-ledger.schema.json",
            "rollback-evidence.schema.json",
        ):
            self.assertTrue((SCHEMAS / name).is_file(), name)
        state_machine = json.loads((SCHEMAS / "state-machine.json").read_text(encoding="utf-8"))
        for event_name in ("ROLLBACK_PLANNED", "COMPENSATION_RECORDED", "ROLLBACK_ESCALATED"):
            self.assertIn(event_name, state_machine["non_state_events"])

    def test_failed_task_alone_cannot_create_a_rollback_plan(self) -> None:
        with self.assertRaises(RollbackRequestError):
            build_rollback_plan({"task_id": "T-001", "task_status": "FAILED"}, operations(), now=BASE_TIME)

    def test_plan_is_explicit_dry_run_and_links_known_operations(self) -> None:
        plan = build_rollback_plan(request(), operations(), now=BASE_TIME)
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["status"], "DRY_RUN")
        self.assertEqual(plan["operation_ids"], ["OP-T-001-1"])
        self.assertFalse(any("executed" in action for action in plan["actions"]))
        invalid = request()
        invalid["actions"] = [{**invalid["actions"][0], "operation_id": "OP-MISSING"}]
        with self.assertRaises(RollbackRequestError):
            build_rollback_plan(invalid, operations(), now=BASE_TIME)

    def test_destructive_compensation_requires_exact_approval(self) -> None:
        plan = build_rollback_plan(request(destructive=True), operations(), now=BASE_TIME)
        with self.assertRaises(ApprovalRequired):
            execute_rollback(plan, None, {"COMP-001": {"status": "COMPLETED", "evidence": "provider"}}, now=BASE_TIME)
        wrong = approval("RB-WRONG")
        with self.assertRaises(ApprovalRequired):
            execute_rollback(plan, wrong, {"COMP-001": {"status": "COMPLETED", "evidence": "provider"}}, now=BASE_TIME)

    def test_executor_accepts_only_a_dry_run_plan(self) -> None:
        plan = build_rollback_plan(request(), operations(), now=BASE_TIME)
        plan["status"] = "ROLLED_BACK"
        plan["dry_run"] = False
        with self.assertRaises(RollbackRequestError):
            execute_rollback(plan, approval(), {"COMP-001": {"status": "COMPLETED", "evidence": "provider"}}, now=BASE_TIME)

    def test_unknown_after_completed_action_is_partial_and_escalated(self) -> None:
        plan = build_rollback_plan(request(include_second=True), operations(), now=BASE_TIME)
        ledger = execute_rollback(
            plan,
            approval(),
            {
                "COMP-001": {"status": "COMPLETED", "evidence": "provider reversed"},
                "COMP-002": {"status": "UNKNOWN", "evidence": "provider timeout"},
            },
            now=BASE_TIME,
        )
        self.assertEqual(ledger["classification"], "PARTIAL_ROLLBACK")
        self.assertEqual(ledger["status"], "ESCALATED")
        self.assertEqual(ledger["next_action"], "ESCALATE")
        self.assertNotEqual(ledger["entries"][1]["status"], "RETRY")

    def test_stale_fencing_token_blocks_compensation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = FileStateStore(Path(directory))
            old = store.acquire_lock("resource", "external", "machine-a", "RUN-001", 1, now=BASE_TIME)
            replacement = store.acquire_lock(
                "resource",
                "external",
                "machine-b",
                "RUN-002",
                60,
                now=BASE_TIME.replace(second=2),
                reclaim_expired=True,
            )
            self.assertGreater(replacement["fencing_token"], old["fencing_token"])
            plan_request = request()
            plan_request["actions"] = [{
                **plan_request["actions"][0],
                "fencing": {
                    "kind": "resource",
                    "key": "external",
                    "owner_id": "machine-a",
                    "run_id": "RUN-001",
                    "fencing_token": old["fencing_token"],
                },
            }]
            plan = build_rollback_plan(plan_request, operations(), now=BASE_TIME)

            def validate_fencing(action: dict[str, object]) -> None:
                fencing = action["fencing"]
                try:
                    current = store.list_locks()[0]
                    if current["fencing_token"] != fencing["fencing_token"]:
                        raise FencingConflict("stale fencing token")
                except IndexError as exc:
                    raise FencingConflict("fence is missing") from exc

            ledger = execute_rollback(
                plan,
                approval(),
                {"COMP-001": {"status": "COMPLETED", "evidence": "provider"}},
                fencing_validator=validate_fencing,
                now=BASE_TIME,
            )
            self.assertEqual(ledger["status"], "ESCALATED")
            self.assertEqual(ledger["entries"][0]["status"], "STALE_OWNER")

    def test_plan_and_ledger_are_schema_valid(self) -> None:
        plan = build_rollback_plan(request(), operations(), now=BASE_TIME)
        plan_schema = json.loads((SCHEMAS / "rollback-plan.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(plan, plan_schema), [])
        ledger = execute_rollback(plan, approval(), {"COMP-001": {"status": "COMPLETED", "evidence": "provider"}}, now=BASE_TIME)
        ledger_schema = json.loads((SCHEMAS / "rollback-ledger.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(ledger, ledger_schema), [])

    def test_cli_persists_plan_approval_ledger_evidence_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            started = write_json(project / "started.json", {"operation_id": "OP-T-001-1", "task_id": "T-001", "run_id": "RUN-001", "type": "DELETE", "status": "STARTED", "command": "provider.delete"})
            completed = write_json(project / "completed.json", {"operation_id": "OP-T-001-1", "task_id": "T-001", "run_id": "RUN-001", "type": "DELETE", "status": "COMPLETED", "command": "provider.delete"})
            self.assertEqual(run_script("record_operation.py", "--project-root", str(project), "--input", str(started)).returncode, 0)
            self.assertEqual(run_script("record_operation.py", "--project-root", str(project), "--input", str(completed)).returncode, 0)
            plan_input = write_json(project / "rollback-request.json", request(destructive=True))
            planned = run_script("plan_rollback.py", "--project-root", str(project), "--input", str(plan_input))
            self.assertEqual(planned.returncode, 0, planned.stderr)
            plan_path = project / ".agent/recovery/rollback-plan-RB-T-001-001.json"
            self.assertTrue(plan_path.is_file())
            approval_input = write_json(project / "approval.json", {"target_type": "ROLLBACK", "target_id": "RB-T-001-001", "decision": "APPROVED", "approver": "primary-agent", "evidence": "approved rollback"})
            approved = run_script("record_approval.py", "--project-root", str(project), "--input", str(approval_input), "--actor", "primary-agent")
            self.assertEqual(approved.returncode, 0, approved.stderr)
            approval_path = project / ".agent/approvals/ROLLBACK-RB-T-001-001.json"
            outcomes = write_json(project / "outcomes.json", {"COMP-001": {"status": "COMPLETED", "evidence": "provider reversed"}})
            executed = run_script(
                "execute_rollback.py",
                "--project-root",
                str(project),
                "--plan-id",
                "RB-T-001-001",
                "--approval",
                str(approval_path),
                "--outcomes",
                str(outcomes),
            )
            self.assertEqual(executed.returncode, 0, executed.stderr)
            self.assertTrue((project / ".agent/recovery/rollback-ledger-LEDGER-RB-T-001-001.json").is_file())
            self.assertTrue((project / ".agent/recovery/rollback-evidence-EVIDENCE-LEDGER-RB-T-001-001.json").is_file())
            journal = (project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8")
            self.assertIn("ROLLBACK_PLANNED", journal)
            self.assertIn("COMPENSATION_RECORDED", journal)


if __name__ == "__main__":
    unittest.main()
