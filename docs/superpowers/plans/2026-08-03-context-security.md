# Context Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Execute the tasks inline with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent secrets, sensitive paths, binaries, and over-budget content from entering context artifacts or logs.

**Architecture:** A shared scanner classifies paths and recursively scans text values for secret patterns. Context builder rejects denied files, redacts allowed text where policy permits, protects binary content, enforces byte and item budgets, and runs the same scanner against serialized output before persistence.

**Tech Stack:** Python 3, regex, pathlib, JSON, atomic artifact writes, `unittest`.

---

### Task 1: Shared scanner and path policy

**Files:**
- Create: `skills/agentic-state-tools/scripts/secret_scanner.py`
- Modify: `skills/agentic-state-tools/scripts/create_context.py`
- Modify: `skills/agentic-state-tools/schemas/context.schema.json`
- Modify: `skills/agentic-configuration/config/agentic-config.yaml`
- Test: `skills/agentic-state-tools/tests/test_report_gaps.py`

- [x] **Step 1: Add failing tests** with `.env`, bearer token, authorization header, password, database URL, private key, cloud credential, and binary bytes.
- [x] **Step 2: Run them and confirm context persists sensitive values.**
- [x] **Step 3: Implement deny-path matching, recursive string scanning, redaction markers, binary detection, and byte budgets.**
- [x] **Step 4: Invoke the scanner before writing context and reject when `forbid_secret_storage_in_context` is true.**
- [x] **Step 5: Run focused context/security tests.**

### Task 2: Log and artifact leak regression coverage

**Files:**
- Modify: `skills/agentic-state-tools/scripts/runtime_utils.py`
- Modify: `skills/agentic-state-tools/scripts/append_event.py`
- Modify: `skills/agentic-dashboard/scripts/project_dashboard.py`
- Test: `skills/agentic-state-tools/tests/test_report_gaps.py`

- [x] **Step 1: Add failing tests** that inspect event journal, operation ledger, and dashboard output after a secret-bearing input.
- [x] **Step 2: Redact or reject values before serialization and keep the original secret out of exception messages.**
- [x] **Step 3: Run context, dashboard, and full tests.**

---

## Acceptance Criteria

- Context builder itself enforces secret policy; dashboard filtering is not the security boundary.
- Denied paths and binary files cannot be read into context.
- Serialized context, event, ledger, and dashboard output contain no detected secret.
