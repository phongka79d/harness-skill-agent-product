# Agent Skills Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the agent skill package enforce the attached runtime, planning, review, async, recovery, authorization, security, testing, packaging, and documentation contracts from planning through release.

**Architecture:** Keep `skills/agentic-state-tools` as the only writer of project-local `.agent/` artifacts. Add one task-state merge contract, one canonical batch-contract writer, one transaction framework, one state-transition registry, one risk-flag vocabulary, and one authorization boundary. Existing plans in `docs/superpowers/plans/` remain reusable workstream baselines; this plan closes their remaining declared-versus-enforced gaps and sequences the work into independently testable phases.

**Tech Stack:** Python 3 standard library, the repository's JSON Schema subset validator, JSON-compatible YAML configuration, `unittest`, subprocess-based CLI tests, Git worktree inspection, atomic filesystem writes, JSONL event and operation journals, and deterministic ZIP packaging.

---

## Scope and baseline

The attached specification is broader than one small change, so execution follows its six requirements phases and is decomposed into nine independently testable tasks. The current repository already contains related plans for configuration, planning/risk, async worktrees, authorization, recovery, review integrity, context security, and package hardening. Those plans are treated as existing implementation context, not as proof that the attached requirements are enforced.

Baseline observed before implementation:

- `python run_tests.py` passes 188 tests across 11 groups.
- `update_task_state.py` writes the submitted payload as the next document and therefore can drop dispatch/runtime identity.
- No official `create_batch_contract.py` exists; normal tests write `batch-contract.json` directly.
- `validate_planning.py` validates only one direction for several relationships and rejects every overlapping write scope, including dependency-ordered work.
- `resolve_execution_mode.py` uses the old boolean execution configuration and accepts only `auto`, `async`, and `sync`.
- `merge_worktree.py` accepts `--authorized` instead of a persisted approval artifact.
- `state-machine.json` is consumed as the source and currently permits executor `COMPLETED -> ACCEPTED`; `ARCHIVED` has no reachable cleanup transition.
- `package_skill.py` excludes tests and the top-level `run_tests.py`, while the requested release allowlist includes both.

The implementation must preserve the current filesystem backend, Primary-controlled architecture, provider-neutral model references, and existing CLI behavior where the new contract does not require a rejection.

The attached specification uses `state-tools/...` as a shorthand. In this repository the concrete package root is `skills/agentic-state-tools/`, and importable runtime modules belong under `skills/agentic-state-tools/scripts/`; the file map below uses those actual paths.

**Progress checkpoint (2026-08-04):** Tasks 1–5 are complete. Task 9 Step 1 has been validated through the focused gates. Tasks 6–8 and the remaining Task 9 steps stay open until their missing registry, manifest, redaction, documentation, archive, and report deliverables are implemented.

## File map

| Responsibility | Files | Boundary |
| --- | --- | --- |
| Task identity-preserving transitions | Create `skills/agentic-state-tools/scripts/task_state_contract.py`; modify `skills/agentic-state-tools/scripts/update_task_state.py`, `skills/agentic-state-tools/scripts/create_handoff.py`, `skills/agentic-state-tools/scripts/dispatch_transaction.py`, `skills/agentic-state-tools/scripts/reconcile_queue.py`, `skills/agentic-state-tools/scripts/inspect_recovery.py`, `skills/agentic-state-tools/schemas/task-state.schema.json`; test in `skills/agentic-state-tools/tests/test_contract_hardening.py` | Mutable executor updates cannot replace immutable execution identity. Retry/rebind is a separate operation. |
| Canonical batch contract | Create `skills/agentic-state-tools/scripts/create_batch_contract.py`, `skills/agentic-state-tools/schemas/batch-contract.schema.json`; modify `skills/agentic-state-tools/scripts/create_batch_review.py`, `skills/agentic-state-tools/SKILL.md`; test in `skills/agentic-state-tools/tests/test_contract_hardening.py` and `skills/agentic-state-tools/tests/test_v1_workflow.py` | Only the official writer may create or replace `.agent/work/B-1/batch-contract.json` for a concrete batch instance. |
| Planning and risk contracts | Create `skills/agentic-state-tools/scripts/risk_flags.py`, `skills/agentic-state-tools/schemas/risk-flags.schema.json`; modify `planning-task.schema.json`, `planning-batch.schema.json`, `sub-plan.schema.json`, `review-contract.schema.json`, `task-state.schema.json`, `change-request.schema.json`, `validate_planning.py`, `detect_scope_overlap.py`, `resolve_rubric.py`, `review_contract.py`, `dispatch_task.py`; test in `skills/agentic-state-tools/tests/test_contract_hardening.py` and `skills/agentic-state-tools/tests/test_adaptive_quality.py` | Every owner, review pin, reverse membership, requirement trace, scope classification, and risk flag is machine-validated. |
| Async execution and merge fencing | Modify `skills/agentic-configuration/config/agentic-config.yaml`, `skills/agentic-configuration/schemas/agentic-config.schema.json`, `skills/agentic-configuration/tests/test_config.py`, `resolve_execution_mode.py`, `dispatch_transaction.py`, `queue.schema.json`, `graph.schema.json`, `worktree.schema.json`, `worktree_manager.py`, `merge_worktree.py`, `authorization.py`; create `isolation-proof.schema.json`; test in `test_orchestration.py`, `test_distributed_state.py`, and `test_recovery_hardening.py` | Async is opt-in by evidence, sync is the default, and merge always requires typed approval. |
| Multi-file transaction and recovery | Create `skills/agentic-state-tools/scripts/runtime_transaction.py`, `skills/agentic-state-tools/schemas/transaction.schema.json`; modify `operation.schema.json`, `runtime_utils.py`, `init_runtime.py`, `dispatch_transaction.py`, `update_task_state.py`, `create_review.py`, `create_batch_review.py`, `record_approval.py`, `apply_change_request.py`, `record_operation.py`, `inspect_recovery.py`, `commit_batch.py`, `merge_worktree.py`; test in `test_transaction_recovery.py` and `test_v1_workflow.py` | All listed local mutations use prepared/staged/committed or rolled-back transactions with idempotency and restart reconciliation. |
| Change request, state, and authorization consistency | Create `skills/agentic-state-tools/scripts/state_transition_registry.py`; modify `state_machine.py`, `state-machine.json`, `generate_state_artifacts.py`, `validate_state_machine.py`, `validate_transition.py`, `validate_change_request.py`, `apply_change_request.py`, `authorization.py`, `record_approval.py`, and their schemas; test in `test_transition_registry.py`, `test_adaptive_quality.py`, `test_authorization.py`, `test_rollback.py` | One transition registry and one approval validator govern every sensitive operation. |
| Context, release runner, package, and docs | Modify `secret_scanner.py`, `create_context.py`, `append_event.py`, `record_operation.py`, `run_tests.py`, `package_skill.py`, `test_release_runner.py`, `test_packaging.py`, and the relevant Wiki/role contract references; create `MANIFEST.txt` and `docs/release-report-template.md`; add grouped tests under `tests/` during Task 8 | Release output is allowlisted, examples execute through scripts, and documentation states whether each policy is enforced. |

## Dependency order

```text
Task 1 runtime identity
  -> Task 2 canonical batch contract
  -> Task 3 planning and risk integrity
  -> Task 4 safe async opt-in and approval-backed merge
  -> Task 5 transaction framework and crash recovery
  -> Task 6 change requests, transition registry, and authorization unification
  -> Task 7 context security, release runner, and package allowlist
  -> Task 9 integrated release gate and implementation report
```

Task 1 can be implemented independently. Tasks 2 and 3 may be developed in separate worktrees after Task 1, but Task 4 consumes both. Task 5 may start after the artifact schemas are frozen, but its migration checklist must be completed before Task 8. Task 6 depends on the transaction API and is the prerequisite for enabling any protected merge or next-batch action.

### Task 1: Preserve task execution identity across transitions

**Files:**
- Create: `skills/agentic-state-tools/scripts/task_state_contract.py`
- Create: `skills/agentic-state-tools/scripts/reissue_task_attempt.py`
- Modify: `skills/agentic-state-tools/scripts/update_task_state.py`
- Modify: `skills/agentic-state-tools/scripts/create_handoff.py`
- Modify: `skills/agentic-state-tools/scripts/dispatch_transaction.py`
- Modify: `skills/agentic-state-tools/scripts/reconcile_queue.py`
- Modify: `skills/agentic-state-tools/scripts/inspect_recovery.py`
- Modify: `skills/agentic-state-tools/schemas/task-state.schema.json`
- Create: `skills/agentic-state-tools/schemas/attempt-reissue.schema.json`
- Test: `skills/agentic-state-tools/tests/test_contract_hardening.py`
- Test: `skills/agentic-state-tools/tests/test_state_tools.py`

- [x] **Step 1: Add the failing identity regression tests.**

Add tests that initialize a runtime, persist a task with the following identity, and then submit only a mutable transition payload:

```python
identity = {
    "task_id": "T-ID-1",
    "plan_id": "MP-1",
    "plan_revision": 4,
    "batch_id": "B-1",
    "requirement_ids": ["REQ-1"],
    "depends_on": [],
    "read_scope": ["src/"],
    "write_scope": ["src/app.py"],
    "review_contract": {
        "project_profile": "production",
        "profile_hash": "b" * 64,
        "task_type": "backend",
        "risk_flags": {},
        "review_type": "task",
        "rubric_id": "R-1",
        "rubric_version": "1",
        "rubric_hash": "a" * 64,
        "review_policy_version": "1",
    },
    "run_id": "RUN-1",
    "attempt_id": "ATTEMPT-1",
    "dispatch_id": "DISPATCH-1",
    "worktree_path": "C:/work/T-ID-1",
    "branch_name": "agent/T-ID-1-r4",
    "input_artifact_hashes": {"plan": "b" * 64},
}
```

The `QUEUED -> RUNNING -> COMPLETED` transitions must retain every identity field and update only `status`, generated revision/timestamps, checkpoint/progress/result/error fields, and output hashes. Add separate assertions that a changed `run_id`, `attempt_id`, `dispatch_id`, `plan_revision`, `write_scope`, or input hash returns `TASK_STATE_REJECTED` and leaves the previous JSON byte-for-byte unchanged. Add wrong-run and wrong-attempt handoff cases and assert `HANDOFF_REJECTED`.

- [x] **Step 2: Run the focused tests and verify the expected failures.**

Run:

```text
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_contract_hardening.py" -v
```

Expected: FAIL because the current state update replaces the document with the submitted payload and does not reject immutable-field changes.

- [x] **Step 3: Implement the task-state merge contract.**

Define these exact constants and APIs in `task_state_contract.py`:

```python
IMMUTABLE_FIELDS = frozenset({
    "task_id", "plan_id", "plan_revision", "batch_id", "requirement_ids",
    "depends_on", "read_scope", "write_scope", "review_contract", "run_id",
    "attempt_id", "dispatch_id", "worktree_path", "branch_name",
    "input_artifact_hashes",
})
MUTABLE_FIELDS = frozenset({
    "status", "progress", "checkpoint", "error", "blocker", "result_summary",
    "output_artifact_hashes", "review_verdict", "updated_at", "revision",
    "previous_revision",
})

def merge_task_state(current: dict[str, object] | None, update: dict[str, object]) -> dict[str, object]:
    """Return a full next state while rejecting identity changes."""

def validate_execution_identity(state: dict[str, object], lease: dict[str, object] | None, queue: dict[str, object] | None) -> None:
    """Reject a state whose run, attempt, or dispatch binding disagrees with durable evidence."""
```

`merge_task_state` must copy `current` first, compare every immutable field present in both documents, reject a submitted immutable value that differs, apply only `MUTABLE_FIELDS`, and generate `revision`, `previous_revision`, and `updated_at` in the caller. Preserve descriptive task fields already stored in `current`; do not construct a new state from the update payload alone.

- [x] **Step 4: Route update, dispatch, handoff, and recovery through the helper.**

Change `update_task_state.py` to read the current state before validating the transition, call `merge_task_state`, then validate the resulting full state. After writing, call `validate_execution_identity` against the current lease and queue/dispatch entry. Change `dispatch_transaction.py` to include `dispatch_id`, worktree metadata, input hashes, and `plan_revision` in task, queue, lease, and dispatch records. Change `create_handoff.py`, `reconcile_queue.py`, and `inspect_recovery.py` to compare all three IDs (`run_id`, `attempt_id`, `dispatch_id`) and report a mismatch instead of treating the task as resumable.

- [x] **Step 5: Isolate retry/reissue identity changes.**

Implement `reissue_task_attempt.py` with an `--expected-revision` guard and a payload schema containing `task_id`, `reason`, `new_run_id`, `new_attempt_id`, and `new_dispatch_id`. It must run under the runtime lock, require the current task to be `REPAIR_REQUIRED`, `STALE`, or `RECOVERY_PENDING`, append a `REISSUE_TASK_ATTEMPT` operation record, update all queue/lease/dispatch bindings together, and emit the reissue event. `update_task_state.py` must reject attempts to change these fields directly.

- [x] **Step 6: Run identity validation.**

Run:

```text
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_contract_hardening.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_state_tools.py" -v
```

Expected: all focused identity, handoff, lease, queue, and recovery tests pass, including `QUEUED -> RUNNING -> COMPLETED` identity retention.

### Task 2: Add the canonical Batch Contract Writer

**Files:**
- Create: `skills/agentic-state-tools/scripts/create_batch_contract.py`
- Create: `skills/agentic-state-tools/schemas/batch-contract.schema.json`
- Modify: `skills/agentic-state-tools/scripts/create_batch_review.py`
- Modify: `skills/agentic-state-tools/scripts/commit_batch.py`
- Modify: `skills/agentic-state-tools/scripts/authorization.py`
- Modify: `skills/agentic-state-tools/schemas/batch-review.schema.json`
- Modify: `skills/agentic-state-tools/schemas/event.schema.json`
- Modify: `skills/agentic-state-tools/schemas/state-machine.json`
- Modify: `skills/agentic-state-tools/scripts/record_approval.py`
- Modify: `skills/agentic-state-tools/scripts/apply_change_request.py`
- Modify: `skills/agentic-state-tools/SKILL.md`
- Modify: `skills/agentic-state-tools/references/artifact-contracts.md`
- Modify: `skills/agentic-state-tools/tests/test_state_tools.py`
- Modify: `skills/agentic-state-tools/tests/test_v1_workflow.py`
- Test: `skills/agentic-state-tools/tests/test_contract_hardening.py`

- [x] **Step 1: Add failing writer and reviewer tests.**

Create an approved planning bundle and approval artifact in each temporary test project, then assert that:

- `create_batch_contract.py` creates `.agent/work/B-1/batch-contract.json` with plan ID/revision/hash, approval ID, batch revision, exact task pins, task review-contract hashes, batch rubric ID/version/hash, a contract hash, and a revision.
- A missing task, duplicate task, task assigned to another batch, task omitted from the batch's reverse membership, stale plan revision, stale approval, or changed expected contract revision is rejected.
- Rebuilding after a plan revision changes the contract hash and rejects the old approval/old batch review.
- Normal test setup invokes the script; no normal workflow test calls `write_text()` for `batch-contract.json`.

Use the official CLI in the test fixture:

```text
python skills/agentic-state-tools/scripts/create_batch_contract.py --project-root C:\Temp\agent-skills-plan-fixture --plan C:\Temp\agent-skills-approved-plan.json --plan-id MP-1 --plan-revision 4 --batch-id B-1 --expected-revision 0
```

Expected before implementation: `CREATE_BATCH_CONTRACT_REJECTED` because the script and schema do not exist.

- [x] **Step 2: Define the canonical contract shape.**

Create `batch-contract.schema.json` with these required top-level fields:

```json
{
  "schema_version": 1,
  "contract_id": "BATCH-CONTRACT-B-1-R4",
  "plan_id": "MP-1",
  "plan_revision": 4,
  "plan_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "plan_approval_id": "APR-MASTER-PLAN-MP-1-1",
  "batch_id": "B-1",
  "batch_revision": 2,
  "tasks": [
    {
      "task_id": "T-1",
      "task_revision": 3,
      "review_contract_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "rubric_id": "TASK_REVIEW_BACKEND_PRODUCTION_V1",
      "rubric_version": "1.0.0",
      "rubric_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    }
  ],
  "review_contract": {
    "project_profile": "production",
    "profile_hash": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    "task_type": "batch",
    "risk_flags": {},
    "review_type": "batch",
    "rubric_id": "BATCH_REVIEW_STANDARD_PRODUCTION_V1",
    "rubric_version": "1.0.0",
    "rubric_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "review_policy_version": "1"
  },
  "rubric_id": "BATCH_REVIEW_STANDARD_PRODUCTION_V1",
  "rubric_version": "1.0.0",
  "rubric_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "revision": 1,
  "previous_revision": null,
  "created_at": "2026-08-03T00:00:00Z",
  "contract_hash": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
}
```

Require unique task IDs, SHA-256 hash patterns, non-negative `previous_revision`, and `additionalProperties: false` for pin objects. Compute `plan_hash` and `contract_hash` from canonical JSON with the hash field removed.

- [x] **Step 3: Implement the writer as the only batch-contract producer.**

`create_batch_contract.py` must accept `--project-root`, `--plan`, `--plan-id`, `--plan-revision`, `--batch-id`, `--expected-revision`, and `--actor`. It must validate the plan ID/revision, verify the matching persisted `MASTER_PLAN` approval through `authorization.py`, resolve the batch and every task from the approved plan, enforce complete task-to-batch and batch-to-sub-plan membership in both directions (including rejecting omitted or nonexistent sibling batch IDs), read current task states, and pin the exact revisions and rubric identities. It must acquire `runtime_lock`, validate the expected existing contract revision, write through `write_validated`, append the registered `BATCH_CONTRACT_CREATED` event, and record a `CREATE_BATCH_CONTRACT` operation with the contract hash. The event schema and state-machine event registry are part of this task because they define that canonical event.

Use this writer API so tests and future workflows have one entry point:

```python
def create_batch_contract(
    project_root: str | Path,
    approved_plan: dict[str, object],
    *,
    plan_id: str,
    plan_revision: int,
    batch_id: str,
    actor: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    """Validate, pin, persist, and journal one canonical batch contract."""
```

- [x] **Step 4: Make Batch Reviewer and commit authorization consume only the generated contract.**

Replace the permissive `load_batch_contract` path in `create_batch_review.py` with schema validation, `contract_hash` verification, plan approval validation, task-state schema/identity validation, task-pin comparison, and canonical review-path binding (`work/<task_id>/review.json`). Require exact task-set equality and exact current task/review-contract/rubric revisions. Store the current batch-contract revision and hash in each non-legacy batch review. Make `commit_batch.py` schema-validate and recompute the current batch-review artifact hash, re-derive its verdict from current task reviews and integration evidence, compare its embedded review contract with the current canonical contract, then reload the current contract and reject a missing or stale review pin before authorizing a PASS commit. A rehashed review with semantically failing evidence must remain rejected. If the plan or any task pin changes, return `BATCH_REVIEW_REJECTED` and never derive `PASS` from the stale contract.

- [x] **Step 5: Remove normal direct contract writes from fixtures and examples.**

Replace the direct writes at the batch-contract setup sites in `test_state_tools.py` and `test_v1_workflow.py` with the official CLI. Keep direct writes only in tests explicitly named as tampering/malformed-artifact tests, and assert those artifacts are rejected by the reviewer. Add `create_batch_contract.py` to `agentic-state-tools/SKILL.md` and `references/artifact-contracts.md`.

When `apply_change_request.py` creates a new plan revision, synchronize both the top-level plan revision and `master_plan.revision`; otherwise the new approval-bound contract cannot be rebuilt. Add `MASTER_PLAN` to the shared authorization policy map and call `authorize()` from the batch-contract writer with the typed actor identity and exact plan target.

- [x] **Step 6: Run the batch contract gate.**

Run:

```text
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_contract_hardening.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_state_tools.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_v1_workflow.py" -v
```

Expected: all writer, membership, revision, hash invalidation, and reviewer completeness tests pass.

> **Progress checkpoint (2026-08-03):** Task 1 is complete and committed as `af9e16a`. Task 2 is complete and committed as `21a1cf0`; focused gates pass (`32/32`, `44/44`, `3/3`) and the current release runner passes (`222` tests, zero failures/timeouts). Quality-review findings were repaired, including loader path validation and a successful CLI commit regression test. Task 3 is now in progress.

### Task 3: Complete planning integrity and risk normalization

**Files:**
- Create: `skills/agentic-state-tools/scripts/risk_flags.py`
- Create: `skills/agentic-state-tools/schemas/risk-flags.schema.json`
- Modify: `skills/agentic-state-tools/schemas/planning-task.schema.json`
- Modify: `skills/agentic-state-tools/schemas/planning-batch.schema.json`
- Modify: `skills/agentic-state-tools/schemas/sub-plan.schema.json`
- Modify: `skills/agentic-state-tools/schemas/review-contract.schema.json`
- Modify: `skills/agentic-state-tools/schemas/task-state.schema.json`
- Modify: `skills/agentic-state-tools/schemas/change-request.schema.json`
- Modify: `skills/agentic-state-tools/scripts/validate_planning.py`
- Modify: `skills/agentic-state-tools/scripts/detect_scope_overlap.py`
- Modify: `skills/agentic-state-tools/scripts/resolve_rubric.py`
- Modify: `skills/agentic-state-tools/scripts/review_contract.py`
- Modify: `skills/agentic-state-tools/scripts/dispatch_task.py`
- Modify: `skills/agentic-state-tools/tests/test_adaptive_quality.py`
- Test: `skills/agentic-state-tools/tests/test_contract_hardening.py`

- [x] **Step 1: Add failing planning tests.**

Add cases for missing owner, unknown owner, owner without the task capability, missing pinned review contract on an approved task, missing reverse task/batch membership, duplicate task membership, missing reverse batch/sub-plan membership, duplicate and unknown requirement IDs, a deprecated requirement referenced by a task, an untraced acceptance criterion, dependency-ordered scope overlap, unapproved shared writes, and read-only overlap.

Use structured acceptance criteria in new fixtures:

```json
{
  "criterion_id": "AC-1",
  "text": "The runtime retains execution identity.",
  "requirement_ids": ["REQ-1"]
}
```

Expected before implementation: each newly covered invalid bundle exits non-zero with a `PLANNING_INVALID:` reason, while the dependency-ordered overlap fixture remains valid.

- [x] **Step 2: Add the closed risk-flag contract.**

Define the exact allowed keys in `risk_flags.py` and the schema:

```python
RISK_FLAG_KEYS = frozenset({
    "authentication", "authorization", "database", "schema_migration",
    "destructive_operation", "deployment", "security_sensitive", "external_api",
    "payments", "personal_data", "concurrency", "shared_state", "infrastructure",
})

def normalize_risk_flags(value: object) -> dict[str, bool]:
    """Return sorted canonical flags or raise for unknown/non-boolean input."""
```

The schema must use `additionalProperties: false` and boolean values. `resolve_rubric.py`, `review_contract.py`, planning validation, dispatch, change requests, and task state must import this helper/schema instead of maintaining separate vocabularies. Update rubric profiles and examples to the canonical keys; do not silently map misspellings.

- [x] **Step 3: Enforce owner, review, membership, and requirement traceability.**

Require `owner` in `planning-task.schema.json`. Resolve owner names against the central config's `agents` registry, accepting the canonical agent IDs plus these documented role aliases: `implementer` -> `agent-executor`, `task-reviewer` -> `agent-review`, `batch-reviewer` -> `agent-batch-review`, `runtime-recovery` -> `agent-runtime-recovery`. Map task types to capabilities already present in the config (`backend_change`, `frontend_change`, `data_change`, `infrastructure`, and `documentation` -> `repository_editing`; `testing` -> `testing`; `review` -> `evidence_review`). Reject an owner that is absent or forbidden from the requested type. When the bundle is approved, require a fully pinned review contract and reject dispatch if the task state does not contain it.

Build reverse indexes before relationship checks:

```python
batch_to_tasks = {batch_id: set(batch.get("tasks", [])) for batch_id, batch in batches_by_id.items()}
task_to_batch = {task["task_id"]: task.get("batch_id") for task in tasks}
subplan_to_batches = {sub_id: set(plan.get("batches", [])) for sub_id, plan in subplans_by_id.items()}
```

Require equality in both directions, one batch per task, one sub-plan per batch, unique requirement IDs, known non-deprecated requirements, non-empty task `requirement_ids`, and at least one task/acceptance criterion trace for every active requirement. Emit a deterministic requirement report with columns `Requirement`, `Tasks`, `Acceptance criteria`, and `Status`.

- [x] **Step 4: Classify write scopes by dependency reachability.**

Add a `has_dependency_path(left, right, task_edges)` helper. For overlapping write scopes, return `CONFLICT` when neither task depends transitively on the other and both could be active; return `SEQUENTIAL_OVERLAP` when one is ordered after the other; return `APPROVED_SHARED_WRITE` only when both tasks share the same `shared_write_group`, use `SYNC`, and reference a persisted approval; and ignore read-only intersections. Make `detect_scope_overlap.py` emit the classification and make `validate_planning.py` reject only `CONFLICT` or an invalid shared-write approval.

- [x] **Step 5: Run planning and rubric validation.**

Run:

```text
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_contract_hardening.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_adaptive_quality.py" -v
python skills/agentic-state-tools/scripts/validate_planning.py --input skills/agentic-state-tools/examples/v1-planning-bundle.json
```

Expected: all invalid bundles fail with deterministic reasons, the release planning example prints `PLANNING_VALID`, and risk-sensitive rubric resolution uses the same normalized flag object and hash at every consumer.

**Task 3 checkpoint — 2026-08-04:** Completed in commits `7c5f0bb` and `bc56178`. Added the canonical risk-flag contract, owner/capability validation, bidirectional planning membership, requirement traceability/reporting, dependency-aware scope classification, schema-valid persisted shared-write approvals, dispatch review-contract pinning, nested risk validation, and structured acceptance criteria. Fresh `python run_tests.py` passed 242/242 tests with 0 failures and 0 timeouts; `validate_planning.py --requirements-report` returned `PLANNING_VALID`; `load_config.py --check` returned `CONFIG_VALID`. Remaining work begins at Task 4 and is intentionally not started in this checkpoint.

### Task 4: Implement safe-by-default async execution and approval-backed merge

**Files:**
- Modify: `skills/agentic-configuration/config/agentic-config.yaml`
- Modify: `skills/agentic-configuration/schemas/agentic-config.schema.json`
- Modify: `skills/agentic-configuration/tests/test_config.py`
- Create: `skills/agentic-state-tools/schemas/execution-policy.schema.json`
- Create: `skills/agentic-state-tools/schemas/isolation-proof.schema.json`
- Modify: `skills/agentic-state-tools/schemas/planning-task.schema.json`
- Modify: `skills/agentic-state-tools/schemas/queue.schema.json`
- Modify: `skills/agentic-state-tools/schemas/graph.schema.json`
- Modify: `skills/agentic-state-tools/schemas/worktree.schema.json`
- Modify: `skills/agentic-state-tools/scripts/resolve_execution_mode.py`
- Modify: `skills/agentic-state-tools/scripts/dispatch_transaction.py`
- Modify: `skills/agentic-state-tools/scripts/worktree_manager.py`
- Modify: `skills/agentic-state-tools/scripts/merge_worktree.py`
- Modify: `skills/agentic-state-tools/scripts/inspect_recovery.py`
- Modify: `skills/agentic-state-tools/scripts/authorization.py`
- Modify: `skills/agentic-state-tools/tests/test_orchestration.py`
- Modify: `skills/agentic-state-tools/tests/test_distributed_state.py`
- Modify: `skills/agentic-state-tools/tests/test_recovery_hardening.py`

- [x] **Step 1: Add failing configuration and resolver tests.**

Assert that the config exposes this shape and defaults to sync:

```yaml
async_execution:
  capability_enabled: false
  default_mode: sync
  allow_task_opt_in: true
  max_parallel_tasks: 2
  require_isolated_worktree: true
  require_separate_branch: true
  require_disjoint_write_scope: true
  require_dependency_clearance: true
  require_pinned_plan_revision: true
  require_pinned_input_hashes: true
  require_authorized_merge: true
  fallback_to_sync: true
  automatic_merge: false
```

Test `SYNC`, `AUTO`, `ASYNC_PREFERRED`, and `ASYNC_REQUIRED`; cover every failed eligibility condition, capacity overflow, missing proof, and fallback/block result. Expected before implementation: the old boolean config and mode parser reject the new contract.

- [x] **Step 2: Replace the boolean execution policy with validated task policy.**

Add `execution_policy` to the task schema with the exact fields `requested_mode`, `resolved_mode`, `resolution_reason`, `resolved_by`, `resolved_at`, and nullable `isolation_proof`. Only planning validation may set `requested_mode`; only `resolve_execution_mode.py` may set resolved fields. Implement:

```python
VALID_REQUESTED_MODES = {"SYNC", "AUTO", "ASYNC_PREFERRED", "ASYNC_REQUIRED"}

def resolve_execution_mode(task, *, config, active_tasks, queue, lease, isolation_proof, now):
    """Return a complete execution_policy without mutating runtime state."""
```

Resolve `ASYNC` only when capability, dependency, scope, operation type, migration/deployment, capacity, worktree, branch, plan revision, input hashes, lease, merge independence, recovery, and queue-slot checks all pass. `AUTO` and `ASYNC_PREFERRED` fall back to `SYNC`; `ASYNC_REQUIRED` becomes `BLOCKED` with a machine-readable reason.

- [x] **Step 3: Persist isolation proof and async queue/graph identity.**

Validate an isolation proof with `task_id`, `run_id`, `worktree_path`, `branch_name`, `base_commit`, `plan_revision`, `write_scope_hash`, `active_conflicts_checked_at`, and `isolation_status=VERIFIED`. Require separate worktree and branch metadata in queue, graph, lease, and task state. Add graph edge kinds `DEPENDENCY`, `CONCURRENT`, `MERGE`, `CONFLICT_GROUP`, and `SHARED_WRITE_GROUP` and validate their IDs and hashes.

- [x] **Step 4: Replace boolean merge authorization.**

Change `merge_worktree.py` to require a persisted approval input and typed actor (`--approval`, `--actor`, `--actor-type`) rather than `--authorized`. Call the common authorization validator and verify task/run/attempt/dispatch IDs, source branch/worktree, base commit, current target commit, review verdict, batch membership, artifact hashes, approval target hash/expiry, and actor merge permission. Keep `automatic_merge: false`; a PASS task review only makes the task merge-eligible, not self-authorizing.

- [x] **Step 5: Add async recovery classifications.**

Extend `inspect_recovery.py` and its schema to emit exactly `RESUMABLE`, `MERGE_PENDING`, `CONFLICTED`, `STALE_SAFE_TO_CLEAN`, `STALE_REQUIRES_REVIEW`, or `ABORTED_UNSAFE` for async worktree cases. Never clean a worktree with uncommitted changes, an active lease, a branch commit not reconciled into state, or a superseding plan revision. Add stale-worktree and target-branch-change tests.

- [x] **Step 6: Run the async gate while keeping the default disabled.**

Run:

```text
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_orchestration.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_distributed_state.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_recovery_hardening.py" -v
python skills/agentic-state-tools/scripts/resolve_execution_mode.py --input skills/agentic-state-tools/examples/task-state.json
```

Expected: ineligible tasks resolve to `SYNC` or `BLOCKED` with a reason, no async dispatch lacks verified isolation, merge without a persisted approval is rejected, and the bundled configuration reports `automatic_merge: false`.

**Task 4 checkpoint — 2026-08-04:** Completed in branch commits `af3b713` and the current Task 4 checkpoint. Added validated safe-by-default execution policy resolution, canonical isolation proof and async identity propagation through queue/graph/task/lease, deterministic lease IDs, persisted typed approval fencing for worktree merge, six async recovery classifications, unreconciled-branch and superseding-plan cleanup fences, and resolver CLI policy output. Fresh `python run_tests.py` passed 258/258 tests with 0 failures, 0 skips, and 0 timeouts; Slice C regression tests passed 6/6; Python compilation and `git diff --check` passed. The next unfinished work begins at Task 5.

### Task 5: Introduce and migrate the multi-file transaction framework

**Files:**
- Create: `skills/agentic-state-tools/scripts/runtime_transaction.py`
- Create: `skills/agentic-state-tools/schemas/transaction.schema.json`
- Modify: `skills/agentic-state-tools/schemas/operation.schema.json`
- Modify: `skills/agentic-state-tools/scripts/runtime_utils.py`
- Modify: `skills/agentic-state-tools/scripts/init_runtime.py`
- Modify: `skills/agentic-state-tools/scripts/dispatch_transaction.py`
- Modify: `skills/agentic-state-tools/scripts/update_task_state.py`
- Modify: `skills/agentic-state-tools/scripts/create_review.py`
- Modify: `skills/agentic-state-tools/scripts/create_batch_review.py`
- Modify: `skills/agentic-state-tools/scripts/record_approval.py`
- Modify: `skills/agentic-state-tools/scripts/apply_change_request.py`
- Modify: `skills/agentic-state-tools/scripts/record_operation.py`
- Modify: `skills/agentic-state-tools/scripts/inspect_recovery.py`
- Modify: `skills/agentic-state-tools/scripts/commit_batch.py`
- Modify: `skills/agentic-state-tools/scripts/merge_worktree.py`
- Create: `skills/agentic-state-tools/tests/test_transaction_recovery.py`
- Modify: `skills/agentic-state-tools/tests/test_v1_workflow.py`

- [x] **Step 1: Add failing lifecycle and crash-point tests.**

Test `PREPARED -> APPLYING -> COMMITTED` and `PREPARED -> APPLYING -> ROLLED_BACK`, expected revision rejection, duplicate idempotency-key replay, conflicting idempotency-key rejection, staged-file cleanup, and recovery after failure at each required boundary:

```text
after review write / before state update
after state update / before lease cleanup
after queue write / before graph write
after approval write / before event append
during worktree merge
```

Each test must compare the complete set of canonical files before and after `recover_transactions()` and assert either a committed state or a machine-readable rollback/recovery-pending classification.

- [x] **Step 2: Define the transaction record and API.**

Create `transaction.schema.json` with required fields `operation_id`, `operation_type`, `idempotency_key`, `status`, `expected_revisions`, `target_files`, `staged_files`, `started_at`, `committed_at`, and `rollback_reason`. Implement this dependency-free API:

```python
class RuntimeTransaction:
    def __init__(self, project_root, *, operation_type, idempotency_key, expected_revisions):
        self.project_root = Path(project_root)
        self.operation_type = operation_type
        self.idempotency_key = idempotency_key
        self.expected_revisions = dict(expected_revisions)

    def prepare(self, target_files):
        raise RuntimeError("prepare must record PREPARED before staging")

    def stage_json(self, relative_path, value, schema_path):
        raise RuntimeError("stage_json must validate and fsync a staged artifact")

    def commit(self):
        raise RuntimeError("commit must replace every staged target and write a commit marker")

    def rollback(self, reason):
        raise RuntimeError("rollback must record ROLLED_BACK evidence and clean staging")

def recover_transactions(project_root: str | Path) -> list[dict[str, object]]:
    raise RuntimeError("recover_transactions must reconcile every non-terminal transaction")
```

The implementation must acquire the runtime lock, validate expected revisions before staging, write all staged files under `.agent/runtime/staging/OP-T-1-1/`, fsync each file, append a PREPARED/APPLYING ledger record, replace target files only after every staged hash validates, write a commit marker, remove staging, and make replay idempotent. A missing or ambiguous external side effect must produce `RECOVERY_PENDING`, never an automatic retry.

- [x] **Step 3: Migrate the listed mutations through the transaction API.**

Replace ad hoc rollback in `dispatch_transaction.py` with one transaction. Wrap the review plus task-state transition in `create_review.py`, the batch contract/review pair in the batch workflow, approval plus event in `record_approval.py`, plan invalidation in `apply_change_request.py`, operation/event pairs in `record_operation.py`, queue/graph/state/lease writes in dispatch, and merge metadata plus conflict artifact in `merge_worktree.py`. Keep `init_runtime.py`'s initial directory publication as its existing one-rename bootstrap, but create the transaction/staging directories in that bootstrap.

- [x] **Step 4: Reconcile incomplete transactions during recovery.**

Call `recover_transactions()` before `inspect_recovery.py` classifies tasks. Verify every committed target hash, roll back only fully inferable prepared transactions, retain evidence for partial operations, and include `operation_id`, `idempotency_key`, target paths, previous hashes, target hashes, and classification in the recovery artifact and event journal.

- [x] **Step 5: Run crash and idempotency validation.**

Run:

```text
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_transaction_recovery.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_v1_workflow.py" -v
python skills/agentic-state-tools/scripts/inspect_recovery.py --project-root C:\Temp\agent-skills-plan-fixture --task-id T-ID-1
```

Expected: every injected interruption leaves a recoverable ledger, no duplicate side effect is replayed for the same idempotency key, and unresolved external work is classified `RECOVERY_PENDING`.

### Task 6: Unify change requests, transitions, and authorization

**Files:**
- Create: `skills/agentic-state-tools/scripts/state_transition_registry.py`
- Modify: `skills/agentic-state-tools/scripts/state_machine.py`
- Modify: `skills/agentic-state-tools/scripts/generate_state_artifacts.py`
- Modify: `skills/agentic-state-tools/scripts/validate_state_machine.py`
- Modify: `skills/agentic-state-tools/scripts/validate_transition.py`
- Modify: `skills/agentic-state-tools/schemas/state-machine.json`
- Modify: `skills/agentic-state-tools/schemas/task-state.schema.json`
- Modify: `skills/agentic-state-tools/schemas/event.schema.json`
- Modify: `skills/agentic-state-tools/scripts/validate_change_request.py`
- Modify: `skills/agentic-state-tools/scripts/apply_change_request.py`
- Modify: `skills/agentic-state-tools/schemas/change-request.schema.json`
- Modify: `skills/agentic-state-tools/scripts/authorization.py`
- Modify: `skills/agentic-state-tools/scripts/record_approval.py`
- Modify: `skills/agentic-state-tools/schemas/approval.schema.json`
- Modify: `skills/agentic-state-tools/tests/test_transition_registry.py`
- Modify: `skills/agentic-state-tools/tests/test_adaptive_quality.py`
- Modify: `skills/agentic-state-tools/tests/test_authorization.py`
- Modify: `skills/agentic-state-tools/tests/test_rollback.py`

- [ ] **Step 1: Add failing transition-registry tests.**

Test that the registry generates the task-state enum, event mapping, and runtime transition map without drift; executor `COMPLETED -> ACCEPTED` is rejected; the reviewer-only path is `COMPLETED -> REVIEWING -> ACCEPTED`; repair is `COMPLETED -> REVIEWING -> REPAIR_REQUIRED -> RUNNING`; and cleanup can reach `ARCHIVED` from `ACCEPTED`, `CANCELLED`, and `SUPERSEDED`. Every transition record must validate `from`, `to`, `allowed_roles`, `required_artifacts`, and `required_guards`, including `same_run` and `same_attempt` for review/acceptance.

- [ ] **Step 2: Make `state_transition_registry.py` authoritative.**

Define a `TRANSITIONS` tuple in the registry and make `state_machine.py` expose maps derived from it. `generate_state_artifacts.py` must generate `schemas/state-machine.json`; `validate_state_machine.py` must compare the checked-in generated artifact to the registry and report every missing/extra status, event, role, artifact, and guard. Runtime scripts must import the registry-derived maps and stop declaring local transition lists.

- [ ] **Step 3: Add target-type-aware structured change operations.**

Set this exact mapping in `validate_change_request.py`:

```python
TARGET_ID_FIELDS = {
    "MASTER_PLAN": "plan_id",
    "SUB_PLAN": "sub_plan_id",
    "BATCH": "batch_id",
    "TASK": "task_id",
    "DECISION": "decision_id",
    "RISK": "risk_id",
    "RUBRIC": "rubric_id",
    "PROFILE": "profile_id",
    "CONFIGURATION": "configuration_id",
}
```

Allow only JSON operations `add`, `replace`, `remove`, `move`, `copy`, and `test`. Implement JSON Pointer resolution for object keys, array indexes, and `-` append; execute all `test` operations before publishing; reject a target whose type-specific ID field does not equal `target_id`. Do not copy an old artifact into a new file with an unvalidated `requested_changes` description.

- [ ] **Step 4: Enforce invalidation and common approval fencing.**

After an approved change, increment revision, recompute hash, mark the prior task revision `SUPERSEDED`, invalidate approvals/reviews/review contracts/batch contracts/dispatches bound to the old revision or hash, and append a typed invalidation event for each affected artifact. Route plan approval, batch approval, merge, change request, schema migration, destructive action, deployment, batch commit, rollback, review override, and next-batch actions through `authorization.py` with `actor`, `action`, `target_type`, `target_id`, `target_revision`, `target_hash`, `policy_version`, `issued_at`, `expires_at`, and `evidence`. Reject stale revision/hash/policy/expiry/actor permissions and require the exact persisted approval artifact.

- [ ] **Step 5: Run the contract consistency gate.**

Run:

```text
python skills/agentic-state-tools/scripts/validate_state_machine.py --input skills/agentic-state-tools/schemas/state-machine.json
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_transition_registry.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_adaptive_quality.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_authorization.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_rollback.py" -v
```

Expected: `STATE_MACHINE_VALID`, all stale/forged/incorrect-target approvals fail closed, and no script can bypass a reviewer-only transition or invalidation rule.

### Task 7: Harden context security, release tests, and packaging

**Files:**
- Create: `skills/agentic-state-tools/scripts/redaction.py`
- Modify: `skills/agentic-state-tools/scripts/secret_scanner.py`
- Modify: `skills/agentic-state-tools/scripts/create_context.py`
- Modify: `skills/agentic-state-tools/scripts/append_event.py`
- Modify: `skills/agentic-state-tools/scripts/record_operation.py`
- Modify: `skills/agentic-dashboard/scripts/project_dashboard.py`
- Modify: `run_tests.py`
- Modify: `skills/agentic-state-tools/scripts/package_skill.py`
- Modify: `skills/agentic-state-tools/tests/test_release_runner.py`
- Modify: `skills/agentic-state-tools/tests/test_packaging.py`
- Create: `MANIFEST.txt`
- Create: `tests/unit/test_context_security.py`
- Create: `tests/release/test_release_gate.py`
- Move: current executable tests into `tests/unit/`, `tests/schema/`, `tests/cli/`, `tests/integration/`, `tests/e2e/`, `tests/recovery/`, `tests/concurrency/`, and `tests/release/`; retain `skills/*/tests` only for package-local metadata fixtures that are included by the manifest.

- [ ] **Step 1: Add failing scanner and redaction tests.**

Test detection and safe reporting for multiline private keys, JWTs, cookie headers, credentialed URLs, database URLs, long base64 values, nested objects, Markdown code blocks, logs, and generated context summaries. Assert that error/report strings contain a path and finding category but never the matched secret value. Test both `REJECT` and configured `REDACT` behavior.

- [ ] **Step 2: Implement one scan-before-persist boundary.**

Add `scan_value`, `redact_value`, and `redaction_report` APIs that recursively traverse dictionaries/lists and serialized JSON/Markdown. Use explicit regexes with named categories:

```python
SECRET_CATEGORIES = {
    "private_key", "jwt", "cookie_header", "credentialed_url",
    "database_credential", "long_base64", "token_assignment",
}
```

`create_context.py` must scan and redact/reject before calling `write_validated`; `append_event.py` and `record_operation.py` must scan serialized event/ledger data before persistence; dashboard projection must scan/redact generated summaries. A redaction report may contain only `{path, category, action}` entries.

- [ ] **Step 3: Split test discovery into explicit groups.**

Update `run_tests.py` so `discover_test_files()` scans only configured `tests/` group directories and skill directories that contain `SKILL.md` or match the official `agentic-*` pattern. Exclude `.pytest_cache`, `__pycache__`, `.git`, `.agent`, `dist`, `build`, and temporary roots by path component. Preserve the public APIs `discover_test_files`, `test_groups`, `empty_group_summary`, and `GROUP_ASSIGNMENTS`; add `--all` as an alias for the complete release group set and keep `--group unit`, `--group integration`, and `--group release` stable. Use subprocess execution only for CLI tests; import pure functions for unit tests.

- [ ] **Step 4: Implement an allowlist package manifest.**

Make `MANIFEST.txt` the source of release members. It must list only `SKILL.md`, `references/` or `refs/`, `scripts/`, `schemas/`, `examples/`, `configuration/`, `tests/`, `README.md`, `MANIFEST.txt`, and the top-level `run_tests.py` under approved package roots. `package_skill.py` must reject a missing manifest, an unlisted file, a missing listed file, `.pyc`, cache, `.agent`, logs, coverage, build output, secret files, and local environment files. Build the ZIP deterministically and reopen it to validate every member against the same allowlist.

- [ ] **Step 5: Add release preflight commands and expected failures.**

Make the release runner execute, in order:

```text
python run_tests.py --all
python -m compileall -q skills tests run_tests.py
python skills/agentic-engineering-wiki/scripts/validate_wiki_links.py --root skills/agentic-engineering-wiki
python skills/agentic-state-tools/scripts/validate_state_machine.py --input skills/agentic-state-tools/schemas/state-machine.json
python skills/agentic-state-tools/scripts/validate_examples.py --examples-root skills/agentic-state-tools/examples --deployment skills/agentic-configuration/config/deployment.test.json
python skills/agentic-state-tools/scripts/package_skill.py --root . --output C:\Temp\agent-skills-release.zip
```

Each command must have a named release error and non-zero exit status on failure; no failed preflight may be hidden by later tests.

- [ ] **Step 6: Run package and security validation.**

Run:

```text
python -m unittest discover -s tests/unit -p "test_context_security.py" -v
python -m unittest discover -s tests/release -p "test_release_runner.py" -v
python -m unittest discover -s tests/release -p "test_packaging.py" -v
python run_tests.py --all
```

Expected: the release runner reports every group, zero collection errors, zero failures, explicit skipped counts, and elapsed duration; the package contains no cache, runtime state, secrets, or unlisted file.

### Task 8: Align documentation, examples, and final reporting

**Files:**
- Modify: `skills/agentic-engineering-wiki/refs/contracts/planning.md`
- Modify: `skills/agentic-engineering-wiki/refs/contracts/handoff.md`
- Modify: `skills/agentic-engineering-wiki/refs/contracts/rubric.md`
- Create: `skills/agentic-engineering-wiki/refs/contracts/batch.md`
- Create: `skills/agentic-engineering-wiki/refs/contracts/async-execution.md`
- Create: `skills/agentic-engineering-wiki/refs/contracts/transactions.md`
- Create: `skills/agentic-engineering-wiki/refs/contracts/authorization.md`
- Create: `skills/agentic-engineering-wiki/refs/contracts/packaging.md`
- Create: `skills/agentic-engineering-wiki/refs/contracts/testing.md`
- Modify: `skills/agentic-engineering-wiki/schemas/index.md`
- Modify: `skills/agentic-state-tools/SKILL.md`
- Modify: `skills/agentic-state-tools/references/artifact-contracts.md`
- Modify: `skills/agentic-task-reviewer/references/review-contract.md`
- Modify: `skills/agentic-batch-reviewer/references/batch-contract.md`
- Modify: `skills/agentic-engineering-core/references/architecture/architecture.md`
- Modify: `skills/agentic-engineering_system_complete_specification.md`
- Create: `docs/release-report-template.md`
- Modify: `skills/agentic-state-tools/examples/task-state.json`
- Modify: `skills/agentic-state-tools/examples/v1-planning-bundle.json`
- Modify: `skills/agentic-state-tools/examples/v1-dispatch.json`
- Create: `skills/agentic-state-tools/examples/batch-contract.json`
- Create: `skills/agentic-state-tools/examples/isolation-proof.json`
- Create: `skills/agentic-state-tools/examples/transaction.json`

- [ ] **Step 1: Add documentation tests for policy status.**

Add a test that every listed policy document contains exactly one of `ENFORCED`, `VALIDATED_ONLY`, `DECLARATIVE_ONLY`, or `NOT_IMPLEMENTED`, and that an `ENFORCED` claim names the script/validator that enforces it. Add a failure for a documented feature with no corresponding command or schema.

- [ ] **Step 2: Update the Wiki and role contracts from implementation.**

Document the exact state transitions, owner/review pin rules, batch writer command, handoff identity checks, async eligibility and recovery classifications, transaction lifecycle, authorization fields/expiry, secret scan behavior, package allowlist, test groups, and release commands. Mark remaining distributed/remote features `NOT_IMPLEMENTED` unless they are backed by a script and release test. Do not describe a policy as enforced solely because a schema contains its fields.

- [ ] **Step 3: Validate every example through the official CLI.**

Add negative examples for missing owner, stale batch contract, wrong run/attempt handoff, async without isolation proof, merge without approval, interrupted transaction, invalid change operation, and secret-bearing context. Update `validate_examples.py` to invoke the relevant scripts, not only JSON schema validation, and make the release runner fail if any positive example or expected negative outcome disagrees with its declared result.

- [ ] **Step 4: Add the required implementation report template.**

Create `docs/release-report-template.md` with these exact sections and tables:

```markdown
## Modified Files
| File | Change | Reason |
| ---- | ------ | ------ |

## New Files
| File | Role |
| ---- | ---- |

## Contract Changes
| Contract | Before | After |
| -------- | ------ | ----- |

## Test Results
| Test group | Passed | Failed | Skipped | Duration |
| ---------- | -----: | ------: | -------: | --------: |

## Remaining Limitations

## Final Verdict
```

The implementation report must choose exactly one verdict: `READY`, `READY_WITH_RESTRICTIONS`, or `NOT_READY`. It must not use `READY` while runtime identity, async isolation, or release tests are failing.

- [ ] **Step 5: Run Wiki, example, and documentation checks.**

Run:

```text
python skills/agentic-engineering-wiki/scripts/validate_wiki_links.py --root skills/agentic-engineering-wiki
python -m unittest discover -s tests/unit -p "test_skill_metadata.py" -v
python -m unittest discover -s tests/release -p "test_release_gate.py" -v
python skills/agentic-state-tools/scripts/validate_examples.py --examples-root skills/agentic-state-tools/examples --deployment skills/agentic-configuration/config/deployment.test.json
```

Expected: `WIKI_VALID`, every positive example passes its runtime validator, every negative example is rejected for the intended reason, and documentation links remain inside the installed Wiki boundary.

### Task 9: Execute the integrated release gate and review the diff

**Files:**
- Modify: `run_tests.py` only if a preceding task exposes a release-gate integration gap.
- Modify: `docs/release-report-template.md` with actual test results and limitations.
- No unrelated files.

- [x] **Step 1: Run focused gates in dependency order.**

Run:

```text
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_contract_hardening.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_transaction_recovery.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_orchestration.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_adaptive_quality.py" -v
python -m unittest discover -s skills/agentic-state-tools/tests -p "test_authorization.py" -v
```

Expected: every focused suite passes before the full release command is attempted.

- [ ] **Step 2: Run the complete release gate.**

Run:

```text
python run_tests.py --all
python -m compileall -q skills tests run_tests.py
python skills/agentic-state-tools/scripts/validate_state_machine.py --input skills/agentic-state-tools/schemas/state-machine.json
python skills/agentic-engineering-wiki/scripts/validate_wiki_links.py --root skills/agentic-engineering-wiki
```

Expected: all test groups pass, no test collection error occurs, state-machine validation prints `STATE_MACHINE_VALID`, and Wiki validation prints `WIKI_VALID`.

- [ ] **Step 3: Build and inspect the release archive.**

Run:

```text
python skills/agentic-state-tools/scripts/package_skill.py --root . --output C:\Temp\agent-skills-release.zip
python -c "import zipfile; from pathlib import Path; p=Path(r'C:\Temp\agent-skills-release.zip'); z=zipfile.ZipFile(p); print('PACKAGE_MEMBERS', len(z.namelist())); assert all('.agent' not in n and '__pycache__' not in n and not n.endswith(('.pyc','.log')) for n in z.namelist())"
```

Expected: the archive is created, reopens successfully, contains only manifest members, and contains no runtime state, cache, compiled bytecode, logs, coverage, build output, secrets, or local environment files.

- [ ] **Step 4: Inspect status and diff before claiming completion.**

Run:

```text
git status --short
git diff --check
git diff --stat
git diff -- docs/superpowers/plans/2026-08-03-agent-skills-contract-hardening.md
```

Expected: only files authorized by the task matrix are changed, the new plan/report contains no placeholder wording, and `git diff --check` produces no output. Do not delete, reset, clean, or move any other files during this review.

- [ ] **Step 5: Populate the final report and select the verdict.**

Copy the actual group counts, failures, skips, and durations from the release runner into `docs/release-report-template.md`. List every remaining `DECLARATIVE_ONLY` or `NOT_IMPLEMENTED` policy honestly. Select `READY` only when full tests pass and runtime identity, canonical artifact creation, async isolation, approval-backed merge, transaction recovery, and package inspection all pass; otherwise select `READY_WITH_RESTRICTIONS` or `NOT_READY` according to the failed gate.

## Acceptance matrix

| Attached requirement | Implementing task | Required evidence |
| --- | --- | --- |
| Runtime identity survives state transitions and wrong-run/attempt handoffs fail | Task 1 | Identity regression suite and recovery/lease reconciliation output |
| Canonical batch contract is script-created and pinned by revision/hash | Task 2 | Writer CLI, schema, no normal direct writes, stale-contract rejection tests |
| Owner, review contract, membership, requirements, and dependency-aware write scope | Task 3 | Planning validator negative matrix and traceability report |
| Closed boolean risk flags are shared by all consumers | Task 3 | Shared schema references, normalization tests, stable rubric hashes |
| Safe-by-default async with isolated worktree and sequential approved merge | Task 4 | Resolver proof, queue/graph identity, merge approval, stale-worktree tests |
| Crash-safe multi-file operations with replay/rollback | Task 5 | Injected interruption matrix and reconciliation evidence |
| Target-aware change requests and invalidation | Task 6 | JSON operation tests, revision/hash invalidation events, superseded task tests |
| Canonical state machine and reviewer-only acceptance | Task 6 | Registry generation/validation and transition tests |
| Unified typed authorization | Task 6 | Approval binding/expiry/actor/action tests across all sensitive commands |
| Secret scanner and context redaction/rejection | Task 7 | Pattern, nested, Markdown, log, and generated-summary tests |
| Release runner, grouped tests, discovery, and allowlist package | Task 7 | `run_tests.py --all`, compile/Wiki/example gates, archive inspection |
| Documentation reflects actual enforcement status | Task 8 | Policy-status documentation test and Wiki validation |
| Required output report and verdict | Task 8 and Task 9 | Completed `docs/release-report-template.md` |

## Completion contract

The work is complete only when every row in the acceptance matrix has a passing test or command result, `git diff --check` is clean, the package contains no forbidden artifact, and the final report names all remaining limitations. The release verdict must be `NOT_READY` if runtime identity, async isolation, transaction recovery, or release tests fail.
