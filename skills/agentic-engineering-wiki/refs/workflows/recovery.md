# Recovery Workflow

1. Inspect canonical state, event history, workspace snapshot, checkpoints, leases, locks, and operation ledgers.
2. Compare expected and actual revisions, paths, owner identity, and side-effect status.
3. Persist machine-readable reconciliation evidence for every uncertain or unsafe classification.
4. Resume only after a fresh validated run is authorized and the classification is `SAFE_TO_RESUME`.
5. Prove terminal cleanup; incomplete proof returns `NEEDS_RECONCILIATION`.

Compensation is explicit and separate from resume. Use the rollback planner for
known operation IDs, require the exact `ROLLBACK` approval before execution,
and escalate partial or unknown outcomes instead of retrying them.
