from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCHEMAS = ROOT / "schemas"
sys.path.insert(0, str(SCRIPTS))

import state_machine  # noqa: E402
from state_machine import event_status_map, load_state_machine, status_event_map, transition_map  # noqa: E402
from state_transition_registry import TRANSITIONS, build_state_machine, validate_transition_records  # noqa: E402
from validate_state_machine import validate_definition  # noqa: E402
from validate_transition import is_allowed_transition  # noqa: E402


class TransitionRegistryTests(unittest.TestCase):
    def test_registry_generates_checked_in_status_events_and_runtime_maps(self) -> None:
        generated = build_state_machine()
        checked_in = load_state_machine()
        self.assertEqual(generated, checked_in)
        self.assertEqual(
            set(json.loads((SCHEMAS / "task-state.schema.json").read_text(encoding="utf-8"))["properties"]["status"]["enum"]),
            set(generated["statuses"]),
        )
        event_enum = set(json.loads((SCHEMAS / "event.schema.json").read_text(encoding="utf-8"))["properties"]["type"]["enum"])
        self.assertEqual(event_enum, set(status_event_map().values()) | set(generated["non_state_events"]))
        self.assertEqual(event_status_map(), {event: status for status, event in status_event_map().items()})
        self.assertEqual(transition_map("executor")["COMPLETED"], {"REVIEWING", "REPAIR_REQUIRED"})

    def test_transition_records_are_complete_and_review_guards_are_pinned(self) -> None:
        self.assertTrue(TRANSITIONS)
        for transition in TRANSITIONS:
            for field in ("from", "to", "allowed_roles", "required_artifacts", "required_guards"):
                self.assertIn(field, transition)
            self.assertIsInstance(transition["from"], str)
            self.assertIsInstance(transition["to"], str)
            self.assertTrue(transition["allowed_roles"])
            self.assertIsInstance(transition["required_artifacts"], tuple)
            self.assertIsInstance(transition["required_guards"], tuple)
        review_transitions = [
            transition for transition in TRANSITIONS
            if transition["from"] in {"COMPLETED", "REVIEWING"}
            and transition["to"] in {"REVIEWING", "ACCEPTED", "REPAIR_REQUIRED", "BLOCKED"}
        ]
        self.assertTrue(review_transitions)
        for transition in review_transitions:
            self.assertIn("same_run", transition["required_guards"])
            self.assertIn("same_attempt", transition["required_guards"])

    def test_executor_cannot_accept_and_review_paths_are_explicit(self) -> None:
        self.assertFalse(is_allowed_transition("COMPLETED", "ACCEPTED", actor="executor"))
        self.assertTrue(is_allowed_transition("COMPLETED", "REVIEWING", actor="executor"))
        self.assertTrue(is_allowed_transition("COMPLETED", "REVIEWING", actor="reviewer"))
        self.assertTrue(is_allowed_transition("REVIEWING", "ACCEPTED", actor="reviewer"))
        self.assertTrue(is_allowed_transition("REVIEWING", "REPAIR_REQUIRED", actor="reviewer"))
        self.assertTrue(is_allowed_transition("REPAIR_REQUIRED", "RUNNING", actor="executor"))

    def test_cleanup_archives_all_terminal_business_outcomes(self) -> None:
        for current in ("ACCEPTED", "CANCELLED", "SUPERSEDED"):
            self.assertTrue(is_allowed_transition(current, "ARCHIVED", actor="cleanup"), current)

    def test_state_machine_validation_reports_registry_drift_categories(self) -> None:
        definition = copy.deepcopy(build_state_machine())
        definition["statuses"]["PENDING"]["executor"].append("ARCHIVED")
        definition["statuses"].pop("READY")
        definition["statuses"]["PENDING"]["event"] = "TASK_DRIFTED"
        definition["statuses"]["PENDING"]["required_artifacts"] = ["drift"]
        definition["statuses"]["PENDING"]["required_guards"] = ["drift"]
        errors = validate_definition(definition)
        message = " ".join(errors).lower()
        self.assertIn("missing", message)
        self.assertIn("extra", message)
        self.assertIn("event", message)
        self.assertIn("role", message)
        self.assertIn("artifact", message)
        self.assertIn("guard", message)

    def test_load_state_machine_rejects_checked_in_registry_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "state-machine.json"
            drifted = copy.deepcopy(build_state_machine())
            drifted["statuses"]["PENDING"]["event"] = "TASK_DRIFTED"
            source.write_text(json.dumps(drifted), encoding="utf-8")
            with patch.object(state_machine, "SOURCE", source):
                with self.assertRaisesRegex(ValueError, "state-machine.json drift"):
                    load_state_machine()

    def test_registry_rejects_duplicate_transition_records(self) -> None:
        duplicate = tuple([*TRANSITIONS, copy.deepcopy(TRANSITIONS[0])])
        errors = validate_transition_records(duplicate)
        self.assertTrue(any("duplicate" in error.lower() and "pending" in error.lower() for error in errors), errors)

    def test_registry_rejects_unknown_roles_artifacts_and_event_status_mismatches(self) -> None:
        unknown_role = copy.deepcopy(TRANSITIONS[0])
        unknown_role["allowed_roles"] = ("executor", "not-a-role")
        unknown_artifact = copy.deepcopy(TRANSITIONS[0])
        unknown_artifact["required_artifacts"] = ("task_state", "not-an-artifact")
        mismatched_event = copy.deepcopy(TRANSITIONS[0])
        mismatched_event["event"] = "TASK_CANCELLED"

        errors = validate_transition_records((unknown_role, unknown_artifact, mismatched_event))
        message = " ".join(errors).lower()
        self.assertIn("unknown role", message)
        self.assertIn("unknown required artifact", message)
        self.assertIn("event", message)
        self.assertIn("status", message)


if __name__ == "__main__":
    unittest.main()
