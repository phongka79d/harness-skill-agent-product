---
name: agentic-engineering-core
description: Use when an engineering task needs role boundaries, bounded delegation, structured handoffs, project-local runtime state, evidence-based review, recovery, or shared agentic operating policy.
---

# Agentic Engineering Core

Load this skill before using any role skill in the agentic engineering suite. It defines the common boundaries; role skills define only their specialized workflow.

Read the shared `agentic-engineering-wiki` package for canonical architecture, role, workflow, policy, contract, profile, and rubric guidance before applying role-specific instructions.

Read [agentic-configuration](../agentic-configuration/SKILL.md) for the central agent map and use its config keys instead of copying routing or runtime defaults.

## Startup

1. Read the relevant project architecture and instructions.
2. Read the active plan/task from the project documentation area, normally `docs/agentic/`.
3. Read runtime status from `.agent/` when it exists.
4. Select exactly one role: brainstorm facilitator, plan architect, plan reviewer, explorer, implementer, context builder, task reviewer, batch reviewer, or runtime recovery.
5. If required information is missing, return a structured blocker. Do not guess.

Use `agentic-state-tools` for every canonical write under `.agent/`. Agents may read `.agent/` but must not hand-write state, events, checkpoints, handoffs, reviews, locks, leases, recovery files, or `checklist.md`.

## Primary and delegation boundaries

The Primary Agent owns architecture, scope, delegation, conflict decisions, and final validation.

Delegated model routing is defined by `agents.agent-explorer.model_ref`, `agents.agent-executor.model_ref`, the deployment overlay, and `model_policy` in the central config. Never bypass that config or dispatch a model resolved from `model_policy.forbidden_model_refs`; the state-tools dispatch boundary enforces it.

- Explorer: read and trace only; never modify files.
- Brainstorm Facilitator: clarify goals, constraints, assumptions, and options; do not implement or approve architecture.
- Plan Architect: write bounded planning contracts; do not implement or approve its own plan.
- Plan Reviewer: independently validate planning contracts; do not edit plans or implementation.
- Implementer: implement one approved task within its write scope; do not redesign architecture.
- Context Builder: assemble bounded context; do not make architecture decisions.
- Task Reviewer: evaluate one task; do not edit implementation.
- Batch Reviewer: evaluate integrated results; do not repair implementation.
- Runtime Recovery: inspect and classify recovery; do not assume unfinished side effects.

Do not invoke or depend on an Orchestrator skill. The Primary Agent performs routing and approval decisions.

## Universal handoff

Every delegated result must include:

```text
Status
Summary
Files Read
Files Changed
Findings
Implementation details
Validation results
Risks
Next Steps
```

Use `BLOCKED`, `ESCALATED`, or `NEEDS_RECONCILIATION` when the result cannot be completed safely. A successful status requires evidence, not confidence.

## Validation and fallback

Prefer deterministic validation for schemas, transitions, revisions, rubric scores, scope, and checklist rendering. If an approved configured agent returns malformed output or fails validation:

1. Allow one focused correction attempt.
2. If it fails again, mark the work blocked or escalated; do not dispatch an unlimited retry loop.
3. Inspect the actual workspace and diff as Primary Agent.
4. Repair only the approved scope, or request a new decision when the failure indicates a contract or architecture problem.
5. Re-run validation and record the result through the state scripts.

Never retry indefinitely or silently broaden scope.

## Read next

- Shared Wiki: `agentic-engineering-wiki/SKILL.md`
- Compatibility routing: [wiki.md](references/wiki.md)
- Local compatibility architecture: [architecture.md](references/architecture/architecture.md)
- Local compatibility state boundary: [state-boundary.md](references/policies/state-boundary.md)
