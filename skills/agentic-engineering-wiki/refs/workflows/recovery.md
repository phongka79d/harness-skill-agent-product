# Recovery Workflow

1. Inspect canonical state, event history, workspace snapshot, checkpoints, leases, locks, and operation ledgers.
2. Compare expected and actual revisions, paths, owner identity, and side-effect status.
3. Persist machine-readable reconciliation evidence for every uncertain or unsafe classification.
4. Resume only after a fresh validated run is authorized and the classification is `SAFE_TO_RESUME`.
5. Prove terminal cleanup; incomplete proof returns `NEEDS_RECONCILIATION`.

Product or code debugging is owned by [agentic-systematic-debugging](../../../agentic-systematic-debugging/SKILL.md). It does not decide whether an interrupted run, stale lease, corrupt runtime state, or uncertain external side effect is safe to resume; those decisions belong to [agentic-runtime-recovery](../../../agentic-runtime-recovery/SKILL.md).

Compensation is explicit and separate from resume. Use the rollback planner for
known operation IDs, require the exact `ROLLBACK` approval before execution,
and escalate partial or unknown outcomes instead of retrying them.

For baseline, worktree, or delivery-identity uncertainty, route to the [execution modes contract](../contracts/async-execution.md) and [delivery safety](../../../agentic-delivery-finalizer/references/merge-and-cleanup-safety.md) before resuming or cleaning up.
