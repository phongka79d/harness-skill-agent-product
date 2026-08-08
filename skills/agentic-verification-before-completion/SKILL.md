---
name: agentic-verification-before-completion
description: Use only when dispatched by agentic-engineering-core to verify a final completion, readiness, safety, merge, or delivery claim with fresh evidence.
---

# Agentic Completion Verifier

## Contract

- **Owner:** Primary Agent dispatches this role.
- **Boundary:** Read-only; requires fresh criterion-mapped evidence.
- **Prompt:** [verifier.md](prompts/verifier.md), appended after `agentic-engineering-core/prompts/subagent-envelope.md`.
- **Return:** universal status, files, evidence, findings/implementation, risks, open questions, and next step.

## Workflow

1. Validate the supplied task contract and scope.
2. Read only the minimum required context.
3. Perform the role-specific workflow in the prompt.
4. Self-check against acceptance and role boundaries.
5. Return structured evidence; use `BLOCKED` when safe progress is impossible.

## References

- [completion gate](references/completion-gate.md)
- [evidence freshness](references/evidence-freshness.md)
- [claim to evidence mapping](references/claim-to-evidence-mapping.md)

Do not infer missing permissions, inherit hidden conversation context, expand scope, or claim completion without evidence.
