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
| Skill authoring and behavioral pressure tests | [skill authoring](../agentic-skill-authoring/SKILL.md), [behavioral testing](../agentic-skill-authoring/references/behavioral-testing.md) |
| Bounded context and attempt lineage | [context builder](../agentic-context-builder/SKILL.md), [context contract](../agentic-context-builder/references/context-contract.md) |
| Planning workflow | [planning](refs/workflows/planning.md), [planning contract](refs/contracts/planning.md) |
| Execution and dispatch | [execution](refs/workflows/execution.md), [handoff contract](refs/contracts/handoff.md) |
| Deterministic skill routing | `agentic-engineering-core/references/policies/skill-routing.md`, `agentic-state-tools/scripts/resolve_skill_route.py` |
| Product/code debugging symptoms | `agentic-systematic-debugging` for evidence-first root-cause investigation |
| Completion, readiness, merge, or release claims | `agentic-verification-before-completion` for fresh evidence and claim mapping |
| Testing and fresh completion evidence | [testing contract](refs/contracts/testing.md), [verification gate](../agentic-verification-before-completion/SKILL.md) |
| Review and quality | [review](refs/workflows/review.md), [rubric contract](refs/contracts/rubric.md), [validation policy](refs/policies/validation.md) |
| Staged review and feedback resolution | [review contract](../agentic-task-reviewer/references/review-contract.md), [feedback resolution](../agentic-implementer/references/review-feedback-resolution.md) |
| Interrupted runtime state or uncertain side effects | `agentic-runtime-recovery`; do not use product debugging to decide resume safety |
| Recovery and cleanup | [recovery](refs/workflows/recovery.md), [delegation policy](refs/policies/delegation.md) |
| Execution modes and read-only isolation | [execution modes](refs/contracts/async-execution.md), [exploration protocol](../agentic-explorer/references/exploration-protocol.md) |
| Workspace baseline and isolated worktree proof | [baseline capture](../agentic-state-tools/scripts/capture_workspace_baseline.py), [baseline schema](../agentic-state-tools/schemas/workspace-baseline.schema.json) |
| Delivery outcome and cleanup | [delivery finalizer](../agentic-delivery-finalizer/SKILL.md), [delivery outcomes](../agentic-delivery-finalizer/references/delivery-outcomes.md) |
| Project profiles | [profiles](refs/profiles/profiles.md) |
| Rubrics | [task rubric](refs/rubrics/task.md), [batch rubric](refs/rubrics/batch.md) |
| Schema index | [schemas](schemas/index.md) |

## Non-negotiable invariants

- The Primary Agent owns architecture, scope, delegation, approval, conflict decisions, and final validation.
- Delegated model routing is limited by `agents.*.model_ref`, the deployment overlay, and `model_policy` in the central config; forbidden and unknown refs are rejected.
- Dispatch skill routing resolves process -> role -> domain precedence and cannot omit a mandatory process skill. The probabilistic “1% chance” rule is explicitly disabled.
- State changes use `agentic-state-tools`; agents do not hand-write canonical `.agent/` artifacts.
- Product/code defects route through `agentic-systematic-debugging`; interrupted runs and uncertain side effects route through `agentic-runtime-recovery`.
- Positive completion claims route through `agentic-verification-before-completion`; summaries, prior-run results, and stale evidence are not proof.
- Isolated writes require an identity-bound workspace baseline; delivery and cleanup use one persisted, approval-backed finalizer outcome.
- Unaccepted dependencies are not runnable, and uncertain side effects are not repeated automatically.
- A score never overrides a hard fail, missing evidence, or an unresolved major finding.
- New reviews carry a resolved rubric; only explicitly marked legacy migration artifacts may omit it.
- Plan changes require approval and create a new version linked to the superseded version.
- Do not introduce a standalone Orchestrator unless the governing specification is explicitly amended.

## Validation

Run `python scripts/validate_wiki_links.py --root <wiki-root>` after changing this package.
