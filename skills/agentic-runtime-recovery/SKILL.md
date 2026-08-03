---
name: agentic-runtime-recovery
description: Use when a run was interrupted, a heartbeat or lease is stale, a runtime snapshot is corrupt, a terminal closed unexpectedly, or an external side effect has uncertain outcome.
---

# Agentic Runtime Recovery

Read the shared `agentic-engineering-wiki` package before this role's workflow.
Read [agentic-configuration](../agentic-configuration/SKILL.md) before applying recovery, locking, or runtime defaults.

Recover conservatively. Never trust a checkpoint without checking the actual workspace and event history.

## Workflow

1. Read `agentic-engineering-core` and the project recovery policy.
2. Inspect `.agent/runtime/events.jsonl`, `state.json`, task state, leases, locks, checkpoints, operation logs, and actual Git diff.
3. Validate schema and revision consistency with `agentic-state-tools`; inspect operation ledgers before repeating side effects.
4. Detect stale runs and incomplete side effects.
5. Classify recovery as `SAFE_TO_RESUME`, `NEEDS_RECONCILIATION`, or `UNSAFE_TO_RESUME`.
6. Only for `SAFE_TO_RESUME`, create a new run through the state scripts and continue from the validated next action.
7. Escalate reconciliation or unsafe side effects to the Primary Agent/user.
8. Regenerate `state.json` and `.agent/checklist.md` after accepted recovery transitions.

## Hard boundaries

- Do not repeat an operation with uncertain external outcome.
- Do not overwrite state by hand.
- Do not mark a run safe using checkpoint data alone.
- Do not delete active recovery evidence.
- Do not silently convert `NEEDS_RECONCILIATION` to resume.

Read [recovery-model.md](references/recovery-model.md).
