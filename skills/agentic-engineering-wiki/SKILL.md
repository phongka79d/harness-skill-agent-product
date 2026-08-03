---
name: agentic-engineering-wiki
description: Use when an agentic engineering role needs the shared architecture, role, workflow, policy, contract, profile, or rubric source of truth.
---

# Agentic Engineering Wiki

This package is the shared source of truth for the agentic engineering suite. Read the smallest relevant reference before acting. Project plans and decisions remain in `docs/agentic/`; generated runtime state remains in `.agent/`.

Use `agentic-engineering-core` for shared startup, delegation, and validation boundaries; this Wiki owns the detailed routing references.

Read `agentic-configuration/SKILL.md` before selecting models, role capabilities, execution defaults, approvals, or runtime paths.

## Routing

| Need | Read |
|---|---|
| Central agent/model/runtime configuration | `agentic-configuration/SKILL.md` |
| Architecture and workspace boundary | [architecture](refs/architecture/architecture.md), [state boundary](refs/policies/state-boundary.md) |
| Shared role boundaries | [roles](refs/roles/brainstorm-facilitator.md), [plan architect](refs/roles/plan-architect.md), [plan reviewer](refs/roles/plan-reviewer.md), [explorer](refs/roles/explorer.md), [implementer](refs/roles/implementer.md), [context builder](refs/roles/context-builder.md), [task reviewer](refs/roles/task-reviewer.md), [batch reviewer](refs/roles/batch-reviewer.md), [runtime recovery](refs/roles/runtime-recovery.md) |
| Planning workflow | [planning](refs/workflows/planning.md), [planning contract](refs/contracts/planning.md) |
| Execution and dispatch | [execution](refs/workflows/execution.md), [handoff contract](refs/contracts/handoff.md) |
| Review and quality | [review](refs/workflows/review.md), [rubric contract](refs/contracts/rubric.md), [validation policy](refs/policies/validation.md) |
| Recovery and cleanup | [recovery](refs/workflows/recovery.md), [delegation policy](refs/policies/delegation.md) |
| Project profiles | [profiles](refs/profiles/profiles.md) |
| Rubrics | [task rubric](refs/rubrics/task.md), [batch rubric](refs/rubrics/batch.md) |
| Schema index | [schemas](schemas/index.md) |

## Non-negotiable invariants

- The Primary Agent owns architecture, scope, delegation, approval, conflict decisions, and final validation.
- Delegated model routing is limited by `agents.*.model_dispatch` and `model_policy` in the central config; forbidden and unknown models are rejected.
- State changes use `agentic-state-tools`; agents do not hand-write canonical `.agent/` artifacts.
- Unaccepted dependencies are not runnable, and uncertain side effects are not repeated automatically.
- A score never overrides a hard fail, missing evidence, or an unresolved major finding.
- New reviews carry a resolved rubric; only explicitly marked legacy migration artifacts may omit it.
- Plan changes require approval and create a new version linked to the superseded version.
- Do not introduce a standalone Orchestrator unless the governing specification is explicitly amended.

## Validation

Run `python scripts/validate_wiki_links.py --root <wiki-root>` after changing this package.
