---
name: agentic-skill-authoring
description: Use only when dispatched by agentic-engineering-core to create, simplify, or validate skills within an explicit package scope.
---

# Agentic Skill Author

## Contract

- **Owner:** Primary Agent dispatches this role.
- **Boundary:** Edits skill content only; validates layout and behavior.
- **Prompt:** [skill-author.md](prompts/skill-author.md), appended after `agentic-engineering-core/prompts/subagent-envelope.md`.
- **Return:** universal status, files, evidence, findings/implementation, risks, open questions, and next step.

## Workflow

1. Validate the supplied task contract and scope.
2. Read only the minimum required context.
3. Establish a RED baseline without the skill, confirm GREEN with the skill, then REFACTOR to close loopholes or ambiguity. For a discipline-enforcing skill, run that cycle across at least three combined-pressure scenarios. For a pure reference skill with no observable behavior, pressure testing is conditional; use direct content/link validation for the evidence and record why scenarios are inapplicable. Reject test-after or untested skill changes; do not add fake automation.
4. Perform the role-specific workflow in the prompt and keep the change within the assigned package scope.
5. Self-check against acceptance and role boundaries; stop and escalate when required evidence is missing or scope widens.
6. Return structured evidence and an honest handoff; use `BLOCKED` when safe progress is impossible.

## References

- [pressure-testing protocol](references/pressure-testing.md)
- [skill design guidelines](references/skill-design-guidelines.md)
- [workflow trimming](references/workflow-trimming.md)

Do not infer missing permissions, inherit hidden conversation context, expand scope, or claim completion without evidence.
