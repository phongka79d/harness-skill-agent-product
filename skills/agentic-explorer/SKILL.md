---
name: agentic-explorer
description: Use only when dispatched by agentic-engineering-core for bounded read-only repository discovery, dependency tracing, or evidence gathering.
---

# Agentic Repository Explorer

## Contract

- **Owner:** Primary Agent dispatches this role.
- **Boundary:** Read-only; never edits or decides architecture.
- **Prompt:** [explorer.md](prompts/explorer.md), appended after `agentic-engineering-core/prompts/subagent-envelope.md`.
- **Return:** universal status, files, evidence, findings/implementation, risks, open questions, and next step.

## Workflow

1. Validate the supplied task contract and scope.
2. Read only the minimum required context.
3. Perform the role-specific workflow in the prompt.
4. Self-check against acceptance and role boundaries.
5. Return structured evidence; use `BLOCKED` when safe progress is impossible.

## References

- [exploration protocol](references/exploration-protocol.md)

Do not infer missing permissions, inherit hidden conversation context, expand scope, or claim completion without evidence.
