from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE_SCRIPTS = ROOT / "skills" / "agentic-state-tools" / "scripts"
CONFIG_SCRIPTS = ROOT / "skills" / "agentic-configuration" / "scripts"
sys.path.insert(0, str(STATE_SCRIPTS))
sys.path.insert(0, str(CONFIG_SCRIPTS))

from load_config import load_config  # noqa: E402
from resolve_execution_mode import resolve_execution_mode  # noqa: E402
from validate_payload import validate  # noqa: E402


class ExecutionModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.now = datetime(2026, 8, 5, tzinfo=timezone.utc)

    def parallel_task(self, **overrides: object) -> dict[str, object]:
        task: dict[str, object] = {
            "task_id": "EXP-1",
            "status": "READY",
            "owner": "agent-explorer",
            "task_type": "exploration",
            "execution_policy": {"requested_mode": "PARALLEL_READ_ONLY"},
            "exploration_question": "Which existing routing pattern should this task reuse?",
            "independent_question": True,
            "read_scope": ["skills/agentic-engineering-core"],
            "write_scope": [],
            "write_forbidden": True,
            "context_capacity_available": True,
            "token_capacity_available": True,
            "deterministic_reconciliation": True,
            "reconciliation_strategy": "reconcile facts, inferences, and unknowns by task id",
            "reconciliation_contract": {
                "order": ["task_id", "path", "symbol"],
                "preserve_source_locations": True,
                "block_on_conflict": True,
                "block_on_material_unknown": True,
            },
        }
        task.update(overrides)
        return task

    def resolve(self, task: dict[str, object], *, config: dict[str, object] | None = None, active_tasks: list[dict[str, object]] | None = None) -> dict[str, object]:
        return resolve_execution_mode(
            task,
            config=config or self.config,
            active_tasks=active_tasks or [],
            queue={"tasks": active_tasks or [], "available_slots": 2},
            lease=None,
            isolation_proof=None,
            now=self.now,
        )

    def test_parallel_read_only_is_eligible_without_async_or_worktree(self) -> None:
        result = self.resolve(self.parallel_task())
        self.assertEqual(result["resolved_mode"], "PARALLEL_READ_ONLY")
        self.assertEqual(result["resolution_reason"], "PARALLEL_READ_ONLY_ELIGIBLE")
        self.assertFalse(self.config["execution"]["async_execution_enabled"])
        schema = json.loads((ROOT / "skills/agentic-state-tools/schemas/execution-policy.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(result, schema), [])

    def test_parallel_read_only_requires_explicit_exploration_contract(self) -> None:
        for field in ("exploration_question", "independent_question", "read_scope", "write_forbidden", "context_capacity_available", "token_capacity_available", "reconciliation_strategy", "reconciliation_contract"):
            with self.subTest(field=field):
                task = self.parallel_task()
                if field == "exploration_question":
                    task.pop(field)
                elif field == "reconciliation_strategy":
                    task[field] = ""
                elif field == "independent_question":
                    task[field] = False
                elif field == "read_scope":
                    task[field] = []
                elif field == "reconciliation_contract":
                    task[field] = {"order": ["task_id"]}
                else:
                    task[field] = False
                result = self.resolve(task)
                self.assertEqual(result["resolved_mode"], "BLOCKED")

    def test_parallel_read_only_rejects_duplicate_active_question(self) -> None:
        active = [self.parallel_task(task_id="EXP-1")]
        result = self.resolve(self.parallel_task(task_id="EXP-2"), active_tasks=active)
        self.assertEqual(result["resolved_mode"], "BLOCKED")
        self.assertEqual(result["resolution_reason"], "EXPLORATION_QUESTION_NOT_INDEPENDENT")

    def test_parallel_read_only_reconciles_active_capacity_from_queue(self) -> None:
        active = []
        queue_tasks = [
            self.parallel_task(task_id="EXP-1", exploration_question="Inspect routing"),
            self.parallel_task(task_id="EXP-2", exploration_question="Inspect validation"),
        ]
        task = self.parallel_task(task_id="EXP-3", exploration_question="Inspect examples")
        result = resolve_execution_mode(
            task,
            config=self.config,
            active_tasks=active,
            queue={"tasks": [{**item, "status": "RUNNING"} for item in queue_tasks], "available_slots": 2},
            lease=None,
            isolation_proof=None,
            now=self.now,
        )
        self.assertEqual(result["resolved_mode"], "BLOCKED")
        self.assertEqual(result["resolution_reason"], "PARALLEL_READ_ONLY_CAPACITY_EXCEEDED")

    def test_parallel_read_only_capacity_is_separate_from_async_capacity(self) -> None:
        active = [
            self.parallel_task(task_id="EXP-1", exploration_question="Inspect routing"),
            self.parallel_task(task_id="EXP-2", exploration_question="Inspect validation"),
        ]
        result = self.resolve(self.parallel_task(task_id="EXP-3"), active_tasks=active)
        self.assertEqual(result["resolved_mode"], "BLOCKED")
        self.assertEqual(result["resolution_reason"], "PARALLEL_READ_ONLY_CAPACITY_EXCEEDED")

        disabled_async = copy.deepcopy(self.config)
        disabled_async["async_execution"]["capability_enabled"] = False
        result = self.resolve(self.parallel_task(), config=disabled_async)
        self.assertEqual(result["resolved_mode"], "PARALLEL_READ_ONLY")

    def test_async_isolated_write_does_not_fallback_when_explicitly_required(self) -> None:
        task = {
            "task_id": "WRITE-1",
            "status": "READY",
            "owner": "agent-executor",
            "task_type": "backend",
            "execution_policy": {"requested_mode": "ASYNC_ISOLATED_WRITE"},
            "write_scope": ["src/write.py"],
        }
        result = self.resolve(task)
        self.assertEqual(result["resolved_mode"], "BLOCKED")
        self.assertEqual(result["resolution_reason"], "ASYNC_CAPABILITY_DISABLED")

    def test_legacy_aliases_remain_readable_and_new_modes_are_explicit(self) -> None:
        self.assertEqual(resolve_execution_mode({"task_id": "SYNC-1", "execution_mode": "sync"}), "SYNC")
        self.assertEqual(resolve_execution_mode({"task_id": "SYNC-2", "execution_mode": "sync_write"}), "SYNC_WRITE")
        self.assertEqual(resolve_execution_mode(self.parallel_task()), "PARALLEL_READ_ONLY")

    def test_execution_policy_schema_declares_the_three_modes(self) -> None:
        schema = json.loads((ROOT / "skills/agentic-state-tools/schemas/execution-policy.schema.json").read_text(encoding="utf-8"))
        requested = set(schema["properties"]["requested_mode"]["enum"])
        resolved = set(schema["properties"]["resolved_mode"]["enum"])
        self.assertTrue({"SYNC_WRITE", "PARALLEL_READ_ONLY", "ASYNC_ISOLATED_WRITE"}.issubset(requested))
        self.assertTrue({"SYNC_WRITE", "PARALLEL_READ_ONLY", "ASYNC_ISOLATED_WRITE"}.issubset(resolved))


if __name__ == "__main__":
    unittest.main()
