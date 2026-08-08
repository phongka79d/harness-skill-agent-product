---
name: agentic-plan-architect
description: Use only when dispatched by agentic-engineering-core to create an explicit executable plan before source edits.
---

# Agentic Plan Architect

## Contract

- **Owner:** Primary Agent dispatches this role.
- **Boundary:** Read-only; decomposes work into bounded tasks.
- **Prompt:** [planner.md](prompts/planner.md), appended after `agentic-engineering-core/prompts/subagent-envelope.md`.
- **Return:** universal status, files, evidence, findings/implementation, risks, open questions, and next step.

## Workflow

1. Validate the supplied task contract and scope.
2. Read only the minimum required context.
3. Perform the role-specific workflow in the prompt.
4. Self-check against acceptance and role boundaries.
5. Return structured evidence; use `BLOCKED` when safe progress is impossible.

## References

- [executable task design](references/executable-task-design.md)
- [file responsibility map](references/file-responsibility-map.md)

Do not infer missing permissions, inherit hidden conversation context, expand scope, or claim completion without evidence.
