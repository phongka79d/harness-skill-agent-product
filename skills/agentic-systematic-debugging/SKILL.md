---
name: agentic-systematic-debugging
description: Use only when dispatched by agentic-engineering-core to establish the root cause of a defect or unexpected behavior before repair.
---

# Agentic Systematic Debugger

## Contract

- **Owner:** Primary Agent dispatches this role.
- **Boundary:** Read-only investigation before repair; never spawns/subdelegates or mutates `.phongka` state.
- **Prompt:** [debugger.md](prompts/debugger.md), appended after `agentic-engineering-core/prompts/subagent-envelope.md`.
- **Return:** the exact universal status, files, evidence, findings/implementation, risks, open questions, and next step fields.

## Workflow

1. Validate the supplied task contract and scope.
2. Read only the minimum required context.
3. Perform the role-specific workflow in the prompt.
4. Self-check against acceptance and role boundaries.
5. Return structured evidence; use `BLOCKED` when safe progress is impossible.

The Debugger is a delegated leaf. Only the Primary Agent may orchestrate multiple independent tasks; independent read-only debugging may be parallelized by the Primary while writers remain sequential. The Debugger may create scratch only in the non-empty host-owned temporary scope declared by the shared envelope. It must never write source files, the bound worktree, `.phongka`, task artifacts, or checklist state.

## References

- [debugging protocol](references/debugging-protocol.md)
- [root cause tracing](references/root-cause-tracing.md)
- [condition based waiting](references/condition-based-waiting.md)
- [escalation and stop rules](references/escalation-and-stop-rules.md)

Do not infer missing permissions, inherit hidden conversation context, expand scope, or claim completion without evidence.
