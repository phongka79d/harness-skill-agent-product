# Artifact Contracts

Canonical runtime files:

```text
.agent/runtime/events.jsonl       historical source of truth
.agent/runtime/state.json         generated snapshot
.agent/work/<id>/task-state.json  generated current task state
.agent/work/<id>/checkpoint.json  generated recovery checkpoint
.agent/work/<id>/handoff.json     generated handoff
.agent/work/<id>/review.json      generated review
.agent/work/<id>/lease.json       generated heartbeat lease
.agent/locks/{tasks,files,resources}/*.json  generated ownership locks
.agent/work/<id>/context.json     generated bounded context package
.agent/work/<id>/operations.jsonl generated side-effect operation ledger
.agent/approvals/<target-type>-<target-id>.json generated approval record
.agent/recovery/rollback-plan-<plan-id>.json generated dry-run compensation plan
.agent/recovery/rollback-ledger-<ledger-id>.json generated provider-outcome ledger
.agent/recovery/rollback-evidence-<evidence-id>.json generated rollback evidence
.agent/checklist.md               generated user-facing projection
```

Agents provide payloads. Scripts add timestamps, IDs, revisions, and derived fields, then write atomically.

Batch review artifacts use `.agent/work/<batch-id>/review.json` and are distinct
from task reviews because their directory key is a batch ID.

Updates may include `expected_revision`. The script compares it with the current
artifact revision and rejects stale payloads instead of overwriting newer state.
