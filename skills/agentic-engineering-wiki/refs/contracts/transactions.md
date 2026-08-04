# Transaction Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/runtime_transaction.py`)

Protected multi-file writes use the runtime transaction lifecycle:

```text
PREPARED -> APPLYING -> COMMITTED
                    \-> ROLLED_BACK
                    \-> RECOVERY_PENDING
```

The transaction records operation ID, operation type, idempotency key,
expected revisions, target files, staged files, timestamps, commit or rollback
markers, and evidence hashes. Prepare validates target containment and expected
revisions; applying stages and atomically publishes files; commit verifies the
marker and hashes; rollback preserves evidence. An interruption after APPLYING
does not imply failure: `recover_transactions()` inspects the manifest and real
files, then commits, rolls back, or leaves `RECOVERY_PENDING` when the outcome
is ambiguous.

`record_operation.py` records protected side effects and enforces terminal
operation idempotency. An unfinished or unknown external side effect requires
reconciliation before resume and must not be retried automatically.

The transaction implementation is local filesystem recovery. A distributed
transaction coordinator is NOT_IMPLEMENTED.
