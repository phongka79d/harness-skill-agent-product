# Delegation Policy

The Primary Agent owns architecture, scope, delegation, conflict resolution, approvals, and final validation. Read `agentic-configuration/SKILL.md` for the canonical routing policy. Every delegated task has a defined objective, read scope, write scope, acceptance criteria, verification, risks, and out-of-scope list. The Primary Agent inspects actual changes and validation evidence before accepting work.

Before dispatch, resolve the deterministic skill route from intent, task state,
task type, repair status, risk flags, project profile, requested role, and the
configured skill set. Process skills take precedence over role and domain skills;
the selected role cannot bypass a mandatory debugging, planning, or verification
process. The route must explicitly disable the probabilistic “1% chance” rule.

## Configured model routing

- Read `agentic-configuration/config/agentic-config.yaml` before selecting a role or model.
- Use `agents.agent-explorer.model_ref` for read-only exploration and `agents.agent-executor.model_ref` for bounded implementation; resolve both through the deployment overlay.
- Reject every value in `model_policy.forbidden_model_refs` and every ref outside `model_policy.allowed_model_refs`.
- Every dispatch record must pass the deterministic config-backed validator in `agentic-state-tools`.

Explorers are read-only. Implementers do not make architecture decisions, select another task, expand scope, or approve their own work.

Route independent read-only questions through the [parallel read-only contract](../contracts/async-execution.md) and [exploration protocol](../../../agentic-explorer/references/exploration-protocol.md). Build attempt-bound context with the [context builder](../../../agentic-context-builder/SKILL.md), author or pressure-test skills with [agentic-skill-authoring](../../../agentic-skill-authoring/SKILL.md), and route accepted delivery decisions through the [delivery finalizer](../../../agentic-delivery-finalizer/SKILL.md).

If a delegated agent returns malformed output or fails validation, allow one focused correction. If the correction fails, stop retrying that approach, capture the evidence, and classify the work as `BLOCKED` or `ESCALATED` without silently expanding scope.
