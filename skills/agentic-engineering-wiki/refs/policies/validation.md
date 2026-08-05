# Validation Policy

The [testing contract](../contracts/testing.md) is canonical for RED/GREEN/BROAD
phases, evidence fields, workspace freshness, and structured exceptions. Use the
[verification gate](../../../agentic-verification-before-completion/SKILL.md) before
any positive completion, readiness, merge, or release claim.

Resolve profile strictness before selecting the verification depth:

- `production` and `high_risk`: RED, GREEN, and broad verification are mandatory for behavior changes and bug fixes.
- `internal_tool` and `course_project`: RED and GREEN are mandatory when a viable harness exists; broad verification is risk-based.
- `prototype`, `quick_change`, and `personal`: a characterization check or focused reproducible command may replace strict TDD only through a recorded exception.

The task cannot lower the resolved profile policy. A permitted exception must
follow the machine-readable shape in the testing contract; a prose waiver is not
evidence.

Before claiming `PASS`, inspect the actual output and exit code for every
required command. Report `FAIL`, `SKIPPED`, `NOT_APPLICABLE`, `NOT_RUN`, and
`BLOCKED` with the reason and non-execution/exit-code state; stale evidence is
rejected as `STALE`. None is equivalent to `PASS` without an accepted exception.
Evidence is also required for approvals, terminal cleanup, recovery safety, and
release claims.
