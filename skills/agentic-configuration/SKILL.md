---
name: agentic-configuration
description: Use when an agentic role, dispatch boundary, runtime helper, or release check needs the shared model routing, agent capability, execution, approval, recovery, or workspace configuration.
---

# Agentic Configuration

Use this skill as the single source of truth for agentic-system defaults and dispatch policy. Read the bundled config before selecting an agent, model, execution mode, approval path, retry limit, runtime location, or context budget.

## Canonical files

- Config: `config/agentic-config.yaml`
- Contract: `schemas/agentic-config.schema.json`
- Loader: `scripts/load_config.py`

The config is JSON-compatible YAML so it works with the Python standard library. Set `AGENTIC_CONFIG_FILE` only for an intentional, schema-valid override; otherwise the loader resolves the bundled deployment profile by package-relative path.

## Required routing

Use the `agents` map, not a copied model literal. The `agent-executor`, `agent-review`, and other role entries define `model_dispatch`, capabilities, forbidden capabilities, and the owning skill. `model_policy.allowed_models` is the global gate; a role's model must be in that set.

Model identifiers are opaque configuration values. Never put a provider/model name in a role skill, runtime script, schema enum, example, or test; load it from this config or an `AGENTIC_CONFIG_FILE` override. The bundled file is a deployment profile for the host tool, while another agent tool can supply its own valid config without changing the skill code.

The loader rejects missing sections, unknown role dispatches, forbidden models, role/model mismatches, and malformed overrides before a dispatch record can be accepted. `model_policy.immutable_forbidden_models` preserves the non-negotiable forbidden tiers. `.agent/` remains project-local runtime state and never stores this config.

## Inspection

Run:

```text
python scripts/load_config.py --check
```

Read [agentic-engineering-core](../agentic-engineering-core/SKILL.md) for the shared boundary and use `agentic-state-tools` for canonical runtime writes.
