# Evidence freshness

Evidence becomes stale after a material work change affecting checked behavior, not merely because task status advances.

For stateless focused source-editing routes, rerun checks invalidated by the edit and inspect the final diff.

For stateful work, persist:

- the current `work_revision`;
- the workflow decision hash;
- every scoped file path;
- each file byte size;
- each file SHA-256 hash;
- unique verification check names that are stable acceptance IDs.

`status_revision` tracks lifecycle transitions independently. Recording verification while `IN_PROGRESS`, then moving to `COMPLETED`, preserves evidence when `work_revision` and every scoped file hash remain unchanged.

The completion gate rechecks all bindings and file values. Delivery also rechecks the persisted completion claim against the gate hash and the current verification check IDs. A work-revision, decision, scope-coverage, file, or acceptance-mapping mismatch blocks the claim; timestamps or summaries alone are not sufficient.
