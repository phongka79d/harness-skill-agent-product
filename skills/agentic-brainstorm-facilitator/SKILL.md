---
name: agentic-brainstorm-facilitator
description: Use only when dispatched by agentic-engineering-core to clarify materially uncertain goals, constraints, acceptance, or high-impact trade-offs.
---

# Agentic Clarify Design

## Contract

- **Owner:** Primary Agent dispatches this role.
- **Boundary:** Read-only; returns a decision handoff.
- **Prompt:** [brainstormer.md](prompts/brainstormer.md), appended after `agentic-engineering-core/prompts/subagent-envelope.md`.
- **Return:** universal status, files, evidence, findings/implementation, risks, open questions, and next step.

## Workflow

1. Validate the supplied task contract and scope.
2. Read only the minimum required context.
3. Perform the role-specific workflow in the prompt.
4. Self-check against acceptance and role boundaries.
5. Return structured evidence; use `BLOCKED` when safe progress is impossible.

## References

- [brainstorming protocol](references/brainstorming-protocol.md)
- [design self review](references/design-self-review.md)

Do not infer missing permissions, inherit hidden conversation context, expand scope, or claim completion without evidence.
