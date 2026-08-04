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
from resolve_rubric import resolve_rubric  # noqa: E402
from review_contract import contract_from_rubric  # noqa: E402
from validate_payload import validate  # noqa: E402

CONFIG_VALUE = json.loads(
    (SKILL_ROOT.parent / "agentic-configuration" / "config" / "agentic-config.yaml").read_text(encoding="utf-8")
)
DEPLOYMENT_PATH = SKILL_ROOT.parent / "agentic-configuration" / "config" / "deployment.test.json"
DEPLOYMENT_VALUE = json.loads(DEPLOYMENT_PATH.read_text(encoding="utf-8"))
EXECUTOR_MODEL = DEPLOYMENT_VALUE["model_ids"][CONFIG_VALUE["agents"]["agent-executor"]["model_ref"]]
REVIEW_MODEL = DEPLOYMENT_VALUE["model_ids"][CONFIG_VALUE["agents"]["agent-review"]["model_ref"]]
TASK_REVIEW_CONTRACT = contract_from_rubric(resolve_rubric("personal", "backend", {}))


def run_script(name: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env["AGENTIC_DEPLOYMENT_CONFIG"] = str(DEPLOYMENT_PATH)
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
    def test_async_identity_schemas_and_edge_kinds_are_declared(self) -> None:
        execution_policy = json.loads((SCHEMAS / "execution-policy.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            execution_policy["required"],
            ["requested_mode", "resolved_mode", "resolution_reason", "resolved_by", "resolved_at", "isolation_proof"],
        )
        isolation_proof = json.loads((SCHEMAS / "isolation-proof.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(isolation_proof["required"]),
            {"task_id", "run_id", "worktree_path", "branch_name", "base_commit", "plan_revision", "write_scope_hash", "active_conflicts_checked_at", "isolation_status"},
        )
        graph = json.loads((SCHEMAS / "graph.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(graph["$defs"]["edge"]["properties"]["kind"]["enum"]),
            {"DEPENDENCY", "CONCURRENT", "MERGE", "CONFLICT_GROUP", "SHARED_WRITE_GROUP"},
        )

    def test_typed_graph_edges_validate_ids_and_hashes_without_requiring_them_for_legacy_edges(self) -> None:
        graph_schema = json.loads((SCHEMAS / "graph.schema.json").read_text(encoding="utf-8"))
        legacy = {"schema_version": 1, "graph_id": "G-LEGACY", "revision": 1, "nodes": ["A", {"id": "B"}], "edges": [{"from": "A", "to": "B"}]}
        self.assertEqual(validate(legacy, graph_schema), [])
        invalid = {
            "schema_version": 1,
            "graph_id": "G-TYPED",
            "revision": 1,
            "nodes": ["A", "B"],
            "edges": [{"from": "A", "to": "B", "kind": "DEPENDENCY", "edge_id": "bad id", "edge_hash": "not-a-hash"}],
        }
        self.assertTrue(validate(invalid, graph_schema))

    def test_async_dispatch_persists_identity_and_proof_across_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_value = json.loads((SKILL_ROOT.parent / "agentic-configuration/config/agentic-config.yaml").read_text(encoding="utf-8"))
            config_value["execution"]["async_execution_enabled"] = True
            config_value["version_control"]["isolated_worktrees"] = True
            config = write_json(directory, "async-persist-config.json", config_value)
            project = Path(directory) / "project-ASYNC-PERSIST"
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            task = write_json(
                directory,
                "async-persist-task.json",
                {
                    "task_id": "T-ASYNC-PERSIST",
                    "title": "async persist",
                    "status": "READY",
                    "plan_revision": 3,
                    "input_artifact_hashes": {"plan": "a" * 64},
                    "write_scope": ["src/async.py"],
                    "depends_on": ["DEP-ASYNC"],
                    "review_contract": TASK_REVIEW_CONTRACT,
                },
            )
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(task)).returncode, 0)
            state_path = project / ".agent/runtime/state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["task_statuses"]["DEP-ASYNC"] = "ACCEPTED"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            proof = {
                "task_id": "T-ASYNC-PERSIST",
                "run_id": "RUN-ASYNC-PERSIST",
                "worktree_path": "C:/worktrees/t-async-persist",
                "branch_name": "async/t-async-persist",
                "base_commit": "b" * 40,
                "plan_revision": 3,
                "write_scope_hash": "c" * 64,
                "active_conflicts_checked_at": "2026-08-02T12:00:00Z",
                "isolation_status": "VERIFIED",
            }
            dispatch = write_json(
                directory,
                "async-persist-dispatch.json",
                {
                    "dispatch_id": "DSP-ASYNC-PERSIST",
                    "task_id": "T-ASYNC-PERSIST",
                    "agent_role": "agent-executor",
                    "selected_mode": "ASYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1, "queue": 0},
                    "approval_references": [],
                    "evidence": {"reason": "async persistence", "architecture_owner": "primary-agent"},
                    "run_id": proof["run_id"],
                    "attempt_id": "ATTEMPT-ASYNC-PERSIST",
                    "isolation_proof": proof,
                },
            )
            result = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch), env={"AGENTIC_CONFIG_FILE": str(config)})
            self.assertEqual(result.returncode, 0, result.stderr)
            envelope = json.loads(result.stdout)
            runtime = project / ".agent"
            queue = json.loads((runtime / "runtime/queue.json").read_text(encoding="utf-8"))
            graph = json.loads((runtime / "runtime/graph.json").read_text(encoding="utf-8"))
            task_state = json.loads((runtime / "work/T-ASYNC-PERSIST/task-state.json").read_text(encoding="utf-8"))
            lease = json.loads((runtime / "work/T-ASYNC-PERSIST/lease.json").read_text(encoding="utf-8"))
            for artifact in (envelope, queue["dispatches"][0], queue["tasks"][0], queue["task_states"][0], task_state, lease):
                self.assertEqual(artifact["task_id"], proof["task_id"])
                self.assertEqual(artifact["run_id"], proof["run_id"])
                self.assertEqual(artifact["attempt_id"], "ATTEMPT-ASYNC-PERSIST")
                self.assertEqual(artifact["dispatch_id"], "DSP-ASYNC-PERSIST")
                self.assertEqual(artifact["worktree_path"], proof["worktree_path"])
                self.assertEqual(artifact["branch_name"], proof["branch_name"])
                self.assertEqual(artifact["isolation_proof"], proof)
            node = next(item for item in graph["nodes"] if isinstance(item, dict) and item.get("task_id") == proof["task_id"])
            self.assertEqual(node["run_id"], proof["run_id"])
            self.assertEqual(node["worktree_path"], proof["worktree_path"])
            self.assertEqual(node["isolation_proof"], proof)
            edge = next(item for item in graph["edges"] if item.get("to") == proof["task_id"])
            self.assertEqual(edge["kind"], "DEPENDENCY")
            self.assertTrue(edge["edge_id"].startswith("EDGE-"))
            self.assertEqual(len(edge["edge_hash"]), 64)
            self.assertEqual(edge["isolation_proof"], proof)

    def test_async_dispatch_rejects_run_identity_mismatch_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_value = json.loads((SKILL_ROOT.parent / "agentic-configuration/config/agentic-config.yaml").read_text(encoding="utf-8"))
            config_value["execution"]["async_execution_enabled"] = True
            config_value["version_control"]["isolated_worktrees"] = True
            config = write_json(directory, "async-mismatch-config.json", config_value)
            project = self._dispatch_project(directory, "T-ASYNC-MISMATCH")
            proof = {
                "task_id": "T-ASYNC-MISMATCH",
                "run_id": "RUN-CANONICAL",
                "worktree_path": "C:/worktrees/t-async-mismatch",
                "branch_name": "async/t-async-mismatch",
                "base_commit": "b" * 40,
                "plan_revision": 1,
                "write_scope_hash": "c" * 64,
                "active_conflicts_checked_at": "2026-08-02T12:00:00Z",
                "isolation_status": "VERIFIED",
            }
            dispatch = write_json(
                directory,
                "async-mismatch-dispatch.json",
                {
                    "dispatch_id": "DSP-ASYNC-MISMATCH",
                    "task_id": "T-ASYNC-MISMATCH",
                    "agent_role": "agent-executor",
                    "selected_mode": "ASYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1, "queue": 0},
                    "approval_references": [],
                    "evidence": {"reason": "identity mismatch", "architecture_owner": "primary-agent"},
                    "run_id": "RUN-WRONG",
                    "isolation_proof": proof,
                },
            )
            result = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch), env={"AGENTIC_CONFIG_FILE": str(config)})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("run_id", result.stderr)

    def _dispatch_project(self, directory: str, task_id: str) -> Path:
        project = Path(directory) / f"project-{task_id}"
        initialized = run_script("init_runtime.py", "--project-root", str(project))
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        task = write_json(directory, f"{task_id}-task.json", {"task_id": task_id, "title": task_id, "status": "READY", "depends_on": [], "write_scope": [], "review_contract": TASK_REVIEW_CONTRACT})
        updated = run_script("update_task_state.py", "--project-root", str(project), "--input", str(task))
        self.assertEqual(updated.returncode, 0, updated.stderr)
        return project

    def test_dispatch_persists_durable_runtime_state_and_run_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            self.assertEqual(run_script("init_runtime.py", "--project-root", str(project)).returncode, 0)
            task = write_json(directory, "durable-task.json", {"task_id": "T-DURABLE", "title": "Durable", "status": "READY", "write_scope": ["src/durable.py"], "depends_on": [], "review_contract": TASK_REVIEW_CONTRACT})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(project), "--input", str(task)).returncode, 0)
            dispatch = write_json(
                directory,
                "durable-dispatch.json",
                {
                    "dispatch_id": "DSP-DURABLE",
                    "task_id": "T-DURABLE",
                    "agent_role": "agent-executor",
                    "selected_mode": "SYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1, "queue": 0},
                    "approval_references": [],
                    "evidence": {"reason": "durable test", "architecture_owner": "primary-agent"},
                    "idempotency_key": "dispatch-T-DURABLE-r1",
                },
            )
            result = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch))
            self.assertEqual(result.returncode, 0, result.stderr)
            envelope = json.loads(result.stdout)
            self.assertTrue(envelope["run_id"])
            self.assertTrue(envelope["attempt_id"])
            runtime = project / ".agent"
            self.assertTrue((runtime / "runtime/queue.json").is_file())
            self.assertTrue((runtime / "runtime/graph.json").is_file())
            self.assertTrue((runtime / "work/T-DURABLE/lease.json").is_file())
            self.assertTrue((runtime / "work/T-DURABLE/operations.jsonl").is_file())
            queue = json.loads((runtime / "runtime/queue.json").read_text(encoding="utf-8"))
            self.assertEqual(queue["dispatches"][0]["dispatch_id"], "DSP-DURABLE")
            task_state = json.loads((runtime / "work/T-DURABLE/task-state.json").read_text(encoding="utf-8"))
            self.assertEqual(task_state["status"], "QUEUED_SYNC")
            operations = [json.loads(line) for line in (runtime / "work/T-DURABLE/operations.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([operation["phase"] for operation in operations], ["PREPARE", "COMMIT"])
            self.assertEqual(operations[-1]["commit_marker"], operations[-1]["operation_id"])
            events = (runtime / "runtime/events.jsonl").read_text(encoding="utf-8")
            self.assertIn("TASK_QUEUED_SYNC", events)

    def test_async_dispatch_requires_manager_validated_isolation_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_value = json.loads((SKILL_ROOT.parent / "agentic-configuration/config/agentic-config.yaml").read_text(encoding="utf-8"))
            config_value["execution"]["async_execution_enabled"] = True
            config_value["version_control"]["isolated_worktrees"] = True
            config = write_json(directory, "async-config.json", config_value)
            project = self._dispatch_project(directory, "T-ASYNC-PROOF")
            dispatch = write_json(
                directory,
                "async-dispatch.json",
                {
                    "dispatch_id": "DSP-ASYNC-PROOF",
                    "task_id": "T-ASYNC-PROOF",
                    "agent_role": "agent-executor",
                    "selected_mode": "ASYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1, "queue": 0},
                    "approval_references": [],
                    "evidence": {"reason": "async proof", "architecture_owner": "primary-agent"},
                },
            )
            result = run_script(
                "dispatch_task.py",
                "--project-root", str(project),
                "--input", str(dispatch),
                env={"AGENTIC_CONFIG_FILE": str(config)},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("isolation", result.stderr.lower())

    def test_dispatch_is_idempotent_for_same_task_revision_and_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._dispatch_project(directory, "T-IDEMPOTENT")
            dispatch = write_json(
                directory,
                "idempotent-dispatch.json",
                {
                    "dispatch_id": "DSP-IDEMPOTENT",
                    "task_id": "T-IDEMPOTENT",
                    "agent_role": "agent-executor",
                    "selected_mode": "SYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1, "queue": 0},
                    "approval_references": [],
                    "evidence": {"reason": "idempotency test", "architecture_owner": "primary-agent"},
                    "idempotency_key": "same-operation",
                },
            )
            first = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch))
            second = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(first.stdout)["run_id"], json.loads(second.stdout)["run_id"])
            queue = json.loads((project / ".agent/runtime/queue.json").read_text(encoding="utf-8"))
            self.assertEqual(len(queue["dispatches"]), 1)

    def test_dispatch_rejects_conflicting_payload_for_reused_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._dispatch_project(directory, "T-IDEMPOTENCY-CONFLICT")
            dispatch = write_json(
                directory,
                "idempotency-conflict.json",
                {
                    "dispatch_id": "DSP-IDEMPOTENCY-CONFLICT",
                    "task_id": "T-IDEMPOTENCY-CONFLICT",
                    "agent_role": "agent-executor",
                    "selected_mode": "SYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1, "queue": 0},
                    "approval_references": [],
                    "evidence": {"reason": "idempotency conflict", "architecture_owner": "primary-agent"},
                    "idempotency_key": "same-idempotency-key",
                },
            )
            first = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch))
            self.assertEqual(first.returncode, 0, first.stderr)
            conflicting = json.loads(dispatch.read_text(encoding="utf-8"))
            conflicting["selected_owner"] = "different-owner"
            conflicting["evidence"]["architecture_owner"] = "different-owner"
            conflicting_path = write_json(directory, "conflicting-dispatch.json", conflicting)
            second = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(conflicting_path))
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("idempotency", second.stderr.lower())

    def test_retry_repairs_a_missing_lease_after_partial_dispatch_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = self._dispatch_project(directory, "T-REPAIR-DISPATCH")
            dispatch = write_json(
                directory,
                "repair-dispatch.json",
                {
                    "dispatch_id": "DSP-REPAIR-DISPATCH",
                    "task_id": "T-REPAIR-DISPATCH",
                    "agent_role": "agent-executor",
                    "selected_mode": "SYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1, "queue": 0},
                    "approval_references": [],
                    "evidence": {"reason": "repair dispatch", "architecture_owner": "primary-agent"},
                    "idempotency_key": "repair-dispatch-once",
                },
            )
            first = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch))
            self.assertEqual(first.returncode, 0, first.stderr)
            lease_path = project / ".agent/work/T-REPAIR-DISPATCH/lease.json"
            lease_path.unlink()
            retry = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch))
            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertTrue(lease_path.is_file())

    def test_dispatch_rejects_parallel_capacity_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_value = json.loads((SKILL_ROOT.parent / "agentic-configuration/config/agentic-config.yaml").read_text(encoding="utf-8"))
            config_value["execution"]["max_parallel_tasks"] = 1
            config = write_json(directory, "capacity-config.json", config_value)
            first_project = self._dispatch_project(directory, "T-CAPACITY-1")
            second_task = write_json(directory, "T-CAPACITY-2-task.json", {"task_id": "T-CAPACITY-2", "title": "T-CAPACITY-2", "status": "READY", "depends_on": [], "write_scope": [], "review_contract": TASK_REVIEW_CONTRACT})
            self.assertEqual(run_script("update_task_state.py", "--project-root", str(first_project), "--input", str(second_task)).returncode, 0)
            first_dispatch = write_json(directory, "capacity-first.json", {"dispatch_id": "DSP-CAP-1", "task_id": "T-CAPACITY-1", "agent_role": "agent-executor", "selected_mode": "SYNC", "selected_owner": "primary-agent", "selected_model": EXECUTOR_MODEL, "input_revisions": {"task": 1, "queue": 0}, "approval_references": [], "evidence": {"architecture_owner": "primary-agent"}})
            second_dispatch = write_json(directory, "capacity-second.json", {"dispatch_id": "DSP-CAP-2", "task_id": "T-CAPACITY-2", "agent_role": "agent-executor", "selected_mode": "SYNC", "selected_owner": "primary-agent", "selected_model": EXECUTOR_MODEL, "input_revisions": {"task": 1, "queue": 1}, "approval_references": [], "evidence": {"architecture_owner": "primary-agent"}})
            first = run_script("dispatch_task.py", "--project-root", str(first_project), "--input", str(first_dispatch), env={"AGENTIC_CONFIG_FILE": str(config)})
            second = run_script("dispatch_task.py", "--project-root", str(first_project), "--input", str(second_dispatch), env={"AGENTIC_CONFIG_FILE": str(config)})
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("max_parallel_tasks", second.stderr)

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
                    "selected_mode": "SYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1, "queue": 0},
                    "approval_references": ["APR-001"],
                    "evidence": {"reason": "independent task", "architecture_owner": "primary-agent"},
                },
            )
            project = self._dispatch_project(directory, "T-001")
            result = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch))
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["dispatch_id"], "DSP-001")
            self.assertEqual(output["status"], "RECORDED")

    def test_dispatch_restricts_model_routing_to_configured_policy(self) -> None:
        base = {
            "dispatch_id": "DSP-MODEL",
            "task_id": "T-MODEL",
            "agent_role": "agent-executor",
            "selected_mode": "SYNC",
            "selected_owner": "primary-agent",
            "input_revisions": {"task": 1},
            "approval_references": ["APR-MODEL"],
            "evidence": {"reason": "model policy", "architecture_owner": "primary-agent"},
        }
        with tempfile.TemporaryDirectory() as directory:
            for index, (model, role) in enumerate(((EXECUTOR_MODEL, "agent-executor"), (REVIEW_MODEL, "agent-review"))):
                task_id = f"T-MODEL-{index}"
                project = self._dispatch_project(directory, task_id)
                dispatch = write_json(directory, f"allowed-{index}.json", {**base, "task_id": task_id, "agent_role": role, "selected_model": model, "input_revisions": {"task": 1, "queue": 0}})
                result = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch))
                self.assertEqual(result.returncode, 0, result.stderr)

            forbidden_models = [
                DEPLOYMENT_VALUE["model_ids"][ref]
                for ref in CONFIG_VALUE["model_policy"]["forbidden_model_refs"]
            ]
            for index, model in enumerate(forbidden_models):
                task_id = f"T-FORBIDDEN-{index}"
                project = self._dispatch_project(directory, task_id)
                dispatch = write_json(directory, f"forbidden-{index}.json", {**base, "task_id": task_id, "selected_model": model, "input_revisions": {"task": 1, "queue": 0}})
                result = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch))
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
            config_value["agents"]["agent-executor"]["model_ref"] = config_value["agents"]["agent-review"]["model_ref"]
            config = write_json(directory, "agentic-config.json", config_value)
            project = self._dispatch_project(directory, "T-CONFIG")
            dispatch = write_json(
                directory,
                "dispatch.json",
                {
                    "dispatch_id": "DSP-CONFIG",
                    "task_id": "T-CONFIG",
                    "agent_role": "agent-executor",
                    "selected_mode": "SYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1, "queue": 0},
                    "approval_references": ["APR-CONFIG"],
                    "evidence": {"reason": "central config", "architecture_owner": "primary-agent"},
                },
            )
            result = run_script(
                "dispatch_task.py",
                "--project-root", str(project),
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
                    "selected_mode": "SYNC",
                    "selected_owner": "primary-agent",
                    "selected_model": EXECUTOR_MODEL,
                    "input_revisions": {"task": 1, "queue": 0},
                    "approval_references": ["APR-BAD"],
                    "evidence": {"architecture_owner": "primary-agent"},
                },
            )
            project = self._dispatch_project(directory, "T-BAD")
            result = run_script("dispatch_task.py", "--project-root", str(project), "--input", str(dispatch))
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

    def test_queue_reconciliation_rejects_missing_canonical_fields(self) -> None:
        result = reconcile_queue({})
        self.assertFalse(result["valid"])
        self.assertTrue(any(item.startswith("MISSING_QUEUE_FIELD:") for item in result["contradictions"]))

    def test_queue_reconciliation_validates_supplied_config(self) -> None:
        config = json.loads(
            (SKILL_ROOT.parent / "agentic-configuration" / "config" / "agentic-config.yaml").read_text(encoding="utf-8")
        )
        config["schema_version"] = True
        with self.assertRaises(ValueError):
            reconcile_queue({"tasks": [], "task_states": [], "dispatches": [], "locks": []}, config=config)


if __name__ == "__main__":
    unittest.main()
