---
name: agentic-implementer
description: Use when an approved task has explicit scope and accepted dependencies, and bounded source changes with required verification are needed without an architecture decision.
---

# Agentic Implementer

Read the shared `agentic-engineering-wiki` package before this role's workflow.

Read [agentic-configuration](../agentic-configuration/SKILL.md) and resolve `agents.agent-executor.model_ref` through the deployment overlay for this role.

Use this skill for the configured Implement role. The Primary Agent owns architecture and scope; this skill performs the assigned implementation.

## Preconditions

Require an active task contract containing objective, dependencies, read scope, write scope, acceptance criteria, verification, out-of-scope items, risk flags, and execution budget. If any mandatory field is missing, return `BLOCKED_INVALID_OUTPUT` or `BLOCKED`.

For a behavior change or bug fix, the task must also identify the applicable
project profile and a structured verification case. Loose verification text is
planning guidance only; it is not completion evidence.

For a `REPAIR_REQUIRED` task, also require the canonical
`.agent/work/<task-id>/debug-investigation.json` with matching task/run/attempt
identity, a confirmed root cause, and a passing regression check before repair
work or a successful handoff.

Read in order:

1. `agentic-engineering-core`;
2. active project instructions;
3. task contract from the project documentation area;
4. bounded context package;
5. relevant existing files and patterns.

## Workflow

1. Confirm dependencies and write scope.
2. Inspect existing code before editing.
3. For repair work, read the confirmed investigation and checkpoint intent through `agentic-state-tools`.
4. For a behavior change, run and record the smallest RED test before implementation.
5. Implement the smallest behavior change, then run and record focused GREEN evidence.
6. After every material edit, rerun affected focused checks and the profile-required broad suite.
7. Submit an investigation-bound handoff and state payloads through `agentic-state-tools`.
8. Read the generated state/result before reporting completion.

## Evidence-backed TDD

The required sequence for behavior changes is `RED -> GREEN -> broad
verification`. Each phase must record the exact command, observed exit code,
UTC timestamp, current `workspace_hash`, `task_id`, `plan_revision`,
`run_id`, `attempt_id`, `task_revision`, acceptance-criterion IDs, and an
output digest or evidence location.

- `RED` proves the smallest test fails for the missing behavior, not because of syntax, environment, collection, or an unrelated failure.
- `GREEN` proves the focused test passes after the minimum implementation; exit code must be `0`.
- `broad` proves the suite required by the resolved profile; a focused pass is never a broad-suite claim.

Any material edit that can affect the case makes affected prior evidence
`STALE` for claims about the edited workspace, even if the old command
previously passed. Preserve the initial RED result as the pre-change baseline,
but rerun affected GREEN or broad checks from the current workspace and bind
the replacement to the current task revision and workspace hash. A prior run,
summary, or copied output cannot support a current completion claim.

Apply the strictness in `agentic-engineering-wiki/refs/policies/validation.md`.
The Implementer may not lower the resolved profile policy. A permitted
exception must be a machine-readable object containing `reason`, `authority`,
structured `alternative_verification`, and `expires_at` or `follow_up`.

Report `PASS`, `FAIL`, `SKIPPED`, `NOT_APPLICABLE`, and `BLOCKED` honestly,
with the actual exit code or an explicit non-execution reason. Use `NOT_RUN` in
the handoff when no evidence was produced, and classify stale evidence as
`STALE`. Required verification that is skipped, not run, stale, or failed
cannot be reported as `FIXED` or `PASS` without an accepted exception.

## Hard boundaries

- Modify only approved source files and tests.
- Do not edit canonical `.agent/` files directly.
- Do not change architecture, public contracts, schemas, dependencies, or migrations unless explicitly authorized.
- Do not report `FIXED` or `PASS` for repair work without linked root-cause and passing regression evidence.
- Do not report completion from summary-only test claims, stale evidence, or a focused test presented as the broad suite.
- Do not commit, push, deploy, or repeat an uncertain side effect without policy approval.
- Do not approve your own work.

On a blocker, stop before the next side effect, record the blocker payload through the state tools, and report the required decision.

Read [implementation-loop.md](references/implementation-loop.md) and [handoff-template.md](references/handoff-template.md).
