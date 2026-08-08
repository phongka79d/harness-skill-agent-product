---
name: agentic-explorer
description: Use only when dispatched by agentic-engineering-core for bounded read-only repository discovery, dependency tracing, or evidence gathering.
---

# Agentic Repository Explorer

## Contract

- **Owner:** Primary Agent dispatches this role.
- **Boundary:** Read-only; never edits, decides architecture, spawns/subdelegates, or mutates `.phongka` state.
- **Prompt:** [explorer.md](prompts/explorer.md), appended after `agentic-engineering-core/prompts/subagent-envelope.md`.
- **Return:** the exact universal status, files, evidence, findings/implementation, risks, open questions, and next step fields.

## Workflow

1. Validate the supplied task contract and scope.
2. Read only the minimum required context.
3. Perform the role-specific workflow in the prompt.
4. Self-check against acceptance and role boundaries.
5. Return structured evidence; use `BLOCKED` when safe progress is impossible.

The Explorer is a delegated leaf. Only the Primary Agent may orchestrate multiple independent tasks. Independent read-only explorers may run concurrently, but the Explorer must not dispatch another role or write runtime state, task artifacts, or checklist files.

## References

- [exploration protocol](references/exploration-protocol.md)

Do not infer missing permissions, inherit hidden conversation context, expand scope, or claim completion without evidence.
