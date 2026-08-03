# Delegation Policy Compatibility Pointer

The canonical delegation policy is [the shared Wiki policy](../../../agentic-engineering-wiki/refs/policies/delegation.md). Keep this compatibility page aligned for older consumers.
The configuration source is [agentic-configuration](../../../agentic-configuration/SKILL.md).

- The Primary Agent owns architecture, scope, delegation, conflict resolution, and final validation.
- Explore work uses `agents.agent-explorer.model_ref` resolved by `AGENTIC_DEPLOYMENT_CONFIG`.
- Implement work uses `agents.agent-executor.model_ref` resolved by `AGENTIC_DEPLOYMENT_CONFIG`.
- `model_policy.forbidden_model_refs` and refs outside `model_policy.allowed_model_refs` are forbidden dispatch targets.
- Allow one focused correction after malformed output or failed validation; then mark the work `BLOCKED` or `ESCALATED` and never retry indefinitely.
