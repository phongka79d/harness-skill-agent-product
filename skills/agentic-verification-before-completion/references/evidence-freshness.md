# Evidence Freshness

Freshness is a conjunction: evidence is usable only when its result, identity,
and workspace all describe the claim being evaluated now. A matching command
or a matching hash alone is insufficient.

## Minimum evidence identity

Each evidence record referenced by a completion claim should expose at least:

```text
evidence_id
verification_case_id
task_id
plan_revision
run_id
attempt_id
task_revision
phase
verification_type
workspace_hash
command
exit_code
status
recorded_at
acceptance_criterion_ids[]
```

The `verification_type` identifies the check class (for example `lint`,
`typecheck`, `tests`, `build`, `package`, or `requirements`). The `phase`
identifies RED, GREEN, or BROAD when the evidence belongs to a TDD case. The
record should also include the relevant output digest or durable output
location, the command scope, and a failure signature when a failing result is
expected (for example, the RED phase of a TDD case).

## Freshness rules

An evaluator must verify all of the following:

1. `task_id`, `plan_revision`, `run_id`, `attempt_id`, and `task_revision`
   exactly match the claim and the current task state.
2. `workspace_hash` matches a recomputed, content-aware snapshot of the current
   workspace or the approved worktree. The snapshot must include relevant file
   content, not only file names or Git status.
3. The evidence was recorded after the last relevant edit and after any
   dependency, lockfile, base-commit, or build-configuration change that can
   affect the check.
4. The command and its scope are the ones required by the active profile and
   change kind. A command string copied into a claim without a recorded run is
   not evidence.
5. The output was inspected for hidden skips and failures, and the recorded
   `exit_code` and `status` agree with the observed result.
6. The evidence's acceptance criterion IDs are valid and are used by the
   claim's explicit acceptance mapping.

An evidence record from a previous attempt is stale even if it was collected
against identical source content. Attempt identity prevents results from one
execution history being silently reused in another.

## Invalidation events

Invalidate affected evidence after any of these events:

| Event after collection | Required action |
| --- | --- |
| Relevant file content changes | Re-run the affected check and capture a new workspace hash |
| Task or plan revision changes | Re-run all checks whose contract or scope may have changed |
| Run or attempt changes | Collect evidence in the new run/attempt |
| Dependency version or lockfile changes | Re-run typecheck, tests, build, package, and any affected requirement check |
| Base commit or merge base changes | Re-run checks affected by the new base and refresh the workspace binding |
| Build, test, lint, or package configuration changes | Re-run that class and all downstream classes it controls |
| A check is skipped, quarantined, xfailed, or partially selected | Record the state and require an allowed exception; never retain a pass |

When the exact affected set cannot be established, treat the evidence as stale
and re-run the broader required suite.

## Freshness procedure

Before emitting a claim:

1. Read current task state and resolve the current run and attempt.
2. Recompute the workspace hash from the approved content and relevant
   configuration.
3. Compare every evidence record's identity, revision, hash, timestamp,
   command, exit code, and output status.
4. Check the final edit boundary. Evidence collected before a material edit is
   invalid even if the edit appears unrelated until the affected scope is
   proven.
5. Replace invalid records or return `UNVERIFIED` with the exact freshness
   failure.

Do not repair a stale record by editing its timestamp or hash. Historical
evidence is immutable; collect a new record.

## Legacy records

Records without the required identity or result fields remain readable for
migration and audit, but they must be classified as `LEGACY_UNVERIFIED`.
They cannot satisfy a new strict production or high-risk gate, and they cannot
be upgraded by copying fields into a claim. New evidence must be recorded in
the current attempt.
