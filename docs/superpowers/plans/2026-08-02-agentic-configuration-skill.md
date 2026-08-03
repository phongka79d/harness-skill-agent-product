# Agentic Configuration Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Keep the Primary Agent as architecture owner and review the actual diff before completion. Steps use checkbox syntax for tracking.

**Goal:** Add one schema-validated configuration skill and route agent dispatch, role guidance, runtime defaults, and release validation through it.

**Architecture:** Create `skills/agentic-configuration` with a JSON-compatible YAML config, schema, loader, and tests. Make the dispatch boundary read the config through an environment-overridable loader; keep `.agent/` runtime state and project-specific plans outside the config skill. Role skills reference config keys instead of copying model policy.

**Tech Stack:** Python 3 standard library, JSON-compatible YAML, existing JSON-schema subset validator, `unittest`, Markdown skills.

---

### Task 1: Establish RED coverage for central configuration

**Files:**
- Modify: `skills/agentic-state-tools/tests/test_orchestration.py`
- Modify: `skills/agentic-engineering-core/tests/test_skill_metadata.py`

- [x] Add a test that dispatch rejects a role/model mismatch supplied through `AGENTIC_CONFIG_FILE`.
- [x] Add a test that requires the new config skill, config file, schema, loader, and all agent-role entries.
- [x] Run the focused tests and observe them fail because the central config package does not exist or is ignored.

### Task 2: Scaffold and implement the configuration skill

**Files:**
- Create: `skills/agentic-configuration/SKILL.md`
- Create: `skills/agentic-configuration/agents/openai.yaml`
- Create: `skills/agentic-configuration/config/agentic-config.yaml`
- Create: `skills/agentic-configuration/schemas/agentic-config.schema.json`
- Create: `skills/agentic-configuration/scripts/load_config.py`
- Create: `skills/agentic-configuration/tests/test_config.py`

- [x] Scaffold the skill with the skill creator initializer.
- [x] Define the agent role map, model policy, execution, approval, runtime, checkpoint, locking, recovery, version-control, documentation, context, security, and retention sections.
- [x] Implement package-relative config discovery plus `AGENTIC_CONFIG_FILE` override.
- [x] Validate required structure, model allowlist, role model references, and unknown model policy before returning config.
- [x] Add loader CLI output for deterministic inspection.
- [x] Run config tests and skill metadata validation.

### Task 3: Route dispatch and queue reconciliation through config

**Files:**
- Modify: `skills/agentic-state-tools/scripts/dispatch_task.py`
- Modify: `skills/agentic-state-tools/scripts/reconcile_queue.py`
- Modify: `skills/agentic-state-tools/schemas/dispatch.schema.json`
- Modify: `skills/agentic-state-tools/examples/v1-dispatch.json`
- Modify: `skills/agentic-state-tools/tests/test_orchestration.py`
- Modify: `skills/agentic-state-tools/tests/test_v1_workflow.py`

- [x] Remove the hard-coded model set from `dispatch_task.py`.
- [x] Require `agent_role` and validate the selected model against the role entry and central model policy.
- [x] Reuse the same config-backed dispatch validator in queue reconciliation.
- [x] Keep schema responsible for shape while config remains the policy source of truth.
- [x] Update examples/tests with explicit role IDs and run focused orchestration tests.

### Task 4: Point role skills and release checks to the config skill

**Files:**
- Modify: `skills/agentic-engineering-core/SKILL.md`
- Modify: `skills/agentic-engineering-core/references/policies/delegation-policy.md`
- Modify: `skills/agentic-engineering-wiki/SKILL.md`
- Modify: `skills/agentic-engineering-wiki/refs/policies/delegation.md`
- Modify: `skills/agentic-engineering-wiki/refs/workflows/execution.md`
- Modify: `skills/agentic-explorer/SKILL.md`
- Modify: `skills/agentic-implementer/SKILL.md`
- Modify: `skills/agentic-state-tools/SKILL.md`
- Modify: `run_tests.py`
- Modify: `skills/agentic-engineering-core/tests/test_skill_metadata.py`

- [x] Add config-skill startup routing to every role entry point.
- [x] Replace duplicated model literals in policy text with config-key references where practical.
- [x] Validate central config before the existing release examples and tests run.
- [x] Preserve the Primary Agent boundary and the no-Orchestrator decision.

### Task 5: Verify the complete package

**Files:**
- No additional files.

- [x] Run config tests and orchestration tests.
- [x] Run `python run_tests.py`.
- [x] Run `python -m compileall -q skills run_tests.py`.
- [x] Run state-machine, dispatch-schema, Wiki-link, config, and all skill metadata validators.
- [x] Inspect actual changed files and report Git limitations if the workspace still has no repository metadata.
