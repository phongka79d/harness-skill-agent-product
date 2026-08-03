"""Run tests from staged skills whose directory names are not Python packages."""

from __future__ import annotations

import importlib.util
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STATE_ROOT = ROOT / "skills" / "agentic-state-tools"
CONFIG_ROOT = ROOT / "skills" / "agentic-configuration"
DEPLOYMENT_TEST = CONFIG_ROOT / "config" / "deployment.test.json"
GROUP_NAMES = (
    "unit",
    "schema",
    "cli",
    "integration",
    "end_to_end",
    "recovery",
    "concurrency",
    "rollback",
    "review_integrity",
    "examples",
    "package",
)
GROUP_ASSIGNMENTS = {
    "test_config.py": "schema",
    "test_schema_runtime.py": "schema",
    "test_skill_metadata.py": "unit",
    "test_wiki_routing.py": "unit",
    "test_orchestration.py": "cli",
    "test_distributed_state.py": "concurrency",
    "test_p1a.py": "schema",
    "test_recovery_hardening.py": "recovery",
    "test_report_gaps.py": "integration",
    "test_rollback.py": "rollback",
    "test_adaptive_quality.py": "review_integrity",
    "test_state_tools.py": "integration",
    "test_v1_workflow.py": "end_to_end",
    "test_authorization.py": "review_integrity",
    "test_commit_batch.py": "rollback",
    "test_release_runner.py": "unit",
    "test_example_runtime.py": "examples",
    "test_packaging.py": "package",
}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".agent", "runtime", "dist", "build"}


def discover_test_files() -> list[Path]:
    return [
        path
        for path in sorted((ROOT / "skills").glob("*/tests/test_*.py"))
        if not any(part in EXCLUDED_PARTS for part in path.relative_to(ROOT).parts)
    ]


def test_groups() -> dict[str, list[Path]]:
    groups = {name: [] for name in GROUP_NAMES}
    for path in discover_test_files():
        group = GROUP_ASSIGNMENTS.get(path.name, "unit")
        groups[group].append(path)
    return groups


def empty_group_summary(group: str) -> dict[str, object]:
    return {
        "group": group,
        "tests": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "elapsed_seconds": 0.0,
        "timed_out": False,
    }


def _module_name(test_path: Path) -> str:
    return "staged_" + "_".join(test_path.relative_to(ROOT).with_suffix("").parts)


def validate_release_examples() -> list[str]:
    """Validate the bundled V1 examples before loading the test suite."""

    examples = STATE_ROOT / "examples"
    release_env = os.environ.copy()
    release_env["AGENTIC_DEPLOYMENT_CONFIG"] = str(DEPLOYMENT_TEST)
    preflight_commands = [
        ("agentic-config", [sys.executable, str(CONFIG_ROOT / "scripts/load_config.py"), "--check", "--deployment", str(DEPLOYMENT_TEST)]),
        ("agentic-config-schema", [sys.executable, str(STATE_ROOT / "scripts/validate_payload.py"), "--input", str(CONFIG_ROOT / "config/agentic-config.yaml"), "--schema", str(CONFIG_ROOT / "schemas/agentic-config.schema.json")]),
        ("example-runtime", [sys.executable, str(STATE_ROOT / "scripts/validate_examples.py"), "--examples-root", str(examples), "--deployment", str(DEPLOYMENT_TEST)]),
    ]
    example_commands = [
        ("v1-planning-bundle.json", [sys.executable, str(STATE_ROOT / "scripts/validate_planning.py"), "--input", str(examples / "v1-planning-bundle.json")]),
        ("v1-dispatch.json", [sys.executable, str(STATE_ROOT / "scripts/validate_payload.py"), "--input", str(examples / "v1-dispatch.json"), "--schema", str(STATE_ROOT / "schemas/dispatch.schema.json")]),
        ("v1-recovery.json", [sys.executable, str(STATE_ROOT / "scripts/validate_payload.py"), "--input", str(examples / "v1-recovery.json"), "--schema", str(STATE_ROOT / "schemas/reconciliation.schema.json")]),
    ]
    errors: list[str] = []
    for name, command in preflight_commands:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, env=release_env)
        if result.returncode != 0:
            errors.append(f"{name}: {result.stderr.strip() or result.stdout.strip()}")
    for name, command in example_commands:
        path = examples / name
        if not path.is_file():
            errors.append(f"missing release example: {name}")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"invalid JSON in {name}: {exc}")
            continue
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, env=release_env)
        if result.returncode != 0:
            errors.append(f"{name}: {result.stderr.strip() or result.stdout.strip()}")
        if name == "v1-dispatch.json":
            try:
                dispatch = json.loads(path.read_text(encoding="utf-8"))
                dispatch["input_revisions"] = {"task": 1, "queue": 0}
                with tempfile.TemporaryDirectory(prefix="agentic-release-dispatch-") as directory:
                    project = Path(directory) / "project"
                    init_result = subprocess.run(
                        [sys.executable, str(STATE_ROOT / "scripts/init_runtime.py"), "--project-root", str(project)],
                        cwd=ROOT,
                        text=True,
                        capture_output=True,
                        check=False,
                        env=release_env,
                    )
                    if init_result.returncode != 0:
                        errors.append(f"{name} policy init: {init_result.stderr.strip() or init_result.stdout.strip()}")
                    ready = Path(directory) / "ready.json"
                    ready.write_text(json.dumps({"task_id": dispatch.get("task_id"), "title": "release", "status": "READY", "depends_on": [], "write_scope": []}), encoding="utf-8")
                    ready_result = subprocess.run(
                        [sys.executable, str(STATE_ROOT / "scripts/update_task_state.py"), "--project-root", str(project), "--input", str(ready)],
                        cwd=ROOT,
                        text=True,
                        capture_output=True,
                        check=False,
                        env=release_env,
                    )
                    if ready_result.returncode != 0:
                        errors.append(f"{name} policy task: {ready_result.stderr.strip() or ready_result.stdout.strip()}")
                    policy_command = [sys.executable, str(STATE_ROOT / "scripts/dispatch_task.py"), "--project-root", str(project), "--input", "-"]
                    policy_result = subprocess.run(
                        policy_command,
                        cwd=ROOT,
                        input=json.dumps(dispatch),
                        text=True,
                        capture_output=True,
                        check=False,
                        env=release_env,
                    )
                    if policy_result.returncode != 0:
                        errors.append(f"{name} policy: {policy_result.stderr.strip() or policy_result.stdout.strip()}")
            except (OSError, TypeError, ValueError) as exc:
                errors.append(f"{name} policy: {exc}")
    return errors


def load_suite(group: str | None = None) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    paths = test_groups().get(group, []) if group is not None else discover_test_files()
    if group is not None and group not in GROUP_NAMES:
        raise ValueError(f"unknown test group: {group}")
    for test_path in paths:
        module_name = _module_name(test_path)
        spec = importlib.util.spec_from_file_location(module_name, test_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load test module: {test_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


def run_group(group: str) -> dict[str, object]:
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(load_suite(group))
    failed = len(result.failures) + len(result.errors)
    skipped = len(result.skipped)
    return {
        "group": group,
        "tests": result.testsRun,
        "passed": result.testsRun - failed - skipped,
        "failed": failed,
        "skipped": skipped,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "timed_out": False,
    }


def _worker_main(group: str) -> int:
    summary = run_group(group)
    print("GROUP_RESULT:" + json.dumps(summary, sort_keys=True))
    return 0 if summary["failed"] == 0 else 1


def _run_group_process(group: str, timeout_seconds: int) -> dict[str, object]:
    started = time.monotonic()
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", "--group", group],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        summary = empty_group_summary(group)
        summary["timed_out"] = True
        summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
        summary["failed"] = 1
        return summary
    summary: dict[str, object] | None = None
    for line in process.stdout.splitlines():
        if line.startswith("GROUP_RESULT:"):
            try:
                parsed = json.loads(line.removeprefix("GROUP_RESULT:"))
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                summary = parsed
    if summary is None:
        summary = empty_group_summary(group)
        summary["failed"] = 1
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    if process.returncode != 0 and summary.get("failed", 0) == 0:
        summary["failed"] = 1
    print(process.stdout, end="")
    if process.stderr:
        print(process.stderr, file=sys.stderr, end="")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--group", choices=GROUP_NAMES)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if args.worker:
        if args.group is None:
            parser.error("--worker requires --group")
        return _worker_main(args.group)

    release_errors = validate_release_examples()
    if release_errors:
        for error in release_errors:
            print(f"RELEASE_GATE_FAILED: {error}", file=sys.stderr)
        return 1
    groups = [args.group] if args.group else list(GROUP_NAMES)
    summaries = [_run_group_process(group, args.timeout) for group in groups]
    for summary in summaries:
        print("TEST_GROUP_SUMMARY:" + json.dumps(summary, sort_keys=True))
    return 0 if all(summary["failed"] == 0 and not summary["timed_out"] for summary in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
