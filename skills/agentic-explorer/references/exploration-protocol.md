# Exploration Protocol

An explorer report is evidence, not an implementation decision. Keep observed
facts, reasoned inferences, unresolved unknowns, and inspected files in
separate fields so a later reviewer can reproduce and challenge the result.

Use this compact report shape:

```yaml
status: COMPLETE | BLOCKED
summary: "..."
inspected_files:
  - path: "src/example.ts"
    symbols: ["ExampleService"]
facts:
  - id: fact-1
    category: existing_pattern
    evidence: "..."
    location: "src/example.ts:12"
inferences:
  - statement: "..."
    basis: ["fact-1"]
unknowns:
  - "..."
risks:
  - "..."
next_steps:
  - "..."
```

`inspected_files` is the complete, bounded read inventory, including files
searched for relevant evidence but found not to contain a matching symbol when
that negative result affects the conclusion. `facts` contain directly observed
content with a location or command-backed evidence. `inferences` are
interpretations derived from listed facts and must not be presented as facts.
`unknowns` record material questions that the inspected scope cannot answer.

When the report is consumed by a handoff that still uses the legacy
`files_read` field, map `inspected_files` to `files_read` without dropping the
fact/inference/unknown separation.

## Parallel reconciliation

`PARALLEL_READ_ONLY` reports are reconciled before implementation. Combine
reports in a stable order using task or explorer identity, then path and symbol;
retain each source location and do not silently merge contradictory claims.
Matching facts may be deduplicated deterministically. A factual conflict,
missing evidence, or unresolved material unknown pauses implementation until a
targeted read or an approval-backed decision resolves it. Inferences never
override a conflicting fact.

The task contract must pin this reconciliation boundary with
`reconciliation_contract.order: [task_id, path, symbol]`,
`preserve_source_locations: true`, `block_on_conflict: true`, and
`block_on_material_unknown: true`. The resolver also requires explicit
`write_forbidden: true`, an empty `write_scope`, and separate context and token
capacity confirmations before selecting `PARALLEL_READ_ONLY`.

Use `BLOCKED` when the task contract, required context, or authorization is
missing. The report itself may be returned to the Primary Agent; do not write it
into `.agent/` by hand.
