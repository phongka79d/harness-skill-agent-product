# Async Worktree Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Execute the tasks inline with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide safe per-task Git worktrees or keep async execution explicitly disabled until all isolation checks exist.

**Architecture:** A worktree manager creates a unique branch and directory for each task/revision, records the mapping in runtime state, and takes a workspace lock. Merge is a primary-owned operation with conflict state; cleanup is allowed only after task acceptance or explicit cancellation. Async resolution fails closed when the manager is unavailable.

**Tech Stack:** Python 3, Git CLI, filesystem locks, JSON artifacts, `unittest`.

---

### Task 1: Worktree manager and mapping

**Files:**
- Create: `skills/agentic-state-tools/scripts/worktree_manager.py`
- Create: `skills/agentic-state-tools/schemas/worktree.schema.json`
- Modify: `skills/agentic-state-tools/scripts/resolve_execution_mode.py`
- Modify: `skills/agentic-state-tools/schemas/task-state.schema.json`
- Test: `skills/agentic-state-tools/tests/test_distributed_state.py`

- [ ] **Step 1: Add failing tests** for unique task directories, unique branches, mapping persistence, shared-directory rejection, and async-disabled fallback.
- [ ] **Step 2: Run the tests and verify no manager exists and four tasks can be marked runnable.**
- [ ] **Step 3: Implement create/validate/reclaim functions using `git worktree add`, a stable path under configured root, and a workspace lock.**
- [ ] **Step 4: Make async mode return blocked unless isolation is validated for the task.**
- [ ] **Step 5: Run worktree and execution-mode tests.**

### Task 2: Merge, conflict, cleanup, and stale recovery

**Files:**
- Modify: `skills/agentic-state-tools/scripts/worktree_manager.py`
- Modify: `skills/agentic-runtime-recovery/scripts/inspect_recovery.py`
- Create: `skills/agentic-state-tools/scripts/merge_worktree.py`
- Test: `skills/agentic-state-tools/tests/test_recovery_hardening.py`

- [ ] **Step 1: Add failing tests** for merge conflicts, stale worktree metadata, cleanup before acceptance, and branch reuse across revisions.
- [ ] **Step 2: Implement conflict artifacts and `RECOVERY_PENDING` fencing; never delete a worktree with active lease or unmerged changes.**
- [ ] **Step 3: Add stale reclaim only after lease expiry and primary authorization.**
- [ ] **Step 4: Run recovery and worktree tests.**

---

## Acceptance Criteria

- No two concurrent async tasks share a directory or branch.
- Mapping survives restart and stale metadata is recoverable.
- Merge conflicts stop the batch and cleanup never discards unaccepted changes.
- Async cannot be enabled by config alone without implementation support.

