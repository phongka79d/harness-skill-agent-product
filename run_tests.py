"""Run the explicit test groups and the ordered release preflight."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
STATE_ROOT = ROOT / "skills" / "agentic-state-tools"
CONFIG_ROOT = ROOT / "skills" / "agentic-configuration"
DEPLOYMENT_TEST = CONFIG_ROOT / "config" / "deployment.test.json"
TEST_ROOT = ROOT / "tests"

# These are the only executable test directories owned by the release runner.
GROUP_NAMES = (
    "unit",
    "schema",
    "cli",
    "integration",
    "e2e",
    "recovery",
    "concurrency",
    "release",
)
# The nested grouped suite receives one caller timeout budget per configured group.
GROUPED_SUITE_TIMEOUT_MULTIPLIER = len(GROUP_NAMES)
GROUP_ALIASES = {"end_to_end": "e2e"}
GROUP_ASSIGNMENTS = {
    "test_config.py": "schema",
    "test_schema_runtime.py": "schema",
    "test_p1a.py": "schema",
    "test_skill_metadata.py": "unit",
    "test_wiki_routing.py": "unit",
    "test_dashboard.py": "unit",
    "test_context_security.py": "unit",
    "test_orchestration.py": "cli",
    "test_distributed_state.py": "concurrency",
    "test_report_gaps.py": "integration",
    "test_state_tools.py": "integration",
    "test_example_runtime.py": "integration",
    "test_v1_workflow.py": "e2e",
    "test_recovery_hardening.py": "recovery",
    "test_recovery_policy.py": "recovery",
    "test_task4_merge_recovery.py": "recovery",
    "test_transaction_recovery.py": "recovery",
    "test_adaptive_quality.py": "release",
    "test_authorization.py": "release",
    "test_commit_batch.py": "release",
    "test_contract_hardening.py": "release",
    "test_rollback.py": "release",
    "test_transition_registry.py": "release",
    "test_release_runner.py": "release",
    "test_release_gate.py": "release",
    "test_packaging.py": "release",
}

EXCLUDED_PARTS = {
    ".git",
    ".agent",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "coverage",
    "tmp",
    "temp",
    "temporary",
}


def _relative_parts(path: Path) -> tuple[str, ...]:
    try:
        return path.resolve().relative_to(ROOT).parts
    except ValueError:
        return ()


def _is_excluded(path: Path) -> bool:
    return any(part.casefold() in EXCLUDED_PARTS for part in _relative_parts(path))


def _skill_test_roots() -> Iterable[Path]:
    skills_root = ROOT / "skills"
    if not skills_root.is_dir():
        return ()
    return (
        skill / "tests"
        for skill in sorted(skills_root.iterdir())
        if skill.is_dir()
        and ((skill / "SKILL.md").is_file() or skill.name.startswith("agentic-"))
    )


def discover_test_files() -> list[Path]:
    """Discover only configured group tests and official skill-local tests."""

    candidates: set[Path] = set()
    for group in GROUP_NAMES:
        group_root = TEST_ROOT / group
        if group_root.is_dir():
            candidates.update(group_root.rglob("test_*.py"))
    for test_root in _skill_test_roots():
        if test_root.is_dir():
            candidates.update(test_root.rglob("test_*.py"))
    return sorted(
        path.resolve()
        for path in candidates
        if path.is_file() and not path.is_symlink() and not _is_excluded(path)
    )


def _path_group(path: Path) -> str:
    parts = _relative_parts(path)
    if len(parts) >= 3 and parts[0].casefold() == "tests" and parts[1] in GROUP_NAMES:
        return parts[1]
    return GROUP_ASSIGNMENTS.get(path.name, "unit")


def test_groups() -> dict[str, list[Path]]:
    groups = {name: [] for name in GROUP_NAMES}
    for path in discover_test_files():
        group = _path_group(path)
        groups.setdefault(group, []).append(path)
    for paths in groups.values():
        paths.sort()
    return groups


def empty_group_summary(group: str) -> dict[str, object]:
    return {
        "group": group,
        "tests": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "collection_errors": 0,
        "elapsed_seconds": 0.0,
        "timed_out": False,
    }


def _module_name(test_path: Path) -> str:
    return "staged_" + "_".join(test_path.relative_to(ROOT).with_suffix("").parts)


def load_suite(group: str | None = None) -> unittest.TestSuite:
    """Import pure-Python test modules into one in-process suite."""

    if group is not None:
        group = GROUP_ALIASES.get(group, group)
        if group not in GROUP_NAMES:
            raise ValueError(f"unknown test group: {group}")
    paths = test_groups().get(group, []) if group is not None else discover_test_files()
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
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


def _parse_subprocess_tests(process: subprocess.CompletedProcess[str], group: str) -> dict[str, object]:
    summary = empty_group_summary(group)
    output = (process.stdout or "") + "\n" + (process.stderr or "")
    match = re.search(r"Ran (\d+) tests?", output)
    if match:
        summary["tests"] = int(match.group(1))
    skipped_match = re.search(r"skipped=(\d+)", output)
    if skipped_match:
        summary["skipped"] = int(skipped_match.group(1))
    summary["failed"] = 0 if process.returncode == 0 else 1
    summary["passed"] = max(0, int(summary["tests"]) - int(summary["skipped"]) - int(summary["failed"]))
    if process.returncode != 0 and (
        int(summary["tests"]) == 0
        or any(marker in output for marker in ("ImportError", "ModuleNotFoundError", "SyntaxError"))
    ):
        summary["collection_errors"] = 1
    return summary


def _run_cli_group(paths: list[Path], timeout_seconds: int = 120) -> dict[str, object]:
    summary = empty_group_summary("cli")
    started = time.monotonic()
    for path in paths:
        command = [sys.executable, "-m", "unittest", "discover", "-s", str(path.parent), "-p", path.name]
        try:
            process = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            summary["failed"] = int(summary["failed"]) + 1
            summary["timed_out"] = True
            print(exc.stdout or "", end="")
            continue
        parsed = _parse_subprocess_tests(process, "cli")
        for key in ("tests", "passed", "failed", "skipped", "collection_errors"):
            summary[key] = int(summary[key]) + int(parsed[key])
        summary["timed_out"] = bool(summary["timed_out"]) or bool(parsed["timed_out"])
        print(process.stdout, end="")
        if process.stderr:
            print(process.stderr, file=sys.stderr, end="")
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return summary


def run_group(group: str, timeout_seconds: int = 120) -> dict[str, object]:
    group = GROUP_ALIASES.get(group, group)
    if group not in GROUP_NAMES:
        raise ValueError(f"unknown test group: {group}")
    if group == "cli":
        return _run_cli_group(test_groups()[group], timeout_seconds)
    started = time.monotonic()
    summary = empty_group_summary(group)
    try:
        result = unittest.TextTestRunner(verbosity=2).run(load_suite(group))
    except Exception as exc:  # collection errors are release failures, not hidden exceptions
        print(f"COLLECTION_ERROR[{group}]: {exc}", file=sys.stderr)
        summary["failed"] = 1
        summary["collection_errors"] = 1
        summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return summary
    failed = len(result.failures) + len(result.errors)
    skipped = len(result.skipped)
    summary.update(
        {
            "tests": result.testsRun,
            "passed": result.testsRun - failed - skipped,
            "failed": failed,
            "skipped": skipped,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    )
    return summary


def _run_release_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=exc.stdout or "",
            stderr=f"TIMEOUT: release command exceeded {timeout_seconds} seconds",
        )


def release_preflight_commands(output: str | Path = r"C:\Temp\agent-skills-release.zip") -> list[tuple[str, list[str]]]:
    """Return the ordered, named commands required for a release."""

    return [
        ("test-suite", [sys.executable, str(ROOT / "run_tests.py"), "--all"]),
        ("compile", [sys.executable, "-m", "compileall", "-q", "skills", "tests", "run_tests.py"]),
        (
            "wiki-links",
            [
                sys.executable,
                str(ROOT / "skills/agentic-engineering-wiki/scripts/validate_wiki_links.py"),
                "--root",
                str(ROOT / "skills/agentic-engineering-wiki"),
            ],
        ),
        (
            "state-machine",
            [
                sys.executable,
                str(ROOT / "skills/agentic-state-tools/scripts/validate_state_machine.py"),
                "--input",
                str(ROOT / "skills/agentic-state-tools/schemas/state-machine.json"),
            ],
        ),
        (
            "examples",
            [
                sys.executable,
                str(ROOT / "skills/agentic-state-tools/scripts/validate_examples.py"),
                "--examples-root",
                str(ROOT / "skills/agentic-state-tools/examples"),
                "--deployment",
                str(ROOT / "skills/agentic-configuration/config/deployment.test.json"),
            ],
        ),
        (
            "package",
            [
                sys.executable,
                str(ROOT / "skills/agentic-state-tools/scripts/package_skill.py"),
                "--root",
                str(ROOT),
                "--output",
                str(output),
            ],
        ),
    ]


def run_release_preflight(timeout_seconds: int = 120) -> list[str]:
    errors: list[str] = []
    env = os.environ.copy()
    env["AGENTIC_DEPLOYMENT_CONFIG"] = str(DEPLOYMENT_TEST)
    for name, command in release_preflight_commands():
        command_env = dict(env)
        if name == "test-suite":
            command_env["AGENTIC_RELEASE_GROUPS_ONLY"] = "1"
        command_timeout = (
            timeout_seconds * GROUPED_SUITE_TIMEOUT_MULTIPLIER
            if name == "test-suite"
            else timeout_seconds
        )
        result = _run_release_process(
            command,
            cwd=ROOT,
            env=command_env,
            timeout_seconds=command_timeout,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "command failed").strip()
            errors.append(f"{name}: {detail}")
    return errors


def validate_release_examples(timeout_seconds: int = 120) -> list[str]:
    """Compatibility name for the complete release preflight."""

    return run_release_preflight(timeout_seconds=timeout_seconds)


def _print_group_summaries(summaries: list[dict[str, object]]) -> None:
    for summary in summaries:
        print("TEST_GROUP_SUMMARY:" + json.dumps(summary, sort_keys=True))


def _run_all_groups(timeout_seconds: int) -> int:
    summaries = [run_group(group, timeout_seconds) for group in GROUP_NAMES]
    _print_group_summaries(summaries)
    return 0 if all(summary["failed"] == 0 and not summary["timed_out"] for summary in summaries) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="run the complete ordered release preflight")
    parser.add_argument("--group", choices=tuple(GROUP_NAMES) + tuple(GROUP_ALIASES), help="run one named test group")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    if args.group:
        summary = run_group(args.group, args.timeout)
        print("TEST_GROUP_SUMMARY:" + json.dumps(summary, sort_keys=True))
        return 0 if summary["failed"] == 0 and not summary["timed_out"] else 1
    if args.all and os.environ.get("AGENTIC_RELEASE_GROUPS_ONLY") == "1":
        return _run_all_groups(args.timeout)
    if args.all or os.environ.get("AGENTIC_RELEASE_GROUPS_ONLY") != "1":
        errors = run_release_preflight(timeout_seconds=args.timeout)
        for error in errors:
            print(f"RELEASE_PREFLIGHT_FAILED: {error}", file=sys.stderr)
        return 0 if not errors else 1
    return _run_all_groups(args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
