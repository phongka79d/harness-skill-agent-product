# Validation Policy

Use the evidence-backed testing contract for behavior changes and bug fixes.
The normal sequence is `RED -> GREEN -> broad verification`: observe the
smallest relevant test fail for the intended missing behavior, implement the
minimum change, confirm the focused test passes, then run the broader suite
required by the resolved profile.

Every phase records the exact command, actual exit code, UTC timestamp,
`workspace_hash`, `task_id`, `plan_revision`, `run_id`, `attempt_id`,
`task_revision`, acceptance-criterion IDs, and output digest or evidence
location. RED records the pre-change baseline; GREEN and broad verification
must record the workspace on which they ran, and the final claim must use the
current final workspace and task revision. Any material edit invalidates
affected prior evidence as `STALE` for claims about the edited workspace.

Profile strictness:

- `production` and `high_risk`: RED, GREEN, and broad verification are mandatory for behavior changes and bug fixes.
- `internal_tool` and `course_project`: RED and GREEN are mandatory when a viable harness exists; broad verification is risk-based.
- `prototype`, `quick_change`, and `personal`: a characterization check or focused reproducible command may replace strict TDD only through a recorded exception.

The task cannot lower the resolved profile policy. An exception must be a
machine-readable object with an explicit `reason`, `authority`, structured
`alternative_verification`, and either `expires_at` or `follow_up`; a prose
waiver is not evidence.

Before claiming `PASS`, inspect the actual output and exit code for every
required command. Report `FAIL`, `SKIPPED`, `NOT_APPLICABLE`, `NOT_RUN`, and
`BLOCKED` with the reason and non-execution/exit-code state; stale evidence is
rejected as `STALE`. None is equivalent to `PASS` without an accepted
exception. Evidence is also required for approvals, terminal cleanup,
recovery safety, and release claims.
