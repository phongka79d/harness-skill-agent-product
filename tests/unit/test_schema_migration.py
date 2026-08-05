from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "agentic-state-tools" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from validate_payload import (  # noqa: E402
    classify_artifact_version,
    normalize_artifact_version,
    preserve_projection_links,
    validate_artifact_payload,
)


class SchemaMigrationTests(unittest.TestCase):
    def test_legacy_and_current_versions_are_distinguished(self) -> None:
        legacy = classify_artifact_version({"task_id": "T-1"}, "context")
        self.assertEqual(legacy["classification"], "LEGACY_UNVERSIONED")
        current = classify_artifact_version({"schema_version": 1}, "context")
        self.assertEqual(current["classification"], "CURRENT")
        with self.assertRaisesRegex(ValueError, "newer"):
            classify_artifact_version({"schema_version": 99}, "context")

    def test_current_projection_records_legacy_source_without_mutating_input(self) -> None:
        source = {"task_id": "T-1"}
        projected, info = normalize_artifact_version(source, "context")
        self.assertEqual(info["classification"], "LEGACY_UNVERSIONED")
        self.assertEqual(projected["schema_version"], 1)
        self.assertTrue(projected["legacy_migration"])
        self.assertNotIn("schema_version", source)

    def test_legacy_schema_inspection_is_allowed_but_current_gate_rejects_it(self) -> None:
        schema = json.loads((ROOT / "skills/agentic-state-tools/schemas/context.schema.json").read_text(encoding="utf-8"))
        legacy = json.loads((ROOT / "skills/agentic-state-tools/examples/context.json").read_text(encoding="utf-8"))
        errors, info = validate_artifact_payload(legacy, schema, artifact_type="context")
        self.assertEqual(errors, [])
        self.assertEqual(info["classification"], "LEGACY_UNVERSIONED")
        errors, _ = validate_artifact_payload(legacy, schema, artifact_type="context", allow_legacy=False)
        self.assertTrue(any("requires migration" in error for error in errors))

    def test_projection_links_are_bound_and_conflicts_are_rejected(self) -> None:
        projected = preserve_projection_links({}, previous_id="REV-1", previous_revision=3, previous_field="previous_review_id")
        self.assertEqual(projected["previous_review_id"], "REV-1")
        self.assertEqual(projected["supersedes_id"], "REV-1")
        self.assertEqual(projected["previous_revision"], 3)
        with self.assertRaisesRegex(ValueError, "does not match"):
            preserve_projection_links({"supersedes_id": "REV-OTHER"}, previous_id="REV-1")

    def test_context_migration_collision_is_rejected_without_partial_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            init = subprocess.run(
                [sys.executable, str(SCRIPTS / "init_runtime.py"), "--project-root", str(project)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            payload = json.loads(
                (ROOT / "skills/agentic-state-tools/examples/context-current.json").read_text(encoding="utf-8")
            )
            payload["context_id"] = "CTX-MIGRATION-ATOMIC"
            payload["task"]["task_id"] = "TASK-MIGRATION-ATOMIC"
            payload.pop("budget", None)
            input_path = project / "context.json"
            input_path.write_text(json.dumps(payload), encoding="utf-8")
            command = [
                sys.executable,
                str(SCRIPTS / "create_context.py"),
                "--project-root",
                str(project),
                "--input",
                str(input_path),
            ]
            first = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            current_path = project / ".agent/work/TASK-MIGRATION-ATOMIC/context.json"
            history_path = project / ".agent/work/TASK-MIGRATION-ATOMIC/contexts/CTX-MIGRATION-ATOMIC.json"
            before_current = current_path.read_bytes()
            before_history = history_path.read_bytes()

            payload["attempt_id"] = "ATT-CURRENT-2"
            payload["dispatch_id"] = "DSP-CURRENT-2"
            input_path.write_text(json.dumps(payload), encoding="utf-8")
            second = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("context_id must be generated", second.stderr)
            self.assertEqual(current_path.read_bytes(), before_current)
            self.assertEqual(history_path.read_bytes(), before_history)


if __name__ == "__main__":
    unittest.main()
