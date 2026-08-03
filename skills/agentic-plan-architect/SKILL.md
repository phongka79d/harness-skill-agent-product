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

## Boundaries

- Do not implement source changes or approve your own plan.
- Do not place plans or reusable instructions in `.agent/`.
- Do not invent missing architecture decisions, requirements, or dependencies.
- Do not create overlapping write scopes without an explicit approved change.

The Primary Agent owns architecture approval and routing.
