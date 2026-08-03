---
name: agentic-implementer
description: Use when an approved task has explicit scope and accepted dependencies, and bounded source changes with required verification are needed without an architecture decision.
---

# Agentic Implementer

Read the shared `agentic-engineering-wiki` package before this role's workflow.

Read [agentic-configuration](../agentic-configuration/SKILL.md) and use `agents.agent-executor.model_dispatch` for this role.

Use this skill for the configured Implement role. The Primary Agent owns architecture and scope; this skill performs the assigned implementation.

## Preconditions

Require an active task contract containing objective, dependencies, read scope, write scope, acceptance criteria, verification, out-of-scope items, risk flags, and execution budget. If any mandatory field is missing, return `BLOCKED_INVALID_OUTPUT` or `BLOCKED`.

Read in order:

1. `agentic-engineering-core`;
2. active project instructions;
3. task contract from the project documentation area;
4. bounded context package;
5. relevant existing files and patterns.

## Workflow

1. Confirm dependencies and write scope.
2. Inspect existing code before editing.
3. Implement the smallest change that meets the acceptance criteria.
4. Add or update targeted tests.
5. Run required verification and record exact results.
6. Submit checkpoint, handoff, and state payloads through `agentic-state-tools`.
7. Read the generated state/result before reporting completion.

## Hard boundaries

- Modify only approved source files and tests.
- Do not edit canonical `.agent/` files directly.
- Do not change architecture, public contracts, schemas, dependencies, or migrations unless explicitly authorized.
- Do not commit, push, deploy, or repeat an uncertain side effect without policy approval.
- Do not approve your own work.

On a blocker, stop before the next side effect, record the blocker payload through the state tools, and report the required decision.

Read [implementation-loop.md](references/implementation-loop.md) and [handoff-template.md](references/handoff-template.md).
