# Review Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Execute tasks inline with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make canonical rubrics the only source of review policy and make task/batch verdicts derived, complete, and fail closed.

**Architecture:** Load the pinned rubric from the task or batch contract, verify profile/task/risk/policy identity and SHA-256, then validate only evidence and achieved scores from the payload. Derive verdicts from canonical criteria, findings, threshold, mandatory minimums, hard-fail rules, and expected task IDs.

**Tech Stack:** Python 3, JSON Schema, filesystem artifacts, `unittest`.

---

### Task 1: Canonical rubric identity

**Files:**
- Modify: `skills/agentic-state-tools/scripts/resolve_rubric.py`
- Modify: `skills/agentic-state-tools/scripts/create_review.py`
- Modify: `skills/agentic-state-tools/scripts/create_batch_review.py`
- Modify: `skills/agentic-state-tools/scripts/calculate_rubric_score.py`
- Test: `skills/agentic-state-tools/tests/test_adaptive_quality.py`

- [x] **Step 1: Add failing tests** that alter payload threshold, criterion weights, mandatory flags, minimum scores, hard-fail rules, profile ID, and rubric hash while keeping evidence constant.
- [x] **Step 2: Run the focused tests and confirm altered policy is accepted by the current code.**
- [x] **Step 3: Add `load_canonical_rubric(contract, review_type)` and compare every pinned identity field plus canonical hash.**
- [x] **Step 4: Remove reviewer-controlled policy fields from normalization; reject them when they differ from canonical values.**
- [x] **Step 5: Run the focused tests and the existing adaptive quality suite.**

### Task 2: Exact criteria and score invariants

**Files:**
- Modify: `skills/agentic-state-tools/scripts/calculate_rubric_score.py`
- Modify: `skills/agentic-state-tools/schemas/review.schema.json`
- Modify: `skills/agentic-state-tools/schemas/rubric.schema.json`
- Test: `skills/agentic-state-tools/tests/test_adaptive_quality.py`

- [x] **Step 1: Add failing tests** for duplicate criterion IDs, missing mandatory criteria, unknown criteria, invalid weight totals, score above maximum, below minimum with `PASS`, and hard-fail omission.
- [x] **Step 2: Run them and verify each fails for the intended invariant.**
- [x] **Step 3: Require criterion objects to carry ID, evidence, and achieved score; compare submitted IDs to canonical IDs exactly once.**
- [x] **Step 4: Compute weighted score from canonical weights and derive verdict after hard-fail and mandatory checks.**
- [x] **Step 5: Run focused tests and `python run_tests.py`.**

### Task 3: Batch completeness and integration gates

**Files:**
- Modify: `skills/agentic-state-tools/scripts/create_batch_review.py`
- Modify: `skills/agentic-state-tools/schemas/batch-review.schema.json`
- Modify: `skills/agentic-state-tools/references/cli-behavior.md`
- Test: `skills/agentic-state-tools/tests/test_orchestration.py`
- Test: `skills/agentic-state-tools/tests/test_p1a.py`

- [x] **Step 1: Add a failing test** with five canonical tasks and only four submitted passing reviews.
- [x] **Step 2: Run the test and verify the batch currently passes or fails for the wrong reason.**
- [x] **Step 3: Load the canonical batch contract and require set equality and list uniqueness for expected and submitted task IDs.**
- [x] **Step 4: Require accepted task state, matching rubric identity, integration/regression/scope checks, and no unresolved severe finding before `PASS`.**
- [x] **Step 5: Run focused orchestration tests and full suite.**

---

## Acceptance Criteria

- Reviewer payload cannot change canonical policy fields.
- Duplicate, missing, unknown, over-scored, under-minimum, hard-fail, and severe-finding cases cannot pass.
- Batch `expected_task_ids == submitted_task_ids` is enforced from the canonical batch contract.
- Changed rubric or contract hash invalidates the review.
