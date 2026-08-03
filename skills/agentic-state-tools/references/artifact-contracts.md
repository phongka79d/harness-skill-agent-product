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
.agent/work/<batch-id>/batch-contract.json generated approval-bound batch contract
.agent/approvals/<target-type>-<target-id>.json generated approval record
.agent/recovery/rollback-plan-<plan-id>.json generated dry-run compensation plan
.agent/recovery/rollback-ledger-<ledger-id>.json generated provider-outcome ledger
.agent/recovery/rollback-evidence-<evidence-id>.json generated rollback evidence
.agent/checklist.md               generated user-facing projection
```

Agents provide payloads. Scripts add timestamps, IDs, revisions, and derived fields, then write atomically.

Batch contracts are canonical, approval-bound pins of the approved plan, exact
batch membership, task revisions, and review contracts. Create or replace one
with `scripts/create_batch_contract.py` and an explicit expected revision; do
not write `batch-contract.json` directly. Legacy migration reviews may consume
explicitly marked legacy evidence, but new batch reviews require the generated
schema-valid contract and its current plan approval.

Batch review artifacts use `.agent/work/<batch-id>/review.json` and are distinct
from task reviews because their directory key is a batch ID.

Updates may include `expected_revision`. The script compares it with the current
artifact revision and rejects stale payloads instead of overwriting newer state.
