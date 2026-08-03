from __future__ import annotations

import unittest
import re
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[2]


def description_from(skill_file: Path) -> str:
    for line in skill_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("description:"):
            return line.partition(":")[2].strip()
    raise AssertionError(f"missing description in {skill_file}")


class SkillMetadataTests(unittest.TestCase):
    def test_descriptions_are_trigger_focused(self) -> None:
        for skill_dir in sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir()):
            description = description_from(skill_dir / "SKILL.md")
            self.assertTrue(
                description.startswith("Use when "),
                f"{skill_dir.name}: description must start with 'Use when '",
            )
            self.assertLessEqual(
                len(description), 500,
                f"{skill_dir.name}: description must stay concise",
            )

    def test_skill_names_match_agent_skills_constraints(self) -> None:
        for skill_dir in sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir()):
            name = next(
                line.partition(":")[2].strip()
                for line in (skill_dir / "SKILL.md").read_text(encoding="utf-8").splitlines()
                if line.startswith("name:")
            )
            self.assertEqual(name, skill_dir.name)
            self.assertLessEqual(len(name), 64)
            self.assertRegex(name, re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$"))

    def test_ui_metadata_points_to_each_skill(self) -> None:
        for skill_dir in sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir()):
            metadata = skill_dir / "agents" / "openai.yaml"
            self.assertTrue(metadata.is_file(), f"{skill_dir.name}: missing agents/openai.yaml")
            body = metadata.read_text(encoding="utf-8")
            self.assertIn(f"${skill_dir.name}", body, f"{skill_dir.name}: default prompt must reference the skill")

    def test_relative_skill_references_resolve(self) -> None:
        for skill_dir in sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir()):
            body = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            for match in re.finditer(r"\]\(([^)]+)\)", body):
                target = match.group(1)
                if target.startswith(("http://", "https://", "#")):
                    continue
                self.assertTrue(
                    (skill_dir / target).is_file(),
                    f"{skill_dir.name}: missing referenced file {target}",
                )

    def test_role_skills_name_the_required_shared_core(self) -> None:
        for skill_dir in sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir() and path.name != "agentic-engineering-core"):
            body = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(
                "agentic-engineering-core",
                body,
                f"{skill_dir.name}: must name the shared core skill",
            )

    def test_state_skill_documents_read_only_runtime_commands(self) -> None:
        body = (SKILLS_ROOT / "agentic-state-tools" / "SKILL.md").read_text(encoding="utf-8")
        for command in (
            "inspect_recovery.py",
            "validate_schema.py",
            "acquire_lock.py",
            "release_lock.py",
            "record_heartbeat.py",
            "create_batch_review.py",
            "create_context.py",
            "record_operation.py",
        ):
            self.assertIn(command, body, f"agentic-state-tools: missing documented command {command}")

    def test_state_cli_documents_recovery_classification_exit_semantics(self) -> None:
        behavior = (SKILLS_ROOT / "agentic-state-tools" / "references" / "cli-behavior.md").read_text(encoding="utf-8")
        self.assertIn("Inspection can return exit code `0`", behavior)
        self.assertIn("UNSAFE_TO_RESUME", behavior)

    def test_architecture_keeps_configuration_out_of_agent_runtime(self) -> None:
        specification = SKILLS_ROOT / "agentic_engineering_system_complete_specification.md"
        body = specification.read_text(encoding="utf-8")
        self.assertNotIn(".agent/config.yaml", body)

    def test_architecture_documents_operation_ledger_recovery_rules(self) -> None:
        specification = SKILLS_ROOT / "agentic_engineering_system_complete_specification.md"
        body = specification.read_text(encoding="utf-8")
        for phrase in (
            "`UNKNOWN` operation outcome",
            "malformed operation ledger",
            "NEEDS_RECONCILIATION",
            "UNSAFE_TO_RESUME",
        ):
            self.assertIn(phrase, body)

    def test_central_configuration_skill_defines_all_agent_roles(self) -> None:
        config_skill = SKILLS_ROOT / "agentic-configuration"
        for relative_path in (
            "SKILL.md",
            "agents/openai.yaml",
            "config/agentic-config.yaml",
            "schemas/agentic-config.schema.json",
            "scripts/load_config.py",
            "tests/test_config.py",
        ):
            self.assertTrue((config_skill / relative_path).is_file(), relative_path)
        config = (config_skill / "config/agentic-config.yaml").read_text(encoding="utf-8")
        for role in ("agent-explorer", "agent-executor", "agent-review", "agent-batch-review", "agent-runtime-recovery"):
            self.assertIn(f'"{role}"', config)
        self.assertIn("AGENTIC_CONFIG_FILE", (config_skill / "scripts/load_config.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
