# Portable Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Execute the tasks inline with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make role routing and policy resolve from one portable configuration plus an explicit deployment overlay.

**Architecture:** Keep role IDs, capabilities, and policy names in the skill package. Store provider model IDs only in a deployment overlay selected by `AGENTIC_DEPLOYMENT_CONFIG`. The loader validates both layers, applies an immutable policy floor, and exposes `resolve_agent()` to every consumer.

**Tech Stack:** Python 3, JSON-compatible YAML, Draft 2020-12 JSON Schema, `unittest`.

---

### Task 1: Add deployment overlay contract

**Files:**
- Modify: `skills/agentic-configuration/schemas/agentic-config.schema.json`
- Modify: `skills/agentic-configuration/config/agentic-config.yaml`
- Create: `skills/agentic-configuration/schemas/deployment-config.schema.json`
- Create: `skills/agentic-configuration/config/deployment.example.json`
- Test: `skills/agentic-configuration/tests/test_config.py`

- [x] **Step 1: Write the failing tests** for a role using `model_ref`, a deployment overlay resolving it, and an overlay that removes an immutable forbidden model.
- [x] **Step 2: Run `python -m unittest skills.agentic-configuration.tests.test_config`** and confirm the new tests fail because the loader has no overlay contract.
- [x] **Step 3: Add `model_ref` to model agents and add an overlay schema requiring `deployment_id`, `version`, and a non-empty `models` object.** Keep the checked-in example provider-neutral.
- [x] **Step 4: Run the focused config tests and `python skills/agentic-configuration/scripts/load_config.py --check`.** Both must pass.
- [x] **Step 5: Commit the schema/config contract with `git add` and `git commit -m "feat: add portable deployment configuration"`.**

### Task 2: Enforce immutable model policy and resolver ownership

**Files:**
- Modify: `skills/agentic-configuration/scripts/load_config.py`
- Modify: `skills/agentic-configuration/tests/test_config.py`
- Modify: every script that currently imports `load_config` or reads model fields directly

- [x] **Step 1: Add failing tests** for missing overlay entries, undeclared role references, forbidden effective models, and a dispatch selection that bypasses `resolve_agent()`.
- [x] **Step 2: Run the focused tests and record the expected failures.**
- [x] **Step 3: Implement `load_deployment_config()`, `merge_deployment_config()`, and `resolve_agent(config, agent_id)` with fail-closed validation.** Reject any overlay attempt to alter immutable forbidden models or execution safety flags.
- [x] **Step 4: Replace direct model comparisons with `resolve_agent()` and keep provider IDs out of prompts, examples, and tests.**
- [x] **Step 5: Run config tests plus `python run_tests.py`; verify no skill file contains a provider model literal outside deployment fixtures.
- [x] **Step 6: Review `git diff --check` and commit the resolver change.**

### Task 3: Document the configuration source of truth

**Files:**
- Modify: `skills/agentic-configuration/SKILL.md`
- Modify: `skills/agentic-engineering-core/references/policies/delegation-policy.md`
- Create: `skills/agentic-configuration/references/configuration-contract.md`
- Test: `skills/agentic-configuration/tests/test_config.py`

- [x] **Step 1: Add a failing metadata test** requiring the skill to name the config loader, overlay variable, and fail-closed behavior.
- [x] **Step 2: Update the documents with exact commands and the role/model-ref contract.**
- [x] **Step 3: Run metadata, config, and wiki-link tests.**
- [x] **Step 4: Commit the documentation after the executable tests pass.**

---

## Acceptance Criteria

- No runtime consumer selects a model without the central resolver.
- A deployment overlay cannot remove immutable policy or enable an unsupported execution mode.
- A portable skill package contains no provider-specific model IDs in role prompts, schemas, examples, or tests.
- Invalid overlays fail before any dispatch or runtime mutation.
