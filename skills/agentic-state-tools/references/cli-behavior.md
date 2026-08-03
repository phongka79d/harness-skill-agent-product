# CLI Behavior

All scripts accept `--project-root` when operating on `.agent/`. Inputs are JSON files; a future adapter may provide stdin without changing the contracts.

Exit codes:

- `0`: accepted and written, or valid/read-only result.
- `1`: invalid input, schema failure, or invalid transition.
- `2`: missing project state or a command that cannot run because required runtime state is absent.

Inspection can return exit code `0` even when its result is `NEEDS_RECONCILIATION` or `UNSAFE_TO_RESUME`: the inspection itself completed successfully. Callers must honor that classification and must not resume unless it is `SAFE_TO_RESUME`.

Read-only planning, profile, rubric, queue, dependency, and scope commands also return `0` for a valid result and `1` for invalid input. They do not mutate `.agent/`.

When a task reaches a terminal status, lease and owned-lock removal is recorded as `LEASE_RELEASED` or `LOCK_RELEASED`. An expired named lock may be replaced only after its `expires_at` is validated; the replacement emits `LOCK_RECLAIMED` evidence.

Scripts must not overwrite existing runtime state during initialization unless an explicit reset operation is added and approved by policy.

For versioned artifacts, submit `expected_revision` from the last read result.
The state script increments the revision only when that value still matches;
otherwise it returns a rejection and the agent must reload the artifact.

The distributed state adapter uses the same rule for `expected_revision` and
also requires the last snapshot `etag`. A repeated event ID with identical
content is idempotent; different content is an `EVENT_CONFLICT`. Transport
timeouts and invalid response framing are `NETWORK_UNCERTAIN`, not permission
to retry the mutation. Callers must reconcile the operation ID first.

Rollback commands are explicit: a task failure does not imply compensation.
The planner creates only a dry-run plan tied to known operation IDs. Execution
requires an exact `ROLLBACK` approval and provider evidence; `UNKNOWN`, failed,
or stale-fencing outcomes are recorded and escalated with retry disabled.
