"""Validate bundled examples through schemas and runtime normalization paths."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from create_batch_contract import _plan_hash, artifact_hash as batch_contract_hash
from create_batch_review import normalize as normalize_batch_review
from create_context import normalize as normalize_context
from dispatch_task import normalize_dispatch
from review_contract import validate_contract
from runtime_transaction import TransactionError, _validate_manifest
from runtime_utils import validate_event
from validate_payload import validate
from validate_planning import validate_manifest
from worktree_manager import validate_canonical_isolation_proof

CONFIG_SKILL = Path(__file__).resolve().parents[2] / "agentic-configuration"
sys.path.insert(0, str(CONFIG_SKILL / "scripts"))
from load_config import load_config, load_deployment_config  # noqa: E402


SCHEMA_MAP = {
    "batch-review.json": "batch-review.schema.json",
    "batch-contract.json": "batch-contract.schema.json",
    "context.json": "context.schema.json",
    "debug-investigation.json": "debug-investigation.schema.json",
    "event.json": "event.schema.json",
    "heartbeat.json": "lease.schema.json",
    "lock.json": "lock.schema.json",
    "operation.json": "operation.schema.json",
    "review.json": "review.schema.json",
    "review-resolution.json": "review-resolution.schema.json",
    "skill-routing.json": "skill-routing.schema.json",
    "task-state.json": "task-state.schema.json",
    "isolation-proof.json": "isolation-proof.schema.json",
    "transaction.json": "transaction.schema.json",
    "verification-evidence.json": "verification-evidence.schema.json",
    "completion-claim.json": "completion-claim.schema.json",
    "v1-dispatch.json": "dispatch.schema.json",
    "v1-recovery.json": "reconciliation.schema.json",
}

EXAMPLE_CLASSIFICATIONS = {
    "checklist.md": "DOCUMENTATION_ONLY",
}


def _official_cli(
    script: str,
    input_value: Any,
    *extra_args: str,
    env: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Run an owning CLI against a temporary payload and return its evidence."""

    script_path = Path(__file__).resolve().parent / script
    with tempfile.TemporaryDirectory() as directory:
        input_path = Path(directory) / "input.json"
        input_path.write_text(json.dumps(input_value, ensure_ascii=False), encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(script_path), *extra_args, "--input", str(input_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return 124, f"{script_path.name}: timed out"
    return result.returncode, (result.stdout + result.stderr).strip()


def _schema_cli_errors(path: Path, schema_path: Path) -> list[str]:
    returncode, output = _official_cli(
        "validate_payload.py",
        _read_json(path),
        "--schema",
        str(schema_path),
    )
    return [] if returncode == 0 else [output or f"validate_payload.py exited {returncode}"]


def _run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        label = Path(str(command[1])).name if len(command) > 1 else str(command[0])
        return 124, f"{label}: timed out"
    return result.returncode, (result.stdout + result.stderr).strip()


def _init_project(project: Path) -> None:
    code, output = _run_command(
        [sys.executable, str(Path(__file__).resolve().parent / "init_runtime.py"), "--project-root", str(project)]
    )
    if code:
        raise ValueError(f"init_runtime.py failed: {output}")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _project_cli(script: str, project: Path, payload: Any, *arguments: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as directory:
        input_path = Path(directory) / "input.json"
        _write_json(input_path, payload)
        return _run_command(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / script),
                *arguments,
                "--project-root",
                str(project),
                "--input",
                str(input_path),
            ]
        )


def _canonical_example(name: str) -> Any:
    return _read_json(Path(__file__).resolve().parents[1] / "examples" / name)


def _independent_batch_review_hash(record: dict[str, Any]) -> str:
    canonical = dict(record)
    canonical.pop("artifact_hash", None)
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _stable_field_errors(
    expected: Any,
    actual: Any,
    *,
    dynamic_fields: set[str] | frozenset[str] = frozenset(),
    path: str = "payload",
) -> list[str]:
    """Return mismatches for provided fields, excluding only explicit dynamic fields."""

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected object, got {type(actual).__name__}"]
        errors: list[str] = []
        for key, expected_value in expected.items():
            field_path = f"{path}.{key}"
            if key in dynamic_fields or field_path in dynamic_fields:
                continue
            if key not in actual:
                errors.append(f"{field_path}: generated field is missing")
                continue
            errors.extend(
                _stable_field_errors(
                    expected_value,
                    actual[key],
                    dynamic_fields=dynamic_fields,
                    path=field_path,
                )
            )
        return errors
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: expected array, got {type(actual).__name__}"]
        errors = []
        if len(expected) != len(actual):
            errors.append(f"{path}: expected {len(expected)} entries, got {len(actual)}")
        for index, expected_value in enumerate(expected[: len(actual)]):
            errors.extend(
                _stable_field_errors(
                    expected_value,
                    actual[index],
                    dynamic_fields=dynamic_fields,
                    path=f"{path}[{index}]",
                )
            )
        return errors
    return [] if expected == actual else [f"{path}: expected {expected!r}, got {actual!r}"]


def _positive_runtime_errors(path: Path, value: Any) -> list[str]:
    """Exercise positive examples through their owning writer CLI when one exists."""

    if path.name == "batch-contract.json":
        return _positive_batch_contract_errors(value)
    if path.name == "batch-review.json":
        return _positive_batch_review_errors(value)
    if path.name == "review.json":
        return _positive_review_errors(value)
    if path.name == "review-resolution.json":
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _init_project(project)
            task_id = str(value["task_id"])
            _write_json(project / ".agent/work" / task_id / "task-state.json", {
                "task_id": task_id,
                "revision": value["task_revision"],
                "status": "REVIEWING",
                "run_id": value["run_id"],
                "attempt_id": value["attempt_id"],
                "dispatch_id": value["artifact_identity"]["dispatch_id"],
            })
            _write_json(project / ".agent/work" / task_id / "review.json", {
                "review_id": value["review_id"],
                "task_id": task_id,
                "artifact_identity": value["artifact_identity"],
                "findings": [value["finding"]],
                "verdict": "REPAIR_REQUIRED",
            })
            code, output = _project_cli("create_review_resolution.py", project, value, "--task-id", task_id)
            if code:
                return [f"create_review_resolution.py: {output or f'exited {code}'}"]
            generated = _read_json(project / ".agent/work" / task_id / "review-resolution.json")
        errors = _stable_field_errors(value, generated, dynamic_fields={"created_at", "updated_at", "actor"})
        return [f"create_review_resolution.py: {error}" for error in errors]
    if path.name == "skill-routing.json":
        code, output = _official_cli("resolve_skill_route.py", value)
        return [] if code == 0 else [f"resolve_skill_route.py: {output or f'exited {code}'}"]
    if path.name == "isolation-proof.json":
        return _positive_isolation_errors(value)
    if path.name == "transaction.json":
        return _positive_transaction_errors(value)
    if path.name == "v1-recovery.json":
        return _positive_recovery_errors(value)
    if path.name == "v1-dispatch.json":
        return _positive_dispatch_errors(value)
    if path.name == "debug-investigation.json":
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _init_project(project)
            task_id = str(value["task_id"])
            _write_json(
                project / ".agent/work" / task_id / "task-state.json",
                {
                    "task_id": task_id,
                    "batch_id": "B-DEBUG-EXAMPLE",
                    "plan_revision": 1,
                    "revision": int(value["task_revision"]) - 1,
                    "status": "REPAIR_REQUIRED",
                    "run_id": value["run_id"],
                    "attempt_id": value["attempt_id"],
                    "dispatch_id": "DISPATCH-DEBUG-EXAMPLE",
                },
            )
            code, output = _project_cli(
                "create_debug_investigation.py",
                project,
                value,
                "--task-id",
                task_id,
                "--actor",
                "validator",
            )
            if code:
                return [f"create_debug_investigation.py: {output or f'exited {code}'}"]
            return _positive_artifact_errors(path.name, value, project)
    if path.name == "verification-evidence.json":
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _init_project(project)
            task_id = str(value["task_id"])
            _write_json(
                project / ".agent/work" / task_id / "task-state.json",
                {
                    "task_id": task_id,
                    "plan_revision": value["plan_revision"],
                    "revision": value["task_revision"],
                    "status": "RUNNING",
                    "run_id": value["run_id"],
                    "attempt_id": value["attempt_id"],
                },
            )
            runtime_value = dict(value)
            runtime_value.pop("workspace_hash", None)
            code, output = _project_cli("record_verification_evidence.py", project, runtime_value)
            if code:
                return [f"record_verification_evidence.py: {output or f'exited {code}'}"]
            generated = _read_json(
                project / ".agent/work" / task_id / "verification" / f"{value['evidence_id']}.json"
            )
            return [
                f"record_verification_evidence.py: {error}"
                for error in _stable_field_errors(
                    value,
                    generated,
                    dynamic_fields={"workspace_hash", "recorded_at", "base_commit"},
                )
            ]
    if path.name == "completion-claim.json":
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _init_project(project)
            task_id = str(value["task_id"])
            _write_json(
                project / ".agent/work" / task_id / "task-state.json",
                {
                    "task_id": task_id,
                    "plan_revision": value["plan_revision"],
                    "revision": value["task_revision"],
                    "status": "RUNNING",
                    "run_id": value["run_id"],
                    "attempt_id": value["attempt_id"],
                },
            )
            evidence = _canonical_example("verification-evidence.json")
            evidence_input = dict(evidence)
            evidence_input.pop("workspace_hash", None)
            evidence_path = Path(directory) / "verification-evidence.json"
            _write_json(evidence_path, evidence_input)
            code, output = _project_cli("record_verification_evidence.py", project, evidence_input)
            if code:
                return [f"record_verification_evidence.py: {output or f'exited {code}'}"]
            generated = _read_json(
                project / ".agent/work" / task_id / "verification" / f"{evidence['evidence_id']}.json"
            )
            claim = dict(value)
            claim["workspace_hash"] = generated["workspace_hash"]
            code, output = _project_cli("verify_completion_claim.py", project, claim)
            if code:
                return [f"verify_completion_claim.py: {output or f'exited {code}'}"]
            return []

    scripts = {
        "task-state.json": "update_task_state.py",
        "context.json": "create_context.py",
        "event.json": "append_event.py",
        "heartbeat.json": "record_heartbeat.py",
        "lock.json": "acquire_lock.py",
        "operation.json": "record_operation.py",
    }
    script = scripts.get(path.name)
    if script is None:
        return []
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        _init_project(project)
        if path.name == "heartbeat.json":
            task_id = str(value.get("task_id"))
            _write_json(
                project / ".agent/work" / task_id / "task-state.json",
                {"task_id": task_id, "revision": 1, "status": "RUNNING", "run_id": value.get("run_id")},
            )
        code, output = _project_cli(script, project, value)
        if code:
            return [f"{script}: {output or f'exited {code}'}"]
        return _positive_artifact_errors(path.name, value, project)


def _positive_artifact_errors(name: str, value: dict[str, Any], project: Path) -> list[str]:
    if name == "context.json":
        generated = _read_json(project / ".agent/work" / value["task"]["task_id"] / "context.json")
        errors = _stable_field_errors(
            value,
            generated,
            dynamic_fields={"context_id", "created_at", "revision"},
        )
        return [f"create_context.py: {error}" for error in errors]
    if name == "event.json":
        lines = (project / ".agent/runtime/events.jsonl").read_text(encoding="utf-8").splitlines()
        generated = json.loads(lines[-1]) if lines else {}
        return [f"append_event.py: {error}" for error in _stable_field_errors(value, generated)]
    if name == "heartbeat.json":
        generated = _read_json(project / ".agent/work" / value["task_id"] / "lease.json")
        errors = _stable_field_errors(
            value,
            generated,
            dynamic_fields={
                "task_revision",
                "acquired_at",
                "last_heartbeat",
                "expires_at",
                "owner_pid",
                "owner_identity",
            },
        )
        return [f"record_heartbeat.py: {error}" for error in errors]
    if name == "lock.json":
        records = [_read_json(path) for path in (project / ".agent/locks").glob("**/*.json")]
        generated = next(
            (
                item
                for item in records
                if item.get("kind") == value.get("kind")
                and item.get("key") == value.get("key")
            ),
            {},
        )
        errors = _stable_field_errors(
            value,
            generated,
            dynamic_fields={"lock_id", "owner_pid", "owner_identity", "acquired_at", "expires_at"},
        )
        return [f"acquire_lock.py: {error}" for error in errors]
    if name == "operation.json":
        path = project / ".agent/work" / value["task_id"] / "operations.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        generated = next((item for item in records if item.get("operation_id") == value.get("operation_id")), {})
        errors = _stable_field_errors(
            value,
            generated,
            dynamic_fields={"recorded_at", "revision", "actor", "phase", "transaction_id", "idempotency_key"},
        )
        return [f"record_operation.py: {error}" for error in errors]
    if name == "task-state.json":
        generated = _read_json(project / ".agent/work" / value["task_id"] / "task-state.json")
        errors = _stable_field_errors(value, generated, dynamic_fields={"revision", "updated_at", "previous_revision"})
        return [f"update_task_state.py: {error}" for error in errors]
    if name == "debug-investigation.json":
        generated = _read_json(project / ".agent/work" / value["task_id"] / "debug-investigation.json")
        errors = _stable_field_errors(
            value,
            generated,
            dynamic_fields={"created_at", "updated_at", "revision", "previous_revision", "workspace_hash"},
        )
        return [f"create_debug_investigation.py: {error}" for error in errors]
    return []


def _positive_batch_review_errors(value: dict[str, Any]) -> list[str]:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        _init_project(project)
        task_id = "SP-01-B01-T01"
        task_review = _canonical_example("review.json")
        _write_json(project / ".agent/work" / task_id / "review.json", task_review)
        _write_json(
            project / ".agent/work" / task_id / "task-state.json",
            {"task_id": task_id, "revision": 4, "status": "ACCEPTED"},
        )
        code, output = _project_cli("create_batch_review.py", project, value)
        if code:
            return [f"create_batch_review.py: {output or f'exited {code}'}"]
        generated = _read_json(project / ".agent/work" / value["batch_id"] / "review.json")
    errors = _stable_field_errors(
        value,
        generated,
        dynamic_fields={"review_id", "revision", "created_at", "reviewer", "artifact_hash", "blocking_reasons"},
    )
    generated_hash = generated.get("artifact_hash")
    if generated_hash != _independent_batch_review_hash(generated):
        errors.append("payload.artifact_hash: persisted artifact hash does not match the generated batch review")
    if "artifact_hash" in value and generated_hash != value.get("artifact_hash"):
        errors.append("payload.artifact_hash: persisted artifact hash does not match the provided example")
    return [f"create_batch_review.py: {error}" for error in errors]


def _positive_review_errors(value: dict[str, Any]) -> list[str]:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        _init_project(project)
        task_id = str(value["task_id"])
        _write_json(
            project / ".agent/work" / task_id / "task-state.json",
            {"task_id": task_id, "revision": 3, "status": "COMPLETED"},
        )
        code, output = _project_cli("create_review.py", project, value)
        if code:
            return [f"create_review.py: {output or f'exited {code}'}"]
        generated = _read_json(project / ".agent/work" / task_id / "review.json")
    errors = _stable_field_errors(
        value,
        generated,
        dynamic_fields={
            "review_id",
            "revision",
            "created_at",
            "reviewer",
            "score_percent",
            "threshold_percent",
            "denominator_weight",
            "insufficient_context",
            "unresolved_severe_findings",
            "mandatory_failure",
        },
    )
    return [f"create_review.py: {error}" for error in errors]


def _positive_isolation_errors(value: dict[str, Any]) -> list[str]:
    task = {
        "task_id": value["task_id"],
        "run_id": value["run_id"],
        "owner": "agent-executor",
        "status": "READY",
        "task_type": "backend",
        "requested_mode": "ASYNC_REQUIRED",
        "merge_independent": True,
        "plan_revision": value["plan_revision"],
        "input_artifact_hashes": {"plan": "a" * 64},
        "worktree_path": value["worktree_path"],
        "branch_name": value["branch_name"],
        "write_scope_hash": value["write_scope_hash"],
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = _read_json(CONFIG_SKILL / "config/agentic-config.yaml")
        config["async_execution"]["capability_enabled"] = True
        config["execution"]["async_execution_enabled"] = True
        config_path = root / "agentic-config.json"
        _write_json(config_path, config)
        task_path = root / "task.json"
        proof_path = root / "isolation-proof.json"
        _write_json(task_path, task)
        _write_json(proof_path, value)
        environment = os.environ.copy()
        environment["AGENTIC_CONFIG_FILE"] = str(config_path)
        code, output = _run_command(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "resolve_execution_mode.py"),
                "--input",
                str(task_path),
                "--isolation-proof",
                str(proof_path),
            ],
            env=environment,
        )
    if code:
        return [f"resolve_execution_mode.py: {output or f'exited {code}'}"]
    try:
        generated = json.loads(output)
    except json.JSONDecodeError as exc:
        return [f"resolve_execution_mode.py returned non-JSON output: {exc}"]
    policy = generated.get("execution_policy", {})
    errors = _stable_field_errors(value, policy.get("isolation_proof"), dynamic_fields=set())
    if policy.get("resolution_reason") != "LEASE_MISSING":
        errors.append(f"payload.resolution_reason: expected 'LEASE_MISSING', got {policy.get('resolution_reason')!r}")
    return [f"resolve_execution_mode.py: {error}" for error in errors]


def _positive_transaction_errors(value: dict[str, Any]) -> list[str]:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        _init_project(project)
        target = project / ".agent" / value["target_files"][0]
        target.parent.mkdir(parents=True, exist_ok=True)
        transaction_bytes = b'{"revision":1}\n'
        target.write_bytes(transaction_bytes)
        staged = project / ".agent" / value["staged_files"][0]["staged_path"]
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(transaction_bytes)
        marker = project / ".agent" / value["commit_marker"]
        _write_json(
            marker,
            {
                "operation_id": value["operation_id"],
                "operation_type": value["operation_type"],
                "idempotency_key": value["idempotency_key"],
                "status": "COMMITTED",
                "committed_at": value["committed_at"],
                "target_hashes": value["evidence"]["target_hashes"],
            },
        )
        manifest = project / ".agent/runtime/transactions" / f"{value['operation_id']}.json"
        _write_json(manifest, value)
        code, output = _run_command(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "inspect_recovery.py"),
                "--project-root",
                str(project),
            ]
        )
        if code:
            return [f"inspect_recovery.py: {output or f'exited {code}'}"]
        try:
            generated = json.loads(output)
        except json.JSONDecodeError as exc:
            return [f"inspect_recovery.py returned non-JSON output: {exc}"]
        transactions = generated.get("transactions", [])
        generated_transaction = next(
            (item for item in transactions if item.get("operation_id") == value["operation_id"]),
            None,
        )
        if not isinstance(generated_transaction, dict):
            return ["inspect_recovery.py: committed transaction identity is missing"]
        expected_transaction = {
            "operation_id": value.get("operation_id"),
            "operation_type": value.get("operation_type"),
            "idempotency_key": value.get("idempotency_key"),
            "status": value.get("status"),
            "target_paths": value.get("target_files"),
            "previous_hashes": value.get("evidence", {}).get("previous_hashes"),
            "target_hashes": value.get("evidence", {}).get("target_hashes"),
            "classification": value.get("evidence", {}).get("classification"),
            "rollback_reason": value.get("rollback_reason"),
        }
        errors = _stable_field_errors(expected_transaction, generated_transaction)
        generated_manifest = _read_json(manifest)
        errors.extend(
            _stable_field_errors(
                value.get("evidence", {}).get("staged_hashes"),
                generated_manifest.get("evidence", {}).get("staged_hashes"),
                path="payload.evidence.staged_hashes",
            )
        )
    return [f"inspect_recovery.py: {error}" for error in errors]


def _positive_recovery_errors(value: dict[str, Any]) -> list[str]:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        _init_project(project)
        workspace_root = project / ".agent"
        (workspace_root / ".gitignore").write_text(
            "runtime/\nwork/\ncheckpoints/\nlocks/\nrecovery/\nlogs/\nchecklist.md\n",
            encoding="utf-8",
        )
        (workspace_root / "tracked.txt").write_text("base\n", encoding="utf-8")

        def require_setup(command: list[str]) -> str:
            code, output = _run_command(command, cwd=workspace_root)
            if code:
                raise ValueError(f"recovery fixture setup failed: {output or f'exited {code}'}")
            return output

        require_setup(["git", "init", "-b", "main"])
        require_setup(["git", "config", "user.email", "fixture@example.test"])
        require_setup(["git", "config", "user.name", "fixture"])
        require_setup(["git", "add", ".gitignore", "tracked.txt"])
        require_setup(["git", "commit", "-m", "fixture"])
        base_commit = require_setup(["git", "rev-parse", "HEAD"])
        (workspace_root / "tracked.txt").write_text("changed\n", encoding="utf-8")
        (workspace_root / "unexpected.py").write_text("unexpected\n", encoding="utf-8")
        task_id = value["task_id"]
        _write_json(
            project / ".agent/work" / task_id / "task-state.json",
            {"task_id": task_id, "revision": 1, "status": "STALE", "run_id": "RUN-RECOVERY"},
        )
        _write_json(
            project / ".agent/work" / task_id / "lease.json",
            {
                "task_id": task_id,
                "owner": "agent-executor",
                "run_id": "RUN-RECOVERY",
                "task_revision": 1,
                "owner_identity": "agent-executor:RUN-RECOVERY",
                "acquired_at": "2026-08-04T00:00:00Z",
                "last_heartbeat": "2026-08-04T00:00:00Z",
                "lease_seconds": 3600,
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )
        _write_json(
            project / ".agent/work" / task_id / "checkpoint.json",
            {
                "checkpoint_id": "CP-T-V1-1",
                "task_id": task_id,
                "run_id": "RUN-RECOVERY",
                "task_revision": 1,
                "created_at": "2026-08-04T00:00:00Z",
                "revision": 1,
                "current_step": "implement",
                "pending_steps": ["review"],
                "resume_safe": True,
                "files_modified": ["tracked.txt"],
                "base_commit": base_commit,
                "workspace_status": "CLEAN",
            },
        )
        code, output = _run_command(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "inspect_recovery.py"),
                "--project-root",
                str(project),
                "--task-id",
                task_id,
            ]
        )
        if code:
            return [f"inspect_recovery.py: {output or f'exited {code}'}"]
        try:
            generated = json.loads(output)
        except json.JSONDecodeError as exc:
            return [f"inspect_recovery.py returned non-JSON output: {exc}"]
    results = generated.get("results", [])
    result = next((item for item in results if item.get("task_id") == value["task_id"]), None)
    if not isinstance(result, dict):
        return ["inspect_recovery.py: recovery task identity is missing"]
    errors = _stable_field_errors(
        {
            "task_id": value.get("task_id"),
            "classification": value.get("classification"),
            "workspace": value.get("workspace"),
        },
        result,
    )
    declared_reasons = value.get("reasons")
    if declared_reasons != ["workspace mismatch is present"]:
        errors.append("payload.reasons: expected the high-level workspace mismatch declaration")
    actual_workspace = result.get("workspace")
    if not isinstance(actual_workspace, dict) or actual_workspace.get("mismatch") is not True:
        errors.append("payload.workspace.mismatch: owning CLI did not report a workspace mismatch")
    actual_reasons = result.get("reasons")
    if (
        not isinstance(actual_reasons, list)
        or not actual_reasons
        or any(
            not isinstance(reason, str) or not reason.strip()
            for reason in actual_reasons
        )
    ):
        errors.append("payload.reasons: owning CLI returned no concrete recovery reasons")
    return [f"inspect_recovery.py: {error}" for error in errors]


def _positive_batch_contract_errors(value: dict[str, Any]) -> list[str]:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        _init_project(project)
        plan = _read_json(Path(__file__).resolve().parents[1] / "examples/v1-planning-bundle.json")
        plan["master_plan"]["revision"] = 1
        task = copy.deepcopy(plan["tasks"][0])
        task_state = {
            "task_id": task["task_id"],
            "batch_id": task["batch_id"],
            "plan_revision": 1,
            "revision": 1,
            "owner": task["owner"],
            "status": "READY",
            "review_contract": task["review_contract"],
        }
        _write_json(project / ".agent/work" / task["task_id"] / "task-state.json", task_state)
        plan_hash = _plan_hash(plan)
        _write_json(
            project / ".agent/approvals/MASTER_PLAN-MP-V1.json",
            {
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
                "evidence": "positive example",
                "created_at": "2026-08-04T00:00:00Z",
                "revision": 1,
            },
        )
        with tempfile.TemporaryDirectory() as inputs:
            plan_path = Path(inputs) / "planning.json"
            _write_json(plan_path, plan)
            code, output = _run_command(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parent / "create_batch_contract.py"),
                    "--project-root",
                    str(project),
                    "--plan",
                    str(plan_path),
                    "--plan-id",
                    "MP-V1",
                    "--plan-revision",
                    "1",
                    "--batch-id",
                    "B-V1",
                    "--expected-revision",
                    "0",
                    "--actor",
                    "primary-agent",
                ]
            )
            if code:
                return [f"create_batch_contract.py: {output or f'exited {code}'}"]
            generated = _read_json(project / ".agent/work/B-V1/batch-contract.json")
            stable_fields = (
                "schema_version",
                "contract_id",
                "plan_id",
                "plan_revision",
                "plan_hash",
                "plan_approval_id",
                "batch_id",
                "batch_revision",
                "tasks",
                "review_contract",
                "rubric_id",
                "rubric_version",
                "rubric_hash",
                "revision",
                "previous_revision",
            )
            errors = [
                f"create_batch_contract.py: generated {field} does not match the provided example"
                for field in stable_fields
                if generated.get(field) != value.get(field)
            ]
            normalized_generated = dict(generated)
            normalized_generated["created_at"] = value.get("created_at")
            if batch_contract_hash(normalized_generated, "contract_hash") != value.get("contract_hash"):
                errors.append(
                    "create_batch_contract.py: generated contract hash does not match the provided example "
                    "after normalizing generated created_at"
                )
            return errors


def _positive_dispatch_errors(value: dict[str, Any]) -> list[str]:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        _init_project(project)
        task = _read_json(Path(__file__).resolve().parents[1] / "examples/v1-planning-bundle.json")["tasks"][0]
        _write_json(
            project / ".agent/work" / task["task_id"] / "task-state.json",
            {
                "task_id": task["task_id"],
                "batch_id": task["batch_id"],
                "revision": 0,
                "owner": task["owner"],
                "status": "READY",
                "review_contract": task["review_contract"],
            },
        )
        payload = copy.deepcopy(value)
        payload["input_revisions"] = {"queue": 0, "task": 0}
        with tempfile.TemporaryDirectory() as inputs:
            input_path = Path(inputs) / "dispatch.json"
            _write_json(input_path, payload)
            code, output = _run_command(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parent / "dispatch_task.py"),
                    "--project-root",
                    str(project),
                    "--input",
                    str(input_path),
                    "--deployment",
                    str(CONFIG_SKILL / "config/deployment.test.json"),
                ]
            )
    if code:
        return [f"dispatch_task.py: {output or f'exited {code}'}"]
    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        return [f"dispatch_task.py returned non-JSON output: {exc}"]
    actual = "PASS" if result.get("status") == "RECORDED" else result.get("status")
    expected = value.get("expected_result")
    return [] if actual == expected else [f"dispatch_task.py: expected_result={expected!r}, actual={actual!r}"]


def _validate_special_runtime(path: Path, value: Any) -> list[str]:
    errors: list[str] = []
    try:
        if path.name == "task-state.json":
            if not isinstance(value.get("owner"), str) or not value["owner"].strip():
                raise ValueError("task state requires an owner")
        elif path.name == "batch-contract.json":
            if value.get("contract_hash") != batch_contract_hash(value, "contract_hash"):
                raise ValueError("batch contract hash does not match content")
            validate_contract(value.get("review_contract"), review_type="batch")
        elif path.name == "isolation-proof.json":
            if not validate_canonical_isolation_proof(
                {
                    key: value.get(key)
                    for key in (
                        "task_id",
                        "run_id",
                        "worktree_path",
                        "branch_name",
                        "plan_revision",
                        "write_scope_hash",
                    )
                },
                value,
            ):
                raise ValueError("isolation proof is not bound to the task")
        elif path.name == "transaction.json":
            _validate_manifest(value)
        elif path.name == "v1-planning-bundle.json":
            return _validate_planning_and_negatives(value)
    except (KeyError, TypeError, ValueError, TransactionError) as exc:
        errors.append(str(exc))
    return errors


def _validate_planning_and_negatives(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        input_path = Path(directory) / "planning.json"
        input_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        code, output = _run_command(
            [sys.executable, str(Path(__file__).resolve().parent / "validate_planning.py"), "--input", str(input_path)]
        )
        if code:
            errors.append(output or f"validate_planning.py exited {code}")
    declared = value.get("negative_examples", [])
    if not isinstance(declared, list):
        return errors + ["negative_examples must be an array"]
    expected_names = {
        "missing-owner",
        "stale-batch-contract",
        "wrong-run-attempt-handoff",
        "async-without-isolation-proof",
        "merge-without-approval",
        "interrupted-transaction",
        "invalid-change-operation",
        "secret-bearing-context",
    }
    expected_validators = {
        "missing-owner": "validate_planning.py",
        "stale-batch-contract": "commit_batch.py",
        "wrong-run-attempt-handoff": "create_handoff.py",
        "async-without-isolation-proof": "resolve_execution_mode.py",
        "merge-without-approval": "merge_worktree.py",
        "interrupted-transaction": "inspect_recovery.py",
        "invalid-change-operation": "validate_change_request.py",
        "secret-bearing-context": "create_context.py",
    }
    actual_names = {item.get("name") for item in declared if isinstance(item, dict)}
    if (
        len(declared) != len(expected_names)
        or len(actual_names) != len(expected_names)
        or actual_names != expected_names
    ):
        errors.append(f"negative example set mismatch: expected {sorted(expected_names)}, got {sorted(actual_names)}")
    for item in declared:
        if not isinstance(item, dict):
            errors.append("negative example must be an object")
            continue
        if item.get("expected") not in {"REJECT", "BLOCKED", "RECOVERY_PENDING"}:
            errors.append(f"{item.get('name')}: unsupported declared result")
            continue
        expected_validator = expected_validators.get(str(item.get("name")))
        if item.get("validator") != expected_validator:
            errors.append(
                f"{item.get('name')}: declared validator "
                f"{item.get('validator')!r} does not match {expected_validator!r}"
            )
            continue
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{item.get('name')}: reason must be a non-empty string")
            continue
        outcome = _negative_outcome(str(item.get("name")), value)
        if (
            outcome is None
            or outcome[0] != item["expected"]
            or not _negative_reason_matches(
                str(item.get("name")), reason, outcome[1]
            )
        ):
            errors.append(f"{item.get('name')}: expected {item.get('expected')} matching {reason!r}, got {outcome}")
    return errors


def _negative_reason_matches(name: str, reason: str, output: str) -> bool:
    if name == "async-without-isolation-proof":
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            return False
        return (
            reason == "ISOLATION_PROOF_MISSING"
            and result.get("execution_mode") == "BLOCKED"
            and result.get("execution_policy", {}).get("resolution_reason") == reason
        )
    if name == "interrupted-transaction":
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            return False
        return (
            reason == "RECOVERY_PENDING"
            and any(item.get("classification") == reason for item in result.get("transactions", []))
        )
    text_reason_map = {
        "missing-owner": ("PLANNING_INVALID", "task T-V1 requires an owner"),
        "stale-batch-contract": (
            "COMMIT_REJECTED",
            "batch review batch contract pin does not match the current contract",
        ),
        "wrong-run-attempt-handoff": ("HANDOFF_REJECTED", "handoff.run_id does not match the current task state"),
        "merge-without-approval": ("MERGE_FAILED", "required approval artifact is missing or unreadable"),
        "invalid-change-operation": (
            "CHANGE_REQUEST_INVALID",
            "requested_changes[0].op must be add, replace, remove, move, copy, or test",
        ),
        "secret-bearing-context": (
            "CONTEXT_REJECTED",
            "secret scan rejected sensitive value: "
            "$.code_context.file_contents.config.py:token_assignment",
        ),
    }
    expected = text_reason_map.get(name)
    if expected is None:
        return False
    code, message = expected
    return reason == message and f"{code}: {message}" in " ".join(output.split())


def _wrong_run_attempt_handoff_payload(
    *, run_id: str = "RUN-WRONG", attempt_id: str = "ATTEMPT-WRONG"
) -> dict[str, Any]:
    return {
        "handoff_id": "HANDOFF-T-V1-NEGATIVE",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "dispatch_id": "DSP-V1",
        "from_role": "executor",
        "to_role": "task-reviewer",
        "task_revision": 1,
        "plan_revision": 1,
        "input_artifact_hashes": {"task": "a" * 64},
        "output_artifact_hashes": {"result": "b" * 64},
        "evidence": {"reason": "negative example"},
        "created_at": "2026-08-04T00:00:00Z",
        "revision": 1,
        "status": "COMPLETE",
        "summary": "negative example",
        "files_read": [],
        "files_changed": [],
        "findings": [],
        "implementation_details": [],
        "validation_results": [],
        "risks": [],
        "next_steps": [],
    }


def _negative_outcome(name: str, planning: dict[str, Any]) -> tuple[str, str] | None:
    if name == "missing-owner":
        payload = copy.deepcopy(planning)
        payload["tasks"][0].pop("owner", None)
        code, output = _official_cli("validate_planning.py", payload)
        return ("REJECT", output) if code else None
    if name == "invalid-change-operation":
        payload = {
            "change_request_id": "CR-INVALID",
            "target_type": "TASK",
            "target_id": "T-V1",
            "target_version": "1.0",
            "new_version": "1.1",
            "reason": "negative example",
            "requested_changes": [{"op": "explode", "path": "/title", "value": "x"}],
            "status": "PROPOSED",
            "requested_by": "primary-agent",
            "impact": {},
            "supersedes_id": "T-V1@1.0",
        }
        code, output = _official_cli("validate_change_request.py", payload)
        return ("REJECT", output) if code else None
    if name == "async-without-isolation-proof":
        payload = {
            "task_id": "T-V1",
            "owner": "agent-executor",
            "status": "READY",
            "task_type": "backend",
            "requested_mode": "ASYNC_REQUIRED",
            "merge_independent": True,
            "run_id": "RUN-V1",
            "attempt_id": "ATTEMPT-V1",
            "plan_revision": 1,
            "input_artifact_hashes": {"plan": "a" * 64},
            "lease": {"expires_at": "2099-01-01T00:00:00Z"},
        }
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "agentic-config.json"
            config = _read_json(CONFIG_SKILL / "config/agentic-config.yaml")
            config["async_execution"]["capability_enabled"] = True
            config["execution"]["async_execution_enabled"] = True
            _write_json(config_path, config)
            environment = os.environ.copy()
            environment["AGENTIC_CONFIG_FILE"] = str(config_path)
            code, output = _official_cli("resolve_execution_mode.py", payload, env=environment)
        if code:
            return None
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            return None
        if (
            result.get("execution_mode") == "BLOCKED"
            and result.get("execution_policy", {}).get("resolution_reason")
            == "ISOLATION_PROOF_MISSING"
        ):
            return "BLOCKED", output
        return None
    if name == "stale-batch-contract":
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _init_project(project)
            batch_id = "B-V1"
            contract = _read_json(Path(__file__).resolve().parents[1] / "examples/batch-contract.json")
            task_contract = planning["tasks"][0]["review_contract"]
            contract["tasks"][0]["review_contract_hash"] = hashlib.sha256(
                json.dumps(task_contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            contract["tasks"][0]["rubric_id"] = task_contract["rubric_id"]
            contract["tasks"][0]["rubric_version"] = task_contract["rubric_version"]
            contract["tasks"][0]["rubric_hash"] = task_contract["rubric_hash"]
            contract["plan_approval_id"] = "APR-MP-V1-1"
            contract["contract_hash"] = batch_contract_hash(contract, "contract_hash")
            review = {
                "review_id": "BATCH-REV-B-V1-STALE",
                "batch_id": batch_id,
                "task_reviews": [],
                "integration_checks": [],
                "findings": [],
                "scope_valid": True,
                "verdict": "PASS",
                "batch_contract_revision": 2,
                "batch_contract_hash": "a" * 64,
                "review_contract": contract["review_contract"],
                "revision": 1,
            }
            review["artifact_hash"] = _independent_batch_review_hash(review)
            _write_json(
                project / ".agent/work/T-V1/task-state.json",
                {
                    "task_id": "T-V1",
                    "batch_id": batch_id,
                    "plan_revision": 1,
                    "revision": 1,
                    "owner": "agent-executor",
                    "status": "READY",
                    "review_contract": task_contract,
                },
            )
            _write_json(
                project / ".agent/approvals/MASTER_PLAN-MP-V1.json",
                {
                    "approval_id": "APR-MP-V1-1",
                    "target_type": "MASTER_PLAN",
                    "target_id": "MP-V1",
                    "decision": "APPROVED",
                    "approver": "primary-agent",
                    "actor_type": "primary_agent",
                    "actor_id": "primary-agent",
                    "action": "MASTER_PLAN",
                    "target_revision": 1,
                    "target_hash": contract["plan_hash"],
                    "policy_version": "1",
                    "issued_at": "2026-08-04T00:00:00Z",
                    "expires_at": "2099-01-01T00:00:00Z",
                    "evidence": "negative example",
                    "created_at": "2026-08-04T00:00:00Z",
                    "revision": 1,
                },
            )
            _write_json(project / ".agent/work/B-V1/batch-contract.json", contract)
            _write_json(project / ".agent/work/B-V1/review.json", review)
            _write_json(project / "approval.json", {"target_type": "WORKTREE"})
            (project / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            code, output = _run_command(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parent / "commit_batch.py"),
                    "--project-root",
                    str(project),
                    "--batch-id",
                    batch_id,
                    "--approval",
                    str(project / "approval.json"),
                    "--actor",
                    "user",
                    "--actor-type",
                    "user",
                    "--message",
                    "negative",
                    "--path",
                    "tracked.txt",
                    "--dry-run",
                ]
            )
            return ("REJECT", output) if code else None
    if name == "merge-without-approval":
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            project = sandbox / "project"
            project.mkdir()
            worktree_root = sandbox / "external-worktrees"
            entry: dict[str, Any] | None = None
            fixture_setup_error: str | None = None
            fixture_cleanup_error: str | None = None
            outcome: tuple[str, str] | None = None

            def require_setup(command: list[str]) -> str:
                code, output = _run_command(command, cwd=project)
                if code:
                    label = " ".join(str(part) for part in command[:2])
                    raise ValueError(f"{label}: {output or f'exited {code}'}")
                return output

            try:
                (project / "README.md").write_text("fixture\n", encoding="utf-8")
                require_setup(["git", "init", "-b", "main"])
                require_setup(["git", "config", "user.email", "fixture@example.test"])
                require_setup(["git", "config", "user.name", "fixture"])
                require_setup(["git", "add", "README.md"])
                require_setup(["git", "commit", "-m", "fixture"])
                _init_project(project)
                output = require_setup(
                    [
                        sys.executable,
                        str(Path(__file__).resolve().parent / "worktree_manager.py"),
                        "--project-root",
                        str(project),
                        "--worktree-root",
                        str(worktree_root),
                        "--task-id",
                        "T-V1",
                        "--revision",
                        "1",
                    ]
                )
                try:
                    entry = json.loads(output)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"worktree_manager.py returned non-JSON output: {exc}") from exc
                if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                    raise ValueError("worktree_manager.py did not return a worktree path")
                contract = _read_json(Path(__file__).resolve().parents[1] / "examples/batch-contract.json")
                contract["tasks"][0]["task_id"] = "T-V1"
                contract["contract_hash"] = batch_contract_hash(contract, "contract_hash")
                identity = {"run_id": "RUN-V1", "attempt_id": "ATTEMPT-V1", "dispatch_id": "DSP-V1"}
                task = {
                    "task_id": "T-V1",
                    "batch_id": "B-V1",
                    "revision": 1,
                    "status": "RUNNING",
                    "review_verdict": "PASS",
                    "plan_revision": 1,
                    "worktree_path": entry["path"],
                    "branch_name": entry["branch"],
                    "base_commit": entry["base_commit"],
                    **identity,
                }
                queue_entry = {
                    "task_id": "T-V1",
                    **identity,
                    "worktree_path": entry["path"],
                    "branch_name": entry["branch"],
                    "base_commit": entry["base_commit"],
                    "plan_revision": 1,
                }
                dispatch = {
                    "task_id": "T-V1",
                    **identity,
                    "worktree_path": entry["path"],
                    "branch_name": entry["branch"],
                    "base_commit": entry["base_commit"],
                    "plan_revision": 1,
                }
                _write_json(project / ".agent/work/T-V1/task-state.json", task)
                _write_json(
                    project / ".agent/runtime/queue.json",
                    {"tasks": [queue_entry], "dispatches": [dispatch], "revision": 0},
                )
                _write_json(project / ".agent/work/T-V1/review.json", {"verdict": "PASS"})
                _write_json(project / ".agent/work/B-V1/batch-contract.json", contract)
                _write_json(project / "approval.json", {"target_type": "WORKTREE"})
                code, output = _run_command(
                    [
                        sys.executable,
                        str(Path(__file__).resolve().parent / "merge_worktree.py"),
                        "--project-root",
                        str(project),
                        "--worktree-root",
                        str(worktree_root),
                        "--task-id",
                        "T-V1",
                        "--revision",
                        "1",
                        "--target-branch",
                        "main",
                        "--approval",
                        str(project / "approval.json"),
                        "--actor",
                        "user",
                        "--actor-type",
                        "user",
                    ]
                )
                outcome = ("REJECT", output) if code else None
            except (OSError, TypeError, ValueError) as exc:
                fixture_setup_error = f"merge-without-approval fixture setup failed: {exc}"
            finally:
                if entry is not None:
                    try:
                        entry_path = Path(entry["path"]).expanduser().resolve(strict=False)
                        resolved_worktree_root = worktree_root.resolve(strict=False)
                        entry_path.relative_to(resolved_worktree_root)
                        if entry_path == resolved_worktree_root:
                            raise ValueError("worktree path must not equal worktree root")
                    except (KeyError, OSError, TypeError, ValueError) as exc:
                        fixture_cleanup_error = f"merge-without-approval fixture cleanup failed: {exc}"
                    else:
                        code, output = _run_command(
                            ["git", "worktree", "remove", "--force", str(entry_path)],
                            cwd=project,
                        )
                        if code:
                            fixture_cleanup_error = (
                                "merge-without-approval fixture cleanup failed: "
                                f"{output or f'exited {code}'}"
                            )
                if fixture_cleanup_error is None:
                    code, output = _run_command(["git", "worktree", "prune"], cwd=project)
                    if code:
                        fixture_cleanup_error = (
                            "merge-without-approval fixture cleanup failed: "
                            f"{output or f'exited {code}'}"
                        )
                if (
                    fixture_cleanup_error is None
                    and worktree_root.is_dir()
                    and worktree_root.resolve().parent == sandbox.resolve()
                ):
                    shutil.rmtree(worktree_root)
            if fixture_setup_error is not None:
                raise ValueError(fixture_setup_error)
            if fixture_cleanup_error is not None:
                raise ValueError(fixture_cleanup_error)
            return outcome
    if name == "interrupted-transaction":
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _init_project(project)
            transaction = _read_json(Path(__file__).resolve().parents[1] / "examples/transaction.json")
            transaction["status"] = "APPLYING"
            transaction["committed_at"] = None
            transaction["commit_marker"] = None
            _write_json(project / ".agent/runtime/transactions" / f"{transaction['operation_id']}.json", transaction)
            code, output = _run_command(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parent / "inspect_recovery.py"),
                    "--project-root",
                    str(project),
                ]
            )
            if code:
                return None
            try:
                result = json.loads(output)
            except json.JSONDecodeError:
                return None
            if any(
                item.get("classification") == "RECOVERY_PENDING"
                for item in result.get("transactions", [])
            ):
                return "RECOVERY_PENDING", output
            return None
    if name == "wrong-run-attempt-handoff":
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _init_project(project)
            task_id = "T-V1"
            _write_json(
                project / ".agent/work/T-V1/task-state.json",
                {
                    "task_id": task_id,
                    "revision": 1,
                    "run_id": "RUN-V1",
                    "attempt_id": "ATTEMPT-V1",
                    "dispatch_id": "DSP-V1",
                    "status": "RUNNING",
                },
            )
            handoff = _wrong_run_attempt_handoff_payload()
            code, output = _project_cli("create_handoff.py", project, handoff, "--task-id", task_id)
            return ("REJECT", output) if code else None
    if name == "secret-bearing-context":
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            _init_project(project)
            context = {
                "context_id": "CTX-SECRET-1",
                "created_at": "2026-08-04T00:00:00Z",
                "revision": 1,
                "task": {"task_id": "T-V1", "objective": "negative example"},
                "required_documents": [],
                "code_context": {
                    "files_to_read": [],
                    "symbols_to_inspect": [],
                    "existing_patterns": [],
                    "file_contents": {"config.py": "API_TOKEN=secret-value"},
                },
                "constraints": {"inherited": [], "task_specific": []},
                "review_history": [],
                "budget": {"max_files": 1, "max_reference_documents": 1, "max_examples": 1},
            }
            code, output = _project_cli("create_context.py", project, context)
            return ("REJECT", output) if code else None
    return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


def _schema_errors(value: Any, schema_path: Path) -> list[str]:
    schema = _read_json(schema_path)
    return validate(value, schema, base_path=schema_path.resolve().parent)


def _validate_one(path: Path, *, config: dict[str, Any], deployment: dict[str, Any], schema_root: Path) -> list[str]:
    value = _read_json(path)
    errors: list[str] = []
    if path.name == "v1-planning-bundle.json":
        errors.extend(validate_manifest(value))
        if not errors:
            errors.extend(_validate_special_runtime(path, value))
        return errors
    schema_name = SCHEMA_MAP.get(path.name)
    if schema_name is None:
        return ["no runtime validator is registered"]
    errors.extend(_schema_errors(value, schema_root / schema_name))
    if errors:
        return errors
    errors.extend(_schema_cli_errors(path, schema_root / schema_name))
    if errors:
        return errors
    errors.extend(_positive_runtime_errors(path, value))
    if errors:
        return errors
    errors.extend(_validate_special_runtime(path, value))
    if errors:
        return errors
    try:
        if path.name == "context.json":
            normalize_context(value, config)
        elif path.name == "event.json":
            validate_event(value)
        elif path.name == "review.json":
            if not isinstance(value.get("resolved_rubric"), dict) and value.get("legacy_migration") is not True:
                raise ValueError("review example lacks a resolved_rubric")
        elif path.name == "batch-review.json":
            if value.get("legacy_migration") is not True:
                normalize_batch_review(value)
        elif path.name == "v1-dispatch.json":
            dispatch = copy.deepcopy(value)
            role = dispatch.get("agent_role")
            reference = dispatch.get("model_reference")
            if reference == f"agents.{role}.model_ref" and isinstance(config.get("agents", {}).get(role), dict):
                dispatch["selected_model"] = deployment["model_ids"][config["agents"][role]["model_ref"]]
            dispatch["input_revisions"] = {"task": 1, "queue": 0}
            normalize_dispatch(dispatch, config, deployment)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return errors


def validate_all_examples(
    examples_root: str | Path,
    *,
    config_root: str | Path | None = None,
    deployment_path: str | Path | None = None,
) -> list[str]:
    examples = Path(examples_root).expanduser().resolve()
    configuration = Path(config_root).expanduser().resolve() if config_root else CONFIG_SKILL
    config = load_config(configuration / "config/agentic-config.yaml")
    deployment = load_deployment_config(deployment_path, config)
    schema_root = Path(__file__).resolve().parents[1] / "schemas"
    errors: list[str] = []
    for path in sorted(path for path in examples.iterdir() if path.is_file()):
        try:
            classification = EXAMPLE_CLASSIFICATIONS.get(path.name)
            if classification == "DOCUMENTATION_ONLY":
                text = path.read_text(encoding="utf-8")
                path_errors = [] if "Example classification: DOCUMENTATION_ONLY" in text else [
                    "documentation-only example is missing its explicit classification marker"
                ]
            elif path.suffix == ".json":
                path_errors = _validate_one(path, config=config, deployment=deployment, schema_root=schema_root)
            else:
                path_errors = ["no example classification is registered"]
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            path_errors = [str(exc)]
        errors.extend(f"{path.name}: {error}" for error in path_errors)
    return errors


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--examples-root", required=True)
    parser.add_argument("--deployment")
    args = parser.parse_args()
    try:
        errors = validate_all_examples(args.examples_root, deployment_path=args.deployment)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"EXAMPLES_INVALID: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"EXAMPLE_INVALID: {error}", file=sys.stderr)
        return 1
    print("EXAMPLES_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
