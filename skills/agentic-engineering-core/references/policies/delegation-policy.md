# Delegation Policy Compatibility Pointer

The canonical delegation policy is [the shared Wiki policy](../../../agentic-engineering-wiki/refs/policies/delegation.md). Keep this compatibility page aligned for older consumers.
The configuration source is [agentic-configuration](../../../agentic-configuration/SKILL.md).

- The Primary Agent owns architecture, scope, delegation, conflict resolution, and final validation.
- Explore work uses `agents.agent-explorer.model_dispatch`.
- Implement work uses `agents.agent-executor.model_dispatch`.
- `model_policy.forbidden_models` and models outside `model_policy.allowed_models` are forbidden dispatch targets.
- Allow one focused correction after malformed output or failed validation; then mark the work `BLOCKED` or `ESCALATED` and never retry indefinitely.
