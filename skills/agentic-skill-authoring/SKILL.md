---
name: agentic-skill-authoring
description: Use when creating, revising, or pressure-testing a Harness skill, especially when triggers are vague, boundaries leak, evidence goes stale, or agents rationalize unsafe shortcuts.
---

# Agentic Skill Authoring

Use this skill to design and behavior-test a bounded Harness skill. Keep the
entrypoint short, imperative, and trigger-driven; move detail into the linked
references.

## Workflow

1. Read the active task, project profile, [agentic-engineering-core](../agentic-engineering-core/SKILL.md),
   [agentic-state-tools](../agentic-state-tools/SKILL.md), and the relevant Wiki
   contracts before changing a skill.
2. Define concrete triggers, scope boundaries, stop conditions, rigid rules,
   and profile-aware flexible guidance.
3. Put high-frequency instructions in `SKILL.md`; put design detail,
   behavioral-test procedure, and rationalization counters in the three
   references below.
4. Add or update pressure scenarios in `examples/pressure-scenarios.yaml` and
   profile rules in `examples/skill-authoring-profile.yaml`.
5. Validate scenarios against
   [behavior-scenario.schema.json](schemas/behavior-scenario.schema.json) and
   run them with [run_behavior_scenarios.py](scripts/run_behavior_scenarios.py).
   Record the configured model reference,
   deployment/config identity, scenario result, and evidence; never hard-code a
   provider.
6. Report `PASS`, `FAIL`, `BLOCKED`, or `INCONCLUSIVE` honestly. Prose
   inspection alone cannot establish behavioral hardening.

## Stop conditions

Stop and report `BLOCKED` when the task scope, profile, scenario schema, or
runner is unavailable; when a required scenario has no expected behavior or
evidence rule; or when the runner cannot distinguish an agent violation from a
harness failure. Do not broaden scope, edit the schema/runner without explicit
authorization, or claim hardening from an unrun scenario.

Read progressively:

- [skill design guidelines](references/skill-design-guidelines.md)
- [behavioral testing](references/behavioral-testing.md)
- [rationalization hardening](references/rationalization-hardening.md)
