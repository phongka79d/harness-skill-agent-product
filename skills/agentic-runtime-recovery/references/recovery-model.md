# Recovery Model

```text
load state and event journal
→ validate snapshot revision
→ detect stale leases
→ inspect checkpoint and actual workspace
→ reconcile operations and side effects
→ classify recovery
→ create a new run only when safe
```

Classification:

- `SAFE_TO_RESUME`: workspace and operations agree with the checkpoint.
- `NEEDS_RECONCILIATION`: evidence conflicts or an external side effect is unresolved.
- `UNSAFE_TO_RESUME`: data loss, destructive ambiguity, corrupted evidence, or invalid state prevents safe continuation.

Workspace reconciliation records Git HEAD, checkpoint `base_commit`, changed and untracked paths, expected `files_modified`, and any unexpected or missing paths. A mismatch is `NEEDS_RECONCILIATION`; a non-Git fixture is tolerated only when the checkpoint does not claim Git evidence.

Checkpoint creation and recovery use the same normalized workspace capture helper. Each inspection persists a schema-validated `reconciliation-<task-id>.json` artifact under `.agent/recovery/` and includes its ID and evidence hash in the `RECOVERY_INSPECTED` event. A checkpoint is evidence, not permission to resume by itself.

Operation-ledger rules:

- Read `.agent/work/<task-id>/operations.jsonl` before classifying a task.
- A malformed JSONL record, schema violation, task mismatch, timestamp error, or broken revision/status chain is `UNSAFE_TO_RESUME`.
- The latest record for any operation with status `STARTED` or `UNKNOWN` is unresolved and forces `NEEDS_RECONCILIATION`.
- `COMPLETED` and `FAILED` are finalized operation evidence; they do not by themselves block recovery.

Lock records include owner PID/identity evidence when available. An expired lock is not reclaimed while its recorded owner is live; legacy records without identity are reclaimed only with an `UNKNOWN` liveness classification and a persisted reclaim artifact.

Terminal cleanup is a proof obligation. Malformed leases, locks, operation records, or unresolved latest operation statuses yield `NEEDS_RECONCILIATION` and prevent a terminal transition from being reported as clean.

Rollback is a separate explicit workflow. Recovery may surface a rollback plan,
ledger, or evidence artifact, but it must not infer compensation from a failed
task. Destructive compensation requires an exact approved `ROLLBACK` record;
unknown, failed, or stale-fencing outcomes remain escalated and are never
retried automatically.
