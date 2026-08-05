---
name: agentic-delivery-finalizer
description: Use when accepted work needs a controlled delivery outcome, final verification, approval-backed merge, or identity-proven branch/worktree cleanup.
---

# Agentic Delivery Finalizer

Read [agentic-engineering-core](../agentic-engineering-core/SKILL.md),
[agentic-state-tools](../agentic-state-tools/SKILL.md), and the shared
[authorization contract](../agentic-engineering-wiki/refs/contracts/authorization.md)
before finalizing delivery. Use the [delivery outcomes](references/delivery-outcomes.md)
and [merge and cleanup safety](references/merge-and-cleanup-safety.md) references
for the controlled decision and evidence requirements.

## Workflow

1. Confirm accepted task and batch reviews, the current workspace identity, and fresh final-verification evidence.
2. Select exactly one supported delivery outcome; do not invent a fallback outcome.
3. Persist the decision, hashes, approval evidence, and intended cleanup state through `agentic-state-tools` before any merge, push, or cleanup side effect.
4. Execute only the approved state-tool operation and read back its result.
5. Re-verify the merged target when the outcome is `MERGE_LOCAL`; preserve the worktree for review when the outcome is `PUSH_AND_CREATE_PR`.
6. Clean up only when the outcome and typed approval permit it and Harness ownership is proven by identity.

Conflicts, missing or stale verification, mismatched identity, and missing
approval produce `BLOCKED` or `NEEDS_RECONCILIATION`. The finalizer does not
repair conflicts or run uncontrolled Git commands. The Batch Reviewer reviews
integration and delivery readiness but never performs the merge.
