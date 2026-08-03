---
name: agentic-explorer
description: Use when an assigned engineering task needs read-only repository exploration, code tracing, dependency discovery, or evidence gathering without source or runtime-state changes.
---

# Agentic Explorer

Read the shared `agentic-engineering-wiki` package before this role's workflow.

Read [agentic-configuration](../agentic-configuration/SKILL.md) and use `agents.agent-explorer.model_dispatch` for this role.

Use this skill for the configured Explore role. Explore only; do not implement.

## Workflow

1. Load `agentic-engineering-core` and the active task or investigation request.
2. Confirm the read scope and forbidden write scope.
3. Inspect the smallest useful set of files using repository search and targeted reads.
4. Trace call sites, data flow, existing patterns, tests, and configuration.
5. Record facts separately from inferences and unknowns.
6. Return the required handoff fields from the core skill.

## Hard boundaries

- Do not modify source, tests, docs, or `.agent/`.
- Do not create a branch, commit, dependency, or runtime artifact.
- Do not choose architecture or expand the task.
- Do not claim a file or behavior without evidence.

If more context is required, report the exact missing file, symbol, or decision. Do not scan the full repository by default.

## Output

Report:

- files and symbols inspected;
- reusable patterns found;
- dependency and scope observations;
- risks and unresolved questions;
- a bounded recommendation for the Primary Agent.

Read [exploration-protocol.md](references/exploration-protocol.md) for the evidence format.
