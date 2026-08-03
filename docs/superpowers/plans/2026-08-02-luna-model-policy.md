# Luna Model Delegation Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Keep the Primary Agent as architecture owner and review the actual diff before completion.

**Goal:** Make dispatch resolve only portable model references through the deployment overlay, while keeping the existing Primary-controlled routing architecture unchanged. A Codex deployment may map its implement/explore references to its approved Luna tiers; the skill package remains provider-neutral.

**Architecture:** Enforce one exact portable-reference allowlist at the deterministic dispatch boundary and resolve provider IDs only from the deployment overlay. Align the shared delegation policy, implementer/explorer role guidance, examples, and regression tests with that contract; do not add a new orchestrator or runtime state.

**Tech Stack:** Python 3 standard library, JSON Schema subset validator, Markdown skill documentation, `unittest`.

---

### Task 1: Add failing model-routing tests

**Files:**
- Modify: `skills/agentic-state-tools/tests/test_orchestration.py`
- Modify: `skills/agentic-state-tools/tests/test_v1_workflow.py`

- [ ] Add dispatch cases proving approved portable model references resolve through a deployment overlay.
- [ ] Add dispatch cases proving missing, placeholder, and policy-forbidden deployment mappings are rejected.
- [ ] Update existing valid fixtures to use portable references, never provider model literals.
- [ ] Run the focused orchestration tests and observe the new rejection assertions fail before implementation.

### Task 2: Enforce the allowlist at the dispatch contract boundary

**Files:**
- Modify: `skills/agentic-state-tools/scripts/dispatch_task.py`
- Modify: `skills/agentic-state-tools/schemas/dispatch.schema.json`
- Modify: `skills/agentic-state-tools/examples/v1-dispatch.json`

- [ ] Define the exact allowed model-reference set in the dispatch normalizer.
- [ ] Reject unresolved, placeholder, or policy-forbidden deployment mappings with a structured non-zero dispatch result.
- [ ] Add the portable references to the schema contract.
- [ ] Update the bundled dispatch example to use a provider-neutral reference.
- [ ] Run focused tests and confirm they pass.

### Task 3: Align global policy and role documentation

**Files:**
- Modify: `skills/agentic-engineering-core/references/policies/delegation-policy.md`
- Modify: `skills/agentic-engineering-wiki/refs/policies/delegation.md`
- Modify: `skills/agentic-engineering-core/SKILL.md`
- Modify: `skills/agentic-explorer/SKILL.md`
- Modify: `skills/agentic-implementer/SKILL.md`
- Modify: `skills/agentic-state-tools/SKILL.md`
- Modify: `skills/agentic_engineering_system_complete_specification.md`

- [ ] State that delegated model selection is limited to the two approved Luna variants.
- [ ] Remove the stale Luna-Normal role reference.
- [ ] Document that Sol and Terra are never valid dispatch targets.
- [ ] Keep Primary ownership, bounded scopes, and the no-Orchestrator decision intact.

### Task 4: Run the release validation gate

**Files:**
- No additional files.

- [ ] Run `python skills/agentic-state-tools/tests/test_orchestration.py`.
- [ ] Run `python run_tests.py`.
- [ ] Run `python -m compileall -q skills run_tests.py`.
- [ ] Run the installed skill metadata validator for every `skills/*` package.
- [ ] Inspect the final changed-file list and confirm no unauthorized files changed.
