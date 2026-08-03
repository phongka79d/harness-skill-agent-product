---
name: agentic-dashboard
description: Use when a project needs a read-only, evidence-backed view of agentic runtime state, queue, reviews, locks, leases, recovery, or event history.
---

# Agentic Dashboard

This skill creates a deterministic observability projection from the current
project's `.agent/` runtime. It never becomes a state owner and it never
changes runtime artifacts.

Read the shared delivery rules in [agentic-engineering-core](../agentic-engineering-core/SKILL.md),
the state ownership rules in [agentic-state-tools](../agentic-state-tools/SKILL.md),
and the shared routing policy in [agentic-engineering-wiki](../agentic-engineering-wiki/SKILL.md)
and the central defaults in [agentic-configuration](../agentic-configuration/SKILL.md)
before interpreting a snapshot.

## Command

From this workspace, run:

```text
python scripts/project_dashboard.py --project-root <project> --as-of <timestamp>
```

Use `--config <external-json>` to configure additional redacted field names
and the stale-evidence threshold. Use `--output <external-path>` only for an
export outside `.agent/`. A fixed `--as-of` value makes repeated exports from
unchanged inputs byte-identical.

## Views

The validated snapshot contains read-only views for:

- queue, task states, and dispatch entries
- the state snapshot and event history
- task reviews and resolved rubrics
- task, file, and resource locks
- task leases and expiry evidence
- persisted recovery classifications and reconciliation records
- event timeline and source diagnostics

Each source item includes a relative source path, normalized data, and stale
evidence reasons. Malformed or missing source files become diagnostics; they
are never silently omitted.

## Boundary

The command may read `.agent/` but must not call mutation commands, acquire a
runtime lock, rebuild state, inspect recovery through a mutating command, or
write any file below `.agent/`. Canonical state changes must go through
`agentic-state-tools`. Dashboard output is a projection, not a source of truth.
