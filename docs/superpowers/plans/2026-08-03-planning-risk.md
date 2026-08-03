# Planning and Risk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Execute the tasks inline with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate complete planning membership, references, dependency and scope semantics, and strictly typed risk flags.

**Architecture:** Planning validation builds reverse indexes for every relationship and rejects orphan tasks, orphan batches, unknown requirements, duplicate requirement references, missing membership, and cycles. Risk flags use a closed boolean vocabulary and feed canonical profile/rubric resolution.

**Tech Stack:** Python 3, JSON Schema, Python graph traversal, `unittest`.

---

### Task 1: Reverse membership and requirement references

**Files:**
- Modify: `skills/agentic-state-tools/scripts/validate_planning.py`
- Modify: `skills/agentic-state-tools/schemas/master-plan.schema.json`
- Modify: `skills/agentic-state-tools/schemas/planning-batch.schema.json`
- Modify: `skills/agentic-state-tools/schemas/planning-task.schema.json`
- Test: `skills/agentic-state-tools/tests/test_v1_workflow.py`

- [ ] **Step 1: Add failing tests** for an orphan task, orphan batch, task assigned to two batches, missing requirement, duplicate requirement reference, and unknown dependency.
- [ ] **Step 2: Run the tests and confirm the current forward-only validation misses at least one case.**
- [ ] **Step 3: Build batch-to-task and requirement-to-task reverse indexes and require one owner for each task and one valid trace for each requirement.**
- [ ] **Step 4: Preserve sequential overlap when an explicit dependency orders the tasks; reject only parallel conflicting scopes.**
- [ ] **Step 5: Run planning and dependency suites.**

### Task 2: Strict risk flags

**Files:**
- Modify: `skills/agentic-state-tools/schemas/risk.schema.json`
- Modify: `skills/agentic-state-tools/scripts/resolve_rubric.py`
- Modify: `skills/agentic-state-tools/scripts/validate_planning.py`
- Test: `skills/agentic-state-tools/tests/test_adaptive_quality.py`
- Test: `skills/agentic-state-tools/tests/test_v1_workflow.py`

- [ ] **Step 1: Add failing tests** for string values, unknown keys, wrong casing, and risk flags that fail to activate security/database/migration/destructive rubrics.
- [ ] **Step 2: Run the tests and record the accepted malformed inputs.**
- [ ] **Step 3: Define one whitelist and require strict booleans; normalize only key casing when the key is whitelisted.**
- [ ] **Step 4: Resolve profile/rubric from normalized flags and pin normalized flags into the task contract hash.**
- [ ] **Step 5: Run all risk and rubric tests.**

---

## Acceptance Criteria

- Every task belongs to exactly one existing batch and every requirement is traceable.
- Dependencies are existing and acyclic.
- Sequential scope overlap is permitted only with dependency order; parallel conflicts are rejected.
- Invalid risk flag keys/values are rejected and valid high-risk flags affect rubric/approval policy.

