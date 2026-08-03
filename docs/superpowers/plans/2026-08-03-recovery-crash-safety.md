# Recovery and Crash Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Execute the tasks inline with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile state-machine, journal, checkpoint, lease, operation, and Git state after restart or partial failure.

**Architecture:** The transition registry is the sole state-transition source. Recovery classifies every documented state, validates checkpoint/task/attempt hashes, repairs safe prepared operations, and reports unsupported or ambiguous states instead of inventing transitions. Reconciliation is explicit and idempotent.

**Tech Stack:** Python 3, JSONL event journal, atomic files, Git inspection, `unittest`.

---

### Task 1: Canonical transition consumers

**Files:**
- Modify: `skills/agentic-state-tools/scripts/state_machine.py`
- Modify: `skills/agentic-state-tools/scripts/update_task_state.py`
- Modify: `skills/agentic-state-tools/scripts/append_event.py`
- Modify: `skills/agentic-runtime-recovery/scripts/inspect_recovery.py`
- Test: `skills/agentic-state-tools/tests/test_recovery_hardening.py`

- [ ] **Step 1: Add failing tests** for direct `TASK_ACCEPTED` without review, undocumented transitions, terminal-state mutation, and `REVIEWING` recovery.
- [ ] **Step 2: Run the tests and confirm direct event replay can create accepted state.**
- [ ] **Step 3: Route event application and task updates through one registry with actor/action guards and review/approval prerequisites.**
- [ ] **Step 4: Add explicit handling for every documented state and reject unsupported states.**
- [ ] **Step 5: Run state/recovery tests and validate the state machine schema.**

### Task 2: Operation ledger and reconciliation

**Files:**
- Modify: `skills/agentic-state-tools/scripts/operation_ledger.py`
- Modify: `skills/agentic-state-tools/scripts/write_artifact.py`
- Modify: `skills/agentic-state-tools/scripts/rebuild_state.py`
- Modify: `skills/agentic-state-tools/scripts/reconcile_queue.py`
- Test: `skills/agentic-state-tools/tests/test_distributed_state.py`
- Test: `skills/agentic-state-tools/tests/test_recovery_hardening.py`

- [ ] **Step 1: Add failing crash-point tests** between each write in dispatch, review, approval, and commit operations.
- [ ] **Step 2: Implement prepare/commit/rollback markers, input/output hashes, and idempotency detection.**
- [ ] **Step 3: Reconcile complete writes, roll back safe partial writes, and return `RECOVERY_PENDING` for ambiguous external side effects.**
- [ ] **Step 4: Validate checkpoints against task revision, attempt ID, and input artifact hashes before resume.**
- [ ] **Step 5: Run crash/restart/recovery tests and full suite.**

---

## Acceptance Criteria

- No direct event or review write can bypass transition prerequisites.
- Every documented state has explicit recovery behavior or a fail-closed unsupported result.
- Partial multi-file operations are discoverable and reconcilable after restart.

