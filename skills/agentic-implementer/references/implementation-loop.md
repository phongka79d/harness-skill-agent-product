# Implementation Loop

```text
read contract
-> read confirmed investigation for repair work
-> checkpoint intent through state tools
-> make the smallest root-cause change
-> run the regression check
-> run broader verification
-> prepare an investigation-bound handoff payload
-> validate and persist handoff
```

The canonical repair investigation is `.agent/work/<task-id>/debug-investigation.json`.
Its `investigation_id` must remain attached to dispatch, task state, lease, and
handoff records. A `COMPLETE` handoff requires confirmed root-cause evidence and
`regression_check.status == PASS` with exit code `0`. `BLOCKED` and `ESCALATED`
handoffs may preserve failed evidence without being normalized to `COMPLETE`.

Create a checkpoint before a migration, deletion, external side effect, or context exhaustion. If validation fails, make one focused repair attempt; then escalate instead of widening scope.
