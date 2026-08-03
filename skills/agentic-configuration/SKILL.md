---
name: agentic-configuration
description: Use when an agentic role, dispatch boundary, runtime helper, or release check needs the shared model routing, agent capability, execution, approval, recovery, or workspace configuration.
---

# Agentic Configuration

Use this skill as the single source of truth for agentic-system defaults and dispatch policy. Read the bundled config before selecting an agent, model, execution mode, approval path, retry limit, runtime location, or context budget.

## Canonical files

- Config: `config/agentic-config.yaml`
- Contract: `schemas/agentic-config.schema.json`
- Deployment overlay contract: `schemas/deployment-config.schema.json`
- Deployment example: `config/deployment.example.json`
- Loader: `scripts/load_config.py`

The portable config is JSON-compatible YAML so it works with the Python standard library. Set `AGENTIC_CONFIG_FILE` only for an intentional, schema-valid policy override. Provider model IDs belong in a separate deployment overlay selected with `AGENTIC_DEPLOYMENT_CONFIG`; a model dispatch cannot resolve without that overlay.

## Required routing

Use the `agents` map, not a copied model literal. The `agent-executor`, `agent-review`, and other role entries define a portable `model_ref`, capabilities, forbidden capabilities, and the owning skill. The deployment overlay maps every ref to an opaque provider model ID. `model_policy.allowed_model_refs` is the global gate; forbidden refs are resolved and fenced by the loader.

Model identifiers are opaque deployment values. Never put a provider/model name in a role skill, runtime script, schema enum, or portable example. Another agent tool supplies its own deployment overlay without changing the skill code. The checked-in test overlay is test-only and is excluded from release packaging.

The loader rejects missing sections, unknown role dispatches, forbidden model refs, missing deployment mappings, role/model mismatches, placeholders, and malformed overrides before a dispatch record can be accepted. `model_policy.immutable_forbidden_model_refs` preserves the non-negotiable forbidden tiers. `.agent/` remains project-local runtime state and never stores this config.

## Inspection

Run:

```text
python scripts/load_config.py --check
python scripts/load_config.py --check --deployment path/to/deployment.json
```

Read [agentic-engineering-core](../agentic-engineering-core/SKILL.md) for the shared boundary and use `agentic-state-tools` for canonical runtime writes.
