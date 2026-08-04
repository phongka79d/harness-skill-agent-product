from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "skills" / "agentic-state-tools"
SCRIPTS = ROOT / "scripts"
WORKSPACE = ROOT.parent.parent


class P1ASourceOfTruthTests(unittest.TestCase):
    def test_state_machine_source_covers_runtime_statuses(self) -> None:
        source_path = ROOT / "schemas/state-machine.json"
        self.assertTrue(source_path.is_file())
        source = json.loads(source_path.read_text(encoding="utf-8"))
        required = {
            "PENDING", "READY", "QUEUED", "QUEUED_ASYNC", "QUEUED_SYNC", "RUNNING",
            "CHECKPOINTED", "WAITING_DEPENDENCY", "WAITING_RESOURCE_LOCK", "BLOCKED",
            "REVIEWING", "REPAIR_REQUIRED", "ACCEPTED", "STALE", "RECOVERY_PENDING",
            "RESUMING", "DEFERRED", "CANCELLED", "SUPERSEDED", "ABORTED_UNSAFE",
            "ESCALATED", "ARCHIVED",
        }
        self.assertTrue(required.issubset(source["statuses"]), sorted(required - set(source["statuses"])))
        self.assertTrue(all(item.get("event") for item in source["statuses"].values()))
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_state_machine.py"), "--input", str(source_path)],
            cwd=str(SCRIPTS),
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STATE_MACHINE_VALID", result.stdout)

    def test_shared_wiki_routes_to_existing_contracts(self) -> None:
        wiki_root = WORKSPACE / "skills" / "agentic-engineering-wiki"
        skill = wiki_root / "SKILL.md"
        self.assertTrue(skill.is_file())
        body = skill.read_text(encoding="utf-8")
        for route in (
            "refs/architecture/architecture.md",
            "refs/roles/plan-architect.md",
            "refs/workflows/recovery.md",
            "refs/policies/state-boundary.md",
            "refs/contracts/handoff.md",
        ):
            self.assertIn(route, body)
        result = subprocess.run(
            [sys.executable, str(wiki_root / "scripts/validate_wiki_links.py"), "--root", str(wiki_root)],
            cwd=str(wiki_root),
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WIKI_VALID", result.stdout)


if __name__ == "__main__":
    unittest.main()
