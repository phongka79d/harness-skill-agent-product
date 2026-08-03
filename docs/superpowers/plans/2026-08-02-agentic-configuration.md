# Central Agentic Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Keep the Primary Agent as architecture owner and review actual diffs before completion.

**Goal:** Make agent roles, dispatch, runtime limits, approvals, recovery, paths, and context budgets read one validated central config while keeping model identifiers portable across agent tools.

**Architecture:** `skills/agentic-configuration/config/agentic-config.yaml` is the canonical deployment profile. Role skills and runtime helpers resolve role/model data through the loader; `AGENTIC_CONFIG_FILE` supplies a schema-valid profile for another host tool. Model IDs remain opaque data and are never embedded in logic or schema enums.

### Implementation checklist

- [x] Add the central config, schema, loader, and environment override.
- [x] Route role skills and state helpers through the config skill.
- [x] Validate config and dispatch payloads at their boundaries.
- [x] Reconcile malformed dispatch records instead of dropping them.
- [x] Load model values from config in tests and fixtures.
- [x] Run the full suite, compile check, schema/state/wiki checks, and skill validators.

### Acceptance criteria

- A role dispatch must match the configured role entry and configured policy.
- A malformed config or dispatch is rejected before policy checks or runtime work.
- A supplied alternate config can use arbitrary non-empty provider-specific model identifiers.
- No role skill, runtime script, schema enum, or test hard-codes a provider/model name.
