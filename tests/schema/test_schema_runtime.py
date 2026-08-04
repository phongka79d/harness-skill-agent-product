from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / "agentic-state-tools"
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from validate_payload import validate  # noqa: E402


class RuntimeSchemaValidatorTests(unittest.TestCase):
    def test_validates_local_refs_and_const_values(self) -> None:
        schema_path = SKILL_ROOT / "schemas" / "worktree.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        value = {
            "schema_version": 1,
            "project_root": "C:/project",
            "worktree_root": "C:/worktrees",
            "entries": {
                "TASK-1@1": {
                    "task_id": "TASK-1",
                    "revision": 1,
                    "path": "C:/worktrees/task-1",
                    "branch": "async/task-1/r1",
                    "base_commit": "a" * 40,
                    "status": "ACTIVE",
                    "lease": None,
                    "created_at": "2026-08-03T12:00:00Z",
                    "updated_at": "2026-08-03T12:00:00Z",
                }
            },
        }
        self.assertEqual(validate(value, schema, base_path=schema_path.parent), [])

        invalid_entry = {
            **value,
            "entries": {
                "TASK-1@1": {**value["entries"]["TASK-1@1"], "status": "INVALID"}
            },
        }
        entry_errors = validate(invalid_entry, schema, base_path=schema_path.parent)
        self.assertTrue(any("enum" in error for error in entry_errors), entry_errors)

        invalid = {**value, "schema_version": 2}
        errors = validate(invalid, schema, base_path=schema_path.parent)
        self.assertTrue(any("const" in error for error in errors), errors)

    def test_enforces_one_of_schema_branches(self) -> None:
        schema_path = SKILL_ROOT / "schemas" / "change-request.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        valid = {
            "change_request_id": "CR-1",
            "target_type": "TASK",
            "target_id": "TASK-1",
            "reason": "update scope",
            "requested_changes": [{"op": "replace", "path": "/title", "value": "new"}],
            "status": "PROPOSED",
            "requested_by": "primary-agent",
        }
        self.assertEqual(validate(valid, schema, base_path=schema_path.parent), [])

        invalid = {**valid, "requested_changes": [{"op": "invalid", "path": "/title"}]}
        errors = validate(invalid, schema, base_path=schema_path.parent)
        self.assertTrue(any("oneOf" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
