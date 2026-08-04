# Async Execution Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/resolve_execution_mode.py`)

Async is eligible only when configuration enables it, the task is independent,
capacity is available, dependencies are accepted, write scopes do not conflict,
and an isolation proof is verified. The proof binds task ID, run ID, external
worktree path, branch, base commit, plan revision, write-scope hash, conflict
check timestamp, and `isolation_status: VERIFIED`.

`resolve_execution_mode.py --input <task.json> --isolation-proof <proof.json>`
returns an async decision only with that proof. Missing or mismatched proof
causes a safe synchronous decision or a blocked result, according to the
requested mode. Async dispatch persists queue, graph, lease, task, and
operation identity through `dispatch_transaction.py`; run ID, attempt ID,
dispatch ID, revision, and idempotency key remain bound throughout the attempt.

Recovery classifications are `SAFE_TO_RESUME`, `NEEDS_RECONCILIATION`, and
`UNSAFE_TO_RESUME`. Unknown side effects, workspace mismatch, stale identity,
or an invalid ledger require reconciliation or escalation. A merge is
sequential and approval-backed; the Batch Reviewer does not merge.

Multi-machine scheduling, remote lock services, and remote async execution are
NOT_IMPLEMENTED because no release-backed remote implementation exists.
