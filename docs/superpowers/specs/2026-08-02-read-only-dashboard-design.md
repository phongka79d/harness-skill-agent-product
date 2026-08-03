# Read-Only Dashboard and Observability Design

**Status:** Approved for inline implementation under the P2 continuation approval.

**Goal:** Provide deterministic visibility into the canonical `.agent/` runtime without introducing a second state owner or a mutation path.

## Scope

The dashboard is a Python standard-library projection command packaged as the
`agentic-dashboard` skill. It reads canonical runtime artifacts and produces a
validated JSON snapshot. It does not run a server, mutate runtime artifacts,
rebuild state, inspect recovery through the mutating recovery command, or write
inside `.agent/`.

The snapshot exposes these views:

- queue and task state
- event/state history
- task review and resolved rubric status
- task/file/resource locks
- task leases
- persisted recovery classifications
- diagnostics for malformed or missing evidence

## Data Flow

```text
.agent/runtime, .agent/work, .agent/locks, .agent/recovery
        -> read-only normalized collector
        -> deterministic sorting and redaction
        -> stale-evidence classification
        -> dashboard snapshot schema
        -> stdout or an external export path
```

The snapshot records an explicit `as_of` timestamp, runtime revision, source
file hashes, redaction configuration, and stale threshold. The same source
artifacts and the same command inputs therefore produce the same snapshot.

## Redaction and Freshness

Dashboard configuration is supplied as an external JSON object with
`redact_keys` and `stale_after_seconds`. Key matching is case-insensitive and
recursive through objects and arrays. Values for matching keys are replaced by
`[REDACTED]`; source paths and field names remain visible for diagnosis.

Evidence is stale when its timestamp is older than the configured threshold at
`as_of`. Lease records are additionally stale when `expires_at` is at or before
`as_of`. Missing timestamps and malformed files become diagnostics rather than
being silently omitted.

## Safety and Errors

The collector treats `.agent/` as read-only. An optional export path must be
outside `.agent`; the command rejects paths inside the runtime boundary. A
malformed source artifact is represented in `diagnostics` with a stable source
path and error category. The command returns a nonzero exit code for invalid
configuration or output-path violations, but a valid snapshot can still expose
runtime evidence that needs reconciliation.

## Verification

Tests cover schema validation, deterministic output, recursive configured
redaction, stale lease/evidence detection, malformed-source diagnostics, and
the absence of writes under `.agent/`. The package metadata and all existing
tests remain part of the release gate.
