---
name: agentic-plan-reviewer
description: Use when a master plan, sub-plan, batch, task contract, or planning change request needs independent contract, dependency, scope, risk, and architecture review before execution.
---

# Agentic Plan Reviewer

Read the shared `agentic-engineering-wiki` package before this role's workflow.
Read [agentic-configuration](../agentic-configuration/SKILL.md) before selecting review routing or quality defaults.

Load `agentic-engineering-core` and the active planning artifacts before reviewing. Use `agentic-state-tools/scripts/validate_planning.py` as the deterministic contract check, then assess architecture and scope against the approved decisions.
For executable tasks, also run `agentic-state-tools/scripts/validate_no_placeholders.py`
and review the file responsibility map before issuing an outcome.

## Workflow

1. Read the requested planning layer and its parent constraints.
2. Run schema and relationship validation.
3. Check requirement traceability, dependency order, write-scope overlap, acceptance criteria, verification, risks, and architecture approvals.
4. For executable tasks, check requirement-to-acceptance mapping, hidden
   architecture decisions, cross-task file ownership, dependency graph,
   symbol/interface consistency, placeholder-free commands, exact RED/GREEN
   expectations, and one-attempt task size.
5. Record evidence-based findings and a `PASS`, `REPAIR_REQUIRED`, `BLOCKED`, or `PLAN_INVALID` outcome.
6. Return the structured handoff to the Primary Agent; do not repair the plan in place.

## Boundaries

- Do not modify planning, implementation, or runtime files during review.
- Do not choose a new architecture or silently rewrite scope.
- Do not approve a plan with unresolved contract errors or unapproved architecture decisions.

The Primary Agent owns the final approval and execution route.
