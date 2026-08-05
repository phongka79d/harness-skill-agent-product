---
name: agentic-explorer
description: Use when an assigned engineering task needs read-only repository exploration, code tracing, dependency discovery, or evidence gathering without source or runtime-state changes.
---

# Agentic Explorer

Use this skill for the configured Explore role. Read the shared
[Explorer role](../agentic-engineering-wiki/refs/roles/explorer.md),
[execution modes contract](../agentic-engineering-wiki/refs/contracts/async-execution.md),
and [exploration protocol](references/exploration-protocol.md) before starting.

Read [agentic-configuration](../agentic-configuration/SKILL.md) and resolve
`agents.agent-explorer.model_ref` through the deployment overlay for this role.

## Workflow

1. Load `agentic-engineering-core` and the active task or investigation request.
2. Confirm the read scope, forbidden write scope, and selected execution mode.
3. Inspect the smallest useful set of files using repository search and targeted reads.
4. Trace call sites, data flow, existing patterns, tests, and configuration.
5. Return a protocol-compliant report with facts, inferences, unknowns, and inspected files kept separate.

Explorer work is read-only and does not implement, commit, create branches or
worktrees, mutate runtime state, or choose architecture. Use the canonical
references above for the detailed boundaries and evidence format.
