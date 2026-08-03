from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
sys.path.insert(0, str(SCRIPTS))

from reconcile_queue import reconcile_queue  # noqa: E402

CONFIG_VALUE = json.loads(
    (SKILL_ROOT.parent / "agentic-configuration" / "config" / "agentic-config.yaml").read_text(encoding="utf-8")
)
EXECUTOR_MODEL = CONFIG_VALUE["agents"]["agent-executor"]["model_dispatch"]
REVIEW_MODEL = CONFIG_VALUE["agents"]["agent-review"]["model_dispatch"]


def run_script(name: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
        env=process_env,
    )


def write_json(directory: str, name: str, value: object) -> Path:
    path = Path(directory) / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class OrchestrationHarnessTests(unittest.TestCase):
    def test_queue_graph_and_dispatch_schemas_exist(self) -> None:
        for name in ("queue.schema.json", "graph.schema.json", "dispatch.schema.json"):
            self.assertTrue((SCHEMAS / name).is_file(), name)

    def test_graph_validator_rejects_cycle_and_accepts_dag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dag = write_json(
                directory,
                "dag.json",
                {
                    "graph_id": "G-001",
                    "revision": 1,
                    "nodes": ["A", "B", "C"],
                    "edges": [{"from": "A", "to": "B"}, {"from": "A", "to": "C"}],
                },
            )
            result = run_script("validate_dependency_graph.py", "--input", str(dag))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("DEPENDENCY_GRAPH_VALID", result.stdout)

            cycle = write_json(
                directory,
                "cycle.json",
                {
                    "graph_id": "G-002",
                    "revision": 1,
                    "nodes": ["A", "B"],
                    "edges": [{"from": "A", "to": "B"}, {"from": "B", "to": "A"}],
                },
            )
            result = run_script("validate_dependency_graph.py", "--input", str(cycle))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cycle", result.stderr.lower())

    def test_critical_path_is_deterministic_with_stable_tie_breaking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            graph = write_json(
                directory,
                "graph.json",
                {
                    "graph_id": "G-003",
                    "revision": 1,
                    "nodes": [
                        {"task_id": "A", "duration": 2},
                        {"task_id": "B", "duration": 3},
                        {"task_id": "C", "duration": 3},
                    ],
                    "edges": [{"from": "A", "to": "B"}, {"from": "A", "to": "C"}],
                },
            )
            result = run_script("compute_critical_path.py", "--input", str(graph))
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["critical_path"], ["A", "B"])
            self.assertEqual(output["critical_path_duration"], 5)
            self.assertEqual(output["topological_order"], ["A", "B", "C"])

    def test_runnable_queue_requires_accepted_dependencies_and_reports_reason_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = write_json(
                directory,
                "queue.json",
                {
                    "queue_id": "Q-001",
                    "revision": 1,
                    "tasks": [
                        {"task_id": "DONE", "status": "COMPLETED", "depends_on": [], "execution_mode": "auto", "write_scope": ["src/done.py"]},
                        {"task_id": "CHILD", "status": "READY", "depends_on": ["DONE"], "execution_mode": "auto", "write_scope": ["src/child.py"]},
                        {"task_id": "FREE", "status": "READY", "depends_on": [], "execution_mode": "auto", "write_scope": ["src/free.py"]},
                    ],
                },
            )
            result = run_script("resolve_runnable_tasks.py", "--input", str(queue))
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual([item["task_id"] for item in output["runnable"]], ["FREE"])
            self.assertEqual(output["reasons"]["CHILD"], "DEPENDENCY_NOT_ACCEPTED:DONE")

    def test_mode_forces_sync_for_repairs_conflicts_and_pending_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for name, task, flags in (
                ("repair.json", {"task_id": "R", "status": "REPAIR_REQUIRED", "execution_mode": "auto"}, []),
                ("conflict.json", {"task_id": "C", "status": "READY", "execution_mode": "auto"}, ["--scope-conflict"]),
                ("dependency.json", {"task_id": "D", "status": "READY", "execution_mode": "auto"}, ["--dependencies-pending"]),
            ):
                input_path = write_json(directory, name, task)
                result = run_script("resolve_execution_mode.py", "--input", str(input_path), *flags)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["execution_mode"], "SYNC")

    def test_mode_reads_default_from_central_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_value = json.loads(
                (SKILL_ROOT.parent / "agentic-configuration" / "config" / "agentic-config.yaml").read_text(encoding="utf-8")
            )
            config_value["execution"]["default_mode"] = "sync"
            config = write_json(directory, "agentic-config.json", config_value)
            task = write_json(directory, "task.json", {"task_id": "T-CONFIG-MODE", "status": "READY", "execution_mode": "auto"})
            result = run_script("resolve_execution_mode.py", "--input", str(task), env={"AGENTIC_CONFIG_FILE": str(config)})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["execution_mode"], "SYNC")

    def test_dispatch_boundary_records_without_spawning_or_architecture_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dispatch = write_json(
                directory,
                "dispatch.json",
                {
                    "dispatch_id": "DSP-001",
                    "task_id": "T-001",
                    "agent_role": "agent-executor",
                    "selected_mode": "ASYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 2, "queue": 4},
                    "approval_references": ["APR-001"],
                    "evidence": {"reason": "independent task", "architecture_owner": "primary-agent"},
                },
            )
            result = run_script("dispatch_task.py", "--input", str(dispatch))
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["dispatch_id"], "DSP-001")
            self.assertEqual(output["status"], "RECORDED")

    def test_dispatch_restricts_model_routing_to_configured_policy(self) -> None:
        base = {
            "dispatch_id": "DSP-MODEL",
            "task_id": "T-MODEL",
            "agent_role": "agent-executor",
            "selected_mode": "ASYNC",
            "selected_owner": "primary-agent",
            "input_revisions": {"task": 1},
            "approval_references": ["APR-MODEL"],
            "evidence": {"reason": "model policy", "architecture_owner": "primary-agent"},
        }
        with tempfile.TemporaryDirectory() as directory:
            for index, (model, role) in enumerate(((EXECUTOR_MODEL, "agent-executor"), (REVIEW_MODEL, "agent-review"))):
                dispatch = write_json(directory, f"allowed-{index}.json", {**base, "agent_role": role, "selected_model": model})
                result = run_script("dispatch_task.py", "--input", str(dispatch))
                self.assertEqual(result.returncode, 0, result.stderr)

            for index, model in enumerate(CONFIG_VALUE["model_policy"]["forbidden_models"]):
                dispatch = write_json(directory, f"forbidden-{index}.json", {**base, "selected_model": model})
                result = run_script("dispatch_task.py", "--input", str(dispatch))
                self.assertNotEqual(result.returncode, 0, model)
                self.assertIn("selected_model", result.stderr)

        schema = json.loads((SCHEMAS / "dispatch.schema.json").read_text(encoding="utf-8"))
        self.assertNotIn("enum", schema["properties"]["selected_model"])
        self.assertIn("agentic-configuration", schema["properties"]["selected_model"]["description"])

    def test_dispatch_uses_role_model_from_central_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_value = json.loads(
                (SKILL_ROOT.parent / "agentic-configuration" / "config" / "agentic-config.yaml").read_text(encoding="utf-8")
            )
            config_value["agents"]["agent-executor"]["model_dispatch"] = REVIEW_MODEL
            config = write_json(directory, "agentic-config.json", config_value)
            dispatch = write_json(
                directory,
                "dispatch.json",
                {
                    "dispatch_id": "DSP-CONFIG",
                    "task_id": "T-CONFIG",
                    "agent_role": "agent-executor",
                    "selected_mode": "ASYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1},
                    "approval_references": ["APR-CONFIG"],
                    "evidence": {"reason": "central config", "architecture_owner": "primary-agent"},
                },
            )
            result = run_script(
                "dispatch_task.py",
                "--input",
                str(dispatch),
                env={"AGENTIC_CONFIG_FILE": str(config)},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("agent-executor", result.stderr)

    def test_dispatch_schema_patterns_are_enforced_at_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dispatch = write_json(
                directory,
                "bad-dispatch.json",
                {
                    "dispatch_id": "BAD ID",
                    "task_id": "T-BAD",
                    "agent_role": "agent-executor",
                    "selected_mode": "ASYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1},
                    "approval_references": ["APR-BAD"],
                    "evidence": {"architecture_owner": "primary-agent"},
                },
            )
            result = run_script("dispatch_task.py", "--input", str(dispatch))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("schema", result.stderr.lower())

    def test_queue_reconciliation_reports_task_and_dispatch_contradictions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = write_json(
                directory,
                "queue-state.json",
                {
                    "queue_id": "Q-002",
                    "revision": 2,
                    "tasks": [
                        {"task_id": "T-001", "queue_state": "DISPATCHED", "execution_mode": "ASYNC", "dependency_snapshot": {"depends_on": [], "accepted_task_ids": []}, "scope_snapshot": {"write_scope": ["src/a.py"]}, "owner": "primary-agent", "revision": 2}
                    ],
                    "task_states": [{"task_id": "T-001", "status": "READY", "revision": 3}],
                    "dispatches": [],
                    "locks": [],
                },
            )
            result = run_script("reconcile_queue.py", "--input", str(queue))
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertFalse(output["valid"])
            self.assertIn("TASK_STATE_MISMATCH:T-001", output["contradictions"])
            self.assertIn("MISSING_DISPATCH:T-001", output["contradictions"])

    def test_queue_reconciliation_validates_dispatch_against_central_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = write_json(
                directory,
                "queue-invalid-dispatch.json",
                {
                    "queue_id": "Q-CONFIG",
                    "revision": 1,
                    "tasks": [
                        {
                            "task_id": "T-CONFIG",
                            "queue_state": "DISPATCHED",
                            "execution_mode": "ASYNC",
                            "dependency_snapshot": {"depends_on": [], "accepted_task_ids": []},
                            "scope_snapshot": {"write_scope": ["src/config.py"]},
                            "revision": 1,
                        }
                    ],
                    "task_states": [],
                    "dispatches": [
                        {
                            "dispatch_id": "DSP-CONFIG",
                            "task_id": "T-CONFIG",
                            "agent_role": "agent-review",
                            "selected_mode": "ASYNC",
                            "selected_owner": "primary-agent",
                            "selected_model": EXECUTOR_MODEL,
                            "input_revisions": {"queue": 1},
                            "approval_references": ["APR-CONFIG"],
                            "evidence": {"architecture_owner": "primary-agent"},
                        }
                    ],
                    "locks": [],
                },
            )
            result = run_script("reconcile_queue.py", "--input", str(queue))
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertFalse(output["valid"])
            self.assertTrue(any(item.startswith("INVALID_DISPATCH:T-CONFIG:") for item in output["contradictions"]))

    def test_queue_reconciliation_reports_dispatch_records_missing_task_identity(self) -> None:
        queue = {
            "queue_id": "Q-MALFORMED",
            "revision": 1,
            "tasks": [],
            "task_states": [],
            "dispatches": [{"dispatch_id": "DSP-MALFORMED", "agent_role": "agent-executor"}],
            "locks": [],
        }
        result = reconcile_queue(queue)
        self.assertFalse(result["valid"])
        self.assertTrue(any(item.startswith("INVALID_DISPATCH:") for item in result["contradictions"]))

    def test_queue_reconciliation_reports_malformed_collections(self) -> None:
        result = reconcile_queue({"tasks": "bad", "task_states": [], "dispatches": "bad", "locks": "bad"})
        self.assertFalse(result["valid"])
        self.assertIn("INVALID_QUEUE_COLLECTION:tasks", result["contradictions"])
        self.assertIn("INVALID_QUEUE_COLLECTION:dispatches", result["contradictions"])
        self.assertIn("INVALID_QUEUE_COLLECTION:locks", result["contradictions"])

    def test_queue_reconciliation_validates_supplied_config(self) -> None:
        config = json.loads(
            (SKILL_ROOT.parent / "agentic-configuration" / "config" / "agentic-config.yaml").read_text(encoding="utf-8")
        )
        config["schema_version"] = True
        with self.assertRaises(ValueError):
            reconcile_queue({"tasks": [], "task_states": [], "dispatches": [], "locks": []}, config=config)


if __name__ == "__main__":
    unittest.main()
