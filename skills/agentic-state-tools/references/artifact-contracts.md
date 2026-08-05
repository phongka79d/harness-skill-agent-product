# Artifact Contracts

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/write_artifact.py`)

Canonical runtime files:

```text
.agent/runtime/events.jsonl       historical source of truth
.agent/runtime/state.json         generated snapshot
.agent/work/<id>/task-state.json  generated current task state
.agent/work/<id>/debug-investigation.json generated task-bound repair investigation
.agent/work/<id>/checkpoint.json  generated recovery checkpoint
.agent/work/<id>/handoff.json     generated handoff
.agent/work/<id>/verification/<evidence-id>.json generated task-bound verification evidence
.agent/work/<id>/review.json      generated review
.agent/work/<id>/review-resolution.json generated latest finding resolution
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

Review findings are resolved by `create_review_resolution.py`. The artifact binds the
finding to the current task review and task/run/attempt revision. `CLOSED` is a
reviewer-only state and must retain correction and re-review evidence; implementers
can only reach `FIXED_PENDING_REREVIEW` after passing targeted verification.

`debug-investigation.json` is owned by `create_debug_investigation.py`. It is a
versioned, task/run/attempt-bound evidence artifact. The writer preserves the
investigation identity across revisions, rejects partial or stale updates, and
emits `DEBUG_INVESTIGATION_CREATED` after validation. Repair dispatch and
successful handoff writers consume this artifact; they are not alternate
investigation writers. Passing regression evidence is workspace-bound and is
rejected by the handoff writer when the current workspace hash is different.

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

Task and handoff artifacts bind task, plan, batch, run, attempt, dispatch, and
revision identity. A handoff with the wrong run or attempt is rejected by
`create_handoff.py`; a batch review with a stale contract revision or hash is
rejected at the commit boundary. Schema validation is necessary but not by
itself evidence that an artifact was created through the owning writer.

Verification evidence is owned by `record_verification_evidence.py`. Each
record stores the exact command, exit code, phase, timestamp, content-aware
workspace hash, task/run/attempt/revision identity, and acceptance mapping.
The writer publishes it atomically with a `VERIFICATION_EVIDENCE_RECORDED`
event. `verify_completion_claim.py` recomputes freshness and rejects prior-run,
stale, unmapped, summary-only, skipped, or failed evidence. Legacy handoffs
remain readable as `LEGACY_UNVERIFIED` but cannot satisfy strict production or
high-risk completion gates.
