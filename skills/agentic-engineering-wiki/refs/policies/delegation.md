# Delegation Policy

The Primary Agent owns architecture, scope, delegation, conflict resolution, approvals, and final validation. Read `agentic-configuration/SKILL.md` for the canonical routing policy. Every delegated task has a defined objective, read scope, write scope, acceptance criteria, verification, risks, and out-of-scope list. The Primary Agent inspects actual changes and validation evidence before accepting work.

## Configured model routing

- Read `agentic-configuration/config/agentic-config.yaml` before selecting a role or model.
- Use `agents.agent-explorer.model_dispatch` for read-only exploration and `agents.agent-executor.model_dispatch` for bounded implementation.
- Reject every value in `model_policy.forbidden_models` and every model outside `model_policy.allowed_models`.
- Every dispatch record must pass the deterministic config-backed validator in `agentic-state-tools`.

Explorers are read-only. Implementers do not make architecture decisions, select another task, expand scope, or approve their own work.

If a delegated agent returns malformed output or fails validation, allow one focused correction. If the correction fails, stop retrying that approach, capture the evidence, and classify the work as `BLOCKED` or `ESCALATED` without silently expanding scope.
