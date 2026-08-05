from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "agentic-state-tools" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from validate_no_placeholders import find_placeholders  # noqa: E402
from validate_payload import validate  # noqa: E402
from validate_planning import _validate_executable_task  # noqa: E402
from runtime_utils import read_json  # noqa: E402


def executable_task() -> dict:
    return {
        "task_id": "T-EXEC-1",
        "batch_id": "B-EXEC-1",
        "version": "1.0",
        "title": "Executable task",
        "contract_mode": "executable",
        "objective": "Add the bounded behavior covered by AC-1.",
        "context": "The existing interface is in skills/example.py.",
        "owner": "agent-executor",
        "depends_on": ["T-DEP-1"],
        "execution_mode": "sync",
        "task_type": "backend",
        "requirement_ids": ["REQ-1"],
        "read_scope": ["skills/example.py"],
        "write_scope": ["skills/example.py"],
        "inputs": [],
        "required_outputs": ["updated behavior and evidence"],
        "acceptance_criteria": [
            {"criterion_id": "AC-1", "text": "The bounded behavior passes.", "requirement_ids": ["REQ-1"]}
        ],
        "verification": ["python -m unittest tests/unit/test_example.py"],
        "out_of_scope": ["new dependencies"],
        "risk_flags": {},
        "blocker_policy": {"hard_blockers": ["missing dependency"]},
        "execution_budget": {
            "max_files_changed": 1,
            "max_new_dependencies": 0,
            "allow_schema_change": False,
            "allow_architecture_change": False,
        },
        "architecture_decisions": ["DEC-1"],
        "prerequisite_decisions": ["DEC-1"],
        "exact_paths": ["skills/example.py"],
        "relevant_symbols": ["skills/example.py::run"],
        "allowed_files": ["skills/example.py"],
        "forbidden_files": ["skills/other.py"],
        "dependency_ids": ["T-DEP-1"],
        "implementation_steps": ["Edit skills/example.py::run and preserve its interface."],
        "validation_mode": "TDD",
        "validation_steps": ["python -m unittest tests/unit/test_example.py"],
        "red_required": True,
        "expected_red": {"result": "exit code 1", "failure_signature": "missing bounded behavior"},
        "expected_green": "exit code 0 with AC-1 passing",
        "verification_commands": ["python -m unittest tests/unit/test_example.py"],
        "acceptance_criteria_ids": ["AC-1"],
        "rollback_recovery_note": "Revert the focused file and preserve the prior evidence.",
        "handoff_expectations": ["Return current evidence and the changed-file list."],
        "file_responsibility_map": [
            {
                "path": "skills/example.py",
                "owner": "agent-executor",
                "concern": "bounded behavior",
                "symbols": ["skills/example.py::run"],
            }
        ],
    }


class ExecutablePlanningTests(unittest.TestCase):
    def test_schema_accepts_the_executable_contract_shape(self) -> None:
        schema = read_json(ROOT / "skills/agentic-state-tools/schemas/planning-task.schema.json")
        errors = validate(
            executable_task(),
            schema,
            base_path=(ROOT / "skills/agentic-state-tools/schemas").resolve(),
        )
        self.assertEqual(errors, [])

    def test_valid_executable_task_passes_cross_field_checks(self) -> None:
        errors: list[str] = []
        _validate_executable_task(
            executable_task(),
            [{"decision_id": "DEC-1", "status": "ACCEPTED"}],
            errors,
        )
        self.assertEqual(errors, [])

    def test_placeholder_and_dependency_mismatch_are_rejected(self) -> None:
        task = executable_task()
        task["implementation_steps"] = ["TODO"]
        task["dependency_ids"] = []
        errors: list[str] = []
        _validate_executable_task(task, [{"decision_id": "DEC-1", "status": "ACCEPTED"}], errors)
        self.assertTrue(any("vague placeholder" in error for error in errors))
        self.assertTrue(any("dependency_ids" in error for error in errors))
        self.assertTrue(find_placeholders({"step": "TODO"}))

    def test_risk_requires_a_nonempty_rollback_note(self) -> None:
        task = copy.deepcopy(executable_task())
        task["risk_flags"] = {"security": True}
        task["rollback_recovery_note"] = "   "
        errors: list[str] = []
        _validate_executable_task(task, [{"decision_id": "DEC-1", "status": "ACCEPTED"}], errors)
        self.assertTrue(any("rollback_recovery_note" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
