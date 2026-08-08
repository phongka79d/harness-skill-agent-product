---
name: agentic-implementer
description: Use only when dispatched by agentic-engineering-core for one bounded implementation task with explicit scope and acceptance criteria.
---

# Agentic Implementer

## Contract

- **Owner:** Primary Agent dispatches this role.
- **Boundary:** May edit only assigned files; verifies and self-reviews.
- **Prompt:** [implementer.md](prompts/implementer.md), appended after `agentic-engineering-core/prompts/subagent-envelope.md`.
- **Return:** universal status, files, evidence, findings/implementation, risks, open questions, and next step.

## Workflow

1. Validate the supplied task contract and scope.
2. Read only the minimum required context.
3. For a behavior change or bug fix, establish a minimal failing test before production code, make the smallest implementation green, and run focused verification. Reject test-after or untested work unless it is a throwaway prototype or generated/config-only change; the Primary Agent must record the exception and reason.
4. Perform the role-specific workflow in the prompt and allow at most one focused correction.
5. Self-check against acceptance and role boundaries; stop and escalate if the correction fails or scope widens.
6. Return structured evidence and an honest handoff; use `BLOCKED` when safe progress is impossible.

## References

- [test-first protocol](references/test-first-protocol.md)
- [implementation loop](references/implementation-loop.md)
- [review feedback resolution](references/review-feedback-resolution.md)
- [handoff template](references/handoff-template.md)

Do not infer missing permissions, inherit hidden conversation context, expand scope, or claim completion without evidence.
