# Agentic Configuration Skill Design

**Status:** Approved for inline implementation from the user's request.

## Goal

Provide one editable, schema-validated configuration skill that defines agent roles, model dispatch, execution limits, approvals, runtime boundaries, recovery, documentation paths, context budgets, security, and retention defaults. Runtime code and role skills must resolve these values from the central config instead of requiring scattered edits.

## Architecture

Create `skills/agentic-configuration/` as the canonical configuration skill. Its `config/agentic-config.yaml` is JSON-compatible YAML so the existing dependency-free loader can read it without requiring PyYAML. Its loader accepts `AGENTIC_CONFIG_FILE` for controlled overrides and otherwise resolves the bundled config by package-relative path.

The config is organized by concern:

- `agents`: role-to-skill mapping, model dispatch, capabilities, and forbidden capabilities;
- `model_policy`: the approved model set and role dispatch rules;
- `execution`, `approval_matrix`, `runtime`, `checkpoint`, `locking`, `recovery`, `version_control`, `documentation`, `context_budget`, `security`, and `retention`.

`agentic-state-tools/scripts/dispatch_task.py` remains the deterministic dispatch boundary. It requires an `agent_role`, loads the central config, and rejects a selected model that does not match that role's configured dispatch model or the configured model policy. The dispatch schema validates the shape; the config validates the policy.

## Routing and compatibility

All role entry points read `agentic-configuration/SKILL.md` and refer to config keys rather than repeating model values. Existing profile and rubric files remain separate because they are versioned collections, not runtime routing settings. `.agent/` remains generated runtime state only.

## Error handling

Missing, malformed, or structurally invalid config is a hard validation failure. Dispatch must stop before writing a record. An environment override is only accepted when it resolves to a readable, schema-valid config. No fallback silently uses a different model or policy.

## Testing

Tests cover: config package discovery, schema validity, required role coverage, env override resolution, role/model mismatch rejection, allowed dispatch, and full existing release behavior. The release runner validates the config before loading the broader suite.

## Scope exclusions

Do not move project-specific task definitions or `.agent/` runtime artifacts into the global config. Do not add an Orchestrator skill, new model tier, remote config service, or automatic config mutation.
