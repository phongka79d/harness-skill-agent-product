---
name: agentic-runtime-recovery
description: Use only when dispatched by agentic-engineering-core to reconcile interrupted project/.phongka work or an uncertain external side effect.
---

# Agentic Runtime Recovery

## Contract

- **Owner:** Primary Agent dispatches this role.
- **Boundary:** Read-only reconciliation; never retries blindly.
- **Prompt:** [recovery.md](prompts/recovery.md), appended after `agentic-engineering-core/prompts/subagent-envelope.md`.
- **Return:** universal status, files, evidence, findings/implementation, risks, open questions, and next step.

## Workflow

1. Validate the supplied task contract and scope.
2. Read only the minimum required context.
3. Perform the role-specific workflow in the prompt.
4. Self-check against acceptance and role boundaries.
5. Return structured evidence; use `BLOCKED` when safe progress is impossible.

## References

- [recovery model](references/recovery-model.md)

Do not infer missing permissions, inherit hidden conversation context, expand scope, or claim completion without evidence.
