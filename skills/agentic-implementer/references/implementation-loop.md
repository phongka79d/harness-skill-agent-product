# Implementation Loop

```text
read contract
-> resolve profile and verification policy
-> read confirmed investigation for repair work
-> checkpoint intent through state tools
-> identify behavior and acceptance criteria
-> run the exact RED command
-> record RED evidence
-> make the smallest behavior or root-cause change
-> run the exact focused GREEN command
-> record GREEN evidence
-> invalidate and rerun evidence after every material edit
-> run and record the profile-required broad suite
-> prepare an investigation-bound handoff payload
-> validate and persist handoff
```

For each phase, record an immutable result with the exact `command`, observed
`exit_code`, UTC `recorded_at`, `workspace_hash`, `task_id`, `plan_revision`,
`run_id`, `attempt_id`, `task_revision`, acceptance-criterion IDs, and output
digest or evidence location. RED normally has a non-zero exit code and an
intended failure signature; GREEN and a required broad suite require exit code
`0`. A RED failure caused by syntax, environment, collection, or an unrelated
test is not valid RED evidence.

The same task, plan revision, run, and attempt must bind the evidence set used
by a completion handoff. RED normally records the pre-change baseline hash;
GREEN and BROAD record the workspace on which they actually ran, normally the
current final hash. The final GREEN/BROAD evidence and claim must match the
current task revision and workspace. A material edit includes any
implementation, test, configuration, dependency-lock, generated-output, or
build-input change that can affect the case. It makes affected prior evidence
`STALE` for claims about the edited workspace; do not relabel it as current or
reuse its output. Re-run from the current workspace and report skipped,
failed, blocked, and not-run commands with their reason and actual exit-code
state.

The canonical repair investigation is `.agent/work/<task-id>/debug-investigation.json`.
Its `investigation_id` must remain attached to dispatch, task state, lease, and
handoff records. A `COMPLETE` handoff requires confirmed root-cause evidence and
`regression_check.status == PASS` with exit code `0`. `BLOCKED` and `ESCALATED`
handoffs may preserve failed evidence without being normalized to `COMPLETE`.

Create a checkpoint before a migration, deletion, external side effect, or context exhaustion. If validation fails, make one focused repair attempt; then escalate instead of widening scope.

Profile strictness and machine-readable exception requirements are defined once
in `agentic-engineering-wiki/refs/contracts/testing.md`. An exception is not a
free-form note and cannot silently lower the resolved profile policy.
