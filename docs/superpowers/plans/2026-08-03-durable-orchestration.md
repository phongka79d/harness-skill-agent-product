# Durable Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Execute tasks inline with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dispatch a durable, idempotent operation that persists queue, graph, lease, run/attempt, event, and task state.

**Architecture:** `dispatch_task.py` validates task revision, dependency readiness, status, model policy, and parallel capacity inside the runtime lock. It writes one operation ledger entry and atomically updates all runtime artifacts. Repeating the same idempotency key returns the original envelope; a different attempt cannot claim the same task revision.

**Tech Stack:** Python 3, JSON artifacts, atomic rename, filesystem lock, `unittest`.

---

### Task 1: Durable dispatch envelope

**Files:**
- Modify: `skills/agentic-state-tools/scripts/dispatch_task.py`
- Modify: `skills/agentic-state-tools/schemas/dispatch.schema.json`
- Modify: `skills/agentic-state-tools/schemas/queue.schema.json`
- Modify: `skills/agentic-state-tools/schemas/graph.schema.json`
- Test: `skills/agentic-state-tools/tests/test_orchestration.py`

- [ ] **Step 1: Add failing tests** that invoke dispatch with a project runtime and assert queue, graph, lease, run ID, attempt ID, event, and task state files exist.
- [ ] **Step 2: Run the focused test and confirm the current CLI only prints or writes an optional envelope.**
- [ ] **Step 3: Add task-contract loading and state/dependency/revision checks before acquiring the lease.**
- [ ] **Step 4: Persist all dispatch artifacts under the runtime lock and return the durable envelope.**
- [ ] **Step 5: Run focused tests and inspect the generated JSON files.**

### Task 2: Idempotency, leases, and capacity

**Files:**
- Modify: `skills/agentic-state-tools/scripts/dispatch_task.py`
- Modify: `skills/agentic-state-tools/scripts/record_heartbeat.py`
- Modify: `skills/agentic-state-tools/scripts/reconcile_queue.py`
- Create: `skills/agentic-state-tools/scripts/dispatch_transaction.py`
- Test: `skills/agentic-state-tools/tests/test_distributed_state.py`

- [ ] **Step 1: Add failing tests** for duplicate task/revision dispatch, two concurrent claimants, max parallel overflow, stale lease heartbeat, and failed dispatch cleanup.
- [ ] **Step 2: Run the tests and verify the current behavior allows at least one bypass.**
- [ ] **Step 3: Add idempotency keys and lease fencing tokens; reject expired-heartbeat renewal and clean prepared leases on failure.**
- [ ] **Step 4: Count active runnable leases against configured `max_parallel_tasks` before claiming.**
- [ ] **Step 5: Run concurrency/distributed-state tests and the full suite.**

---

## Acceptance Criteria

- Dispatch is observable in queue, graph, journal, lease, ledger, and task state.
- Duplicate dispatch is idempotent or rejected, never duplicated.
- Capacity, dependency, revision, and lease ownership are enforced under one lock.
