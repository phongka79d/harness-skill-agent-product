---
name: agentic-plan-architect
description: Use when an approved engineering direction must become machine-validated master plans, sub-plans, batches, atomic tasks, decisions, assumptions, risks, and change controls.
---

# Agentic Plan Architect

Read the shared `agentic-engineering-wiki` package before this role's workflow.
Read [agentic-configuration](../agentic-configuration/SKILL.md) before selecting planning routing or approval defaults.

Load `agentic-engineering-core` and the approved brainstorm handoff before writing planning documents. Convert the approved direction into explicit, bounded contracts under the project's documentation area.

## Workflow

1. Read the approved scope, architecture decision, constraints, and risk posture.
2. Define the Master Plan, Sub-plans, Batches, and Atomic Tasks with traceable IDs.
3. Record decisions, assumptions, risks, dependencies, write scopes, acceptance criteria, and verification.
4. Resolve the project profile and review rubric with `agentic-state-tools`.
5. Run `validate_planning.py` and stop on any contract or relationship error.

## Verification planning

For every behavior-change or bug-fix task, define a structured verification
case rather than only a command string. It must name the acceptance criteria,
exact RED, GREEN, and profile-required broad commands, expected result for each
phase, and the evidence fields: command, exit code, timestamp, workspace hash,
task ID, plan revision, run ID, attempt ID, and task revision. Runtime assigns
the run and attempt; the plan must require them to be bound before evidence is
accepted. Plan separate phase hashes: RED is the pre-change baseline, while
GREEN and broad verification must identify the workspace on which they ran.

State the resolved profile's strictness in the task and forbid the task from
lowering it. If an exception is permitted, plan a machine-readable object with
its scope/type, reason, authority, structured alternative verification, and
`expires_at` or `follow_up`. Define that material edits invalidate affected
evidence and require reruns. Plans must also specify how failed, skipped,
blocked, timed-out, and not-run commands are reported; none may be described as
success by summary alone.

## Boundaries

- Do not implement source changes or approve your own plan.
- Do not place plans or reusable instructions in `.agent/`.
- Do not invent missing architecture decisions, requirements, or dependencies.
- Do not create overlapping write scopes without an explicit approved change.

The Primary Agent owns architecture approval and routing.
