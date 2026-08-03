# Test and Package Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Execute the tasks inline with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make release validation cover failure paths, validate examples through runtime scripts, and produce a clean allowlisted package.

**Architecture:** Split the test runner into named groups with counts, elapsed time, and timeout. Add adversarial, crash, concurrency, review-integrity, example-runtime, and packaging tests. Package only source/docs/config/schema/example files and verify no cache, secret, log, or runtime state enters the artifact.

**Tech Stack:** Python 3, `unittest`, subprocess timeout, ZIP, JSON Schema, Git ignore rules.

---

### Task 1: Test group runner and timeouts

**Files:**
- Modify: `run_tests.py`
- Create: `skills/agentic-state-tools/tests/test_release_runner.py`
- Modify: `.gitignore`

- [ ] **Step 1: Add failing tests** for group discovery, timeout handling, separate pass/fail/skip counts, and cache exclusion.
- [ ] **Step 2: Run them and verify the current runner reports only one aggregate result.**
- [ ] **Step 3: Implement explicit groups for unit/schema/CLI/integration/end-to-end/recovery/concurrency/rollback/review/examples/package.**
- [ ] **Step 4: Add per-process timeout and deterministic discovery that excludes `__pycache__`, `.pytest_cache`, and generated runtime roots.**
- [ ] **Step 5: Run the runner tests and full suite.**

### Task 2: Runtime example and negative coverage

**Files:**
- Create: `skills/agentic-state-tools/tests/test_adversarial_contracts.py`
- Create: `skills/agentic-state-tools/tests/test_example_runtime.py`
- Create: `skills/agentic-state-tools/scripts/validate_examples.py`

- [ ] **Step 1: Add failing tests** for every documented bypass scenario and for schema-pass/runtime-fail examples.
- [ ] **Step 2: Implement the example validator using the corresponding CLI script without mutating fixtures.**
- [ ] **Step 3: Add crash-point and concurrency fixtures using temporary project roots.**
- [ ] **Step 4: Run each named group separately and record pass/fail/skip counts and elapsed time.**

### Task 3: Allowlisted packaging

**Files:**
- Create: `skills/agentic-state-tools/scripts/package_skill.py`
- Create: `skills/agentic-state-tools/tests/test_packaging.py`
- Modify: `skills/agentic-engineering-system-complete-specification.md`

- [ ] **Step 1: Add a failing packaging test** that finds `.pyc`, `__pycache__`, logs, runtime state, temporary files, and secrets in a package candidate.
- [ ] **Step 2: Implement an allowlist rooted at `skills/` and `docs/` with explicit file extensions and exclusions.**
- [ ] **Step 3: Create a reproducible ZIP with sorted paths and fixed metadata, then verify it in the test.**
- [ ] **Step 4: Run packaging and full test groups.**

---

## Acceptance Criteria

- Test output has independent group counts, timing, and explicit incomplete groups.
- Examples are runtime-validated and negative paths are covered.
- Package output excludes caches, secrets, logs, temporary files, and generated runtime state.

