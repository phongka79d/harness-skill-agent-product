from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
STATE_SCRIPTS = Path(__file__).resolve().parents[2] / "agentic-state-tools" / "scripts"


def run_dashboard(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "project_dashboard.py"), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def run_state_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(STATE_SCRIPTS / name), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def init_fixture(project: Path) -> Path:
    initialized = run_state_script("init_runtime.py", "--project-root", str(project))
    if initialized.returncode:
        raise AssertionError(initialized.stderr)

    root = project / ".agent"
    write_json(
        root / "runtime/state.json",
        {
            "schema_version": 1,
            "revision": 7,
            "previous_revision": 6,
            "last_event_id": "EVT-000002",
            "updated_at": "2026-08-02T11:00:00Z",
            "running_tasks": ["T-001"],
            "blocked_tasks": [],
            "completed_tasks": [],
            "task_statuses": {"T-001": "RUNNING"},
        },
    )
    (root / "runtime/events.jsonl").write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "event_id": "EVT-000001",
                    "timestamp": "2026-08-02T10:00:00Z",
                    "type": "TASK_QUEUED",
                    "actor": "primary-agent",
                    "task_id": "T-001",
                },
                {
                    "event_id": "EVT-000002",
                    "timestamp": "2026-08-02T11:00:00Z",
                    "type": "TASK_STARTED",
                    "actor": "executor",
                    "task_id": "T-001",
                    "data": {"token": "event-secret"},
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    write_json(
        root / "runtime/queue.json",
        {
            "schema_version": 1,
            "queue_id": "RUNTIME-QUEUE",
            "revision": 3,
            "tasks": [
                {
                    "task_id": "T-001",
                    "status": "RUNNING",
                    "execution_mode": "SYNC",
                    "depends_on": [],
                    "owner": "executor",
                    "token": "queue-secret",
                }
            ],
            "task_states": [],
            "dispatches": [
                {
                    "dispatch_id": "DSP-001",
                    "task_id": "T-001",
                    "selected_mode": "SYNC",
                    "selected_owner": "executor",
                }
            ],
            "locks": [],
        },
    )
    write_json(
        root / "work/T-001/task-state.json",
        {
            "schema_version": 1,
            "task_id": "T-001",
            "batch_id": "B-001",
            "status": "RUNNING",
            "revision": 2,
            "updated_at": "2026-08-02T11:00:00Z",
            "next_action": "verify",
        },
    )
    write_json(
        root / "work/T-001/review.json",
        {
            "review_id": "REV-001",
            "task_id": "T-001",
            "verdict": "PENDING",
            "updated_at": "2026-08-02T11:00:00Z",
            "resolved_rubric": {
                "rubric_id": "task-general",
                "rubric_version": "1.0",
                "rubric_hash": "a" * 64,
            },
            "authorization": "review-secret",
        },
    )
    write_json(
        root / "work/T-001/lease.json",
        {
            "task_id": "T-001",
            "owner": "executor",
            "run_id": "RUN-001",
            "created_at": "2026-08-02T10:00:00Z",
            "expires_at": "2026-08-02T10:30:00Z",
        },
    )
    write_json(
        root / "locks/tasks/task-001.json",
        {
            "kind": "task",
            "key": "T-001",
            "task_id": "T-001",
            "owner": "executor",
            "run_id": "RUN-001",
            "acquired_at": "2026-08-02T10:00:00Z",
        },
    )
    write_json(
        root / "recovery/recovery-state.json",
        {
            "schema_version": 1,
            "inspected_at": "2026-08-02T11:00:00Z",
            "results": [
                {
                    "task_id": "T-001",
                    "classification": "NEEDS_RECONCILIATION",
                    "reasons": ["active task lease has expired"],
                }
            ],
        },
    )
    return root


def tree_digest(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class DashboardTests(unittest.TestCase):
    def test_snapshot_is_reproducible_and_contains_all_views(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            root = init_fixture(project)
            config = write_json(project / "dashboard-config.json", {"redact_keys": ["token", "authorization"], "stale_after_seconds": 3600})
            args = ("--project-root", str(project), "--config", str(config), "--as-of", "2026-08-02T12:00:00Z")
            first = run_dashboard(*args)
            second = run_dashboard(*args)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(first.stdout, second.stdout)
            snapshot = json.loads(first.stdout)
            self.assertEqual(
                run_state_script(
                    "validate_schema.py",
                    "--input",
                    str(config),
                    "--schema",
                    str(SCHEMAS / "dashboard-config.schema.json"),
                ).returncode,
                0,
            )
            self.assertEqual(snapshot["schema_version"], 1)
            self.assertEqual(snapshot["source"]["runtime_revision"], 7)
            self.assertEqual(
                set(snapshot["views"]),
                {"queue", "state_history", "reviews", "locks", "leases", "recovery", "events"},
            )
            self.assertTrue((root / "runtime/state.json").is_file())

    def test_configured_redaction_is_recursive_and_stale_evidence_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            init_fixture(project)
            config = write_json(project / "dashboard-config.json", {"redact_keys": ["token", "authorization"], "stale_after_seconds": 3600})
            result = run_dashboard(
                "--project-root",
                str(project),
                "--config",
                str(config),
                "--as-of",
                "2026-08-02T12:00:00Z",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads(result.stdout)
            rendered = result.stdout
            self.assertNotIn("event-secret", rendered)
            self.assertNotIn("queue-secret", rendered)
            self.assertNotIn("review-secret", rendered)
            self.assertEqual(snapshot["redaction"]["replacement"], "[REDACTED]")
            leases = snapshot["views"]["leases"]["items"]
            self.assertTrue(leases[0]["stale"])
            self.assertIn("EXPIRED", leases[0]["stale_reasons"])

    def test_malformed_source_becomes_a_diagnostic_without_mutating_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            root = init_fixture(project)
            (root / "work/T-001/review.json").write_text("{broken\n", encoding="utf-8")
            before = tree_digest(root)
            result = run_dashboard("--project-root", str(project), "--as-of", "2026-08-02T12:00:00Z")
            after = tree_digest(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(before, after)
            snapshot = json.loads(result.stdout)
            self.assertTrue(any(item["code"] == "MALFORMED_SOURCE" for item in snapshot["diagnostics"]))
            self.assertEqual(snapshot["views"]["reviews"]["items"], [])

    def test_export_is_validated_and_cannot_target_agent_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            root = init_fixture(project)
            output = project / "exports/dashboard.json"
            result = run_dashboard(
                "--project-root",
                str(project),
                "--output",
                str(output),
                "--as-of",
                "2026-08-02T12:00:00Z",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())
            self.assertEqual(run_state_script("validate_schema.py", "--input", str(output), "--schema", str(SCHEMAS / "dashboard-snapshot.schema.json")).returncode, 0)
            rejected = run_dashboard(
                "--project-root",
                str(project),
                "--output",
                str(root / "dashboard.json"),
                "--as-of",
                "2026-08-02T12:00:00Z",
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("DASHBOARD_REJECTED", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
