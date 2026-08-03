# Authorization Fencing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Execute tasks inline with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn approval evidence into enforceable, identity-bound authorization for plan, batch, destructive, commit, rollback, and next-batch actions.

**Architecture:** Approval records contain a validated actor identity, action, target type/id, artifact revision/hash, policy version, expiry, and unique approval ID. Gate functions resolve the target artifact and reject stale, forged, cross-target, or insufficient approvals.

**Tech Stack:** Python 3, JSON Schema, filesystem runtime state, `unittest`.

---

### Task 1: Typed approval records

**Files:**
- Modify: `skills/agentic-state-tools/schemas/approval.schema.json`
- Modify: `skills/agentic-state-tools/scripts/record_approval.py`
- Create: `skills/agentic-state-tools/scripts/authorization.py`
- Test: `skills/agentic-state-tools/tests/test_rollback.py`

- [ ] **Step 1: Add failing tests** for actor mismatch, missing target hash, expired approval, and approval reused for another revision.
- [ ] **Step 2: Run the focused tests and confirm forged string actors are accepted.**
- [ ] **Step 3: Require `actor_type`, `actor_id`, `action`, `target_revision`, `target_hash`, `policy_version`, and `expires_at`; validate them in `record_approval.py`.**
- [ ] **Step 4: Implement `authorize(action, target, approval, actor)` and make target/hash/revision/expiry checks mandatory.**
- [ ] **Step 5: Run rollback and approval tests.**

### Task 2: Enforce action gates

**Files:**
- Modify: `skills/agentic-state-tools/scripts/dispatch_task.py`
- Modify: `skills/agentic-state-tools/scripts/execute_rollback.py`
- Modify: `skills/agentic-state-tools/scripts/rollback.py`
- Create: `skills/agentic-state-tools/scripts/commit_batch.py`
- Test: `skills/agentic-state-tools/tests/test_orchestration.py`
- Test: `skills/agentic-state-tools/tests/test_rollback.py`

- [ ] **Step 1: Add failing tests** for user-only destructive/commit actions, primary-only plan actions, and approval invalidation after artifact revision.
- [ ] **Step 2: Run the tests and confirm actor strings or absent gates are sufficient.**
- [ ] **Step 3: Call `authorize()` before every protected side effect and record the consumed approval ID in the operation ledger.**
- [ ] **Step 4: Reject direct approval-like events that do not pass the same gate.**
- [ ] **Step 5: Run focused tests and full suite.**

---

## Acceptance Criteria

- A caller cannot self-assert user or primary identity.
- Approval is bound to exact target type/id, revision/hash, action, policy version, and expiry.
- Plan/batch/commit/rollback/next-batch operations reject stale or insufficient approvals.
