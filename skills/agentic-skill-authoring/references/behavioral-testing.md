# Behavioral Testing

A skill is not behaviorally hardened because its prose looks correct. Test the
agent under pressure with the scenario schema and runner named by the
entrypoint:

```text
RED       run the scenario before the rule exists or is corrected
GREEN     add the smallest skill rule and rerun the same scenario
REFACTOR  increase pressure or ambiguity, close the new loophole, rerun all affected scenarios
```

## Scenario contract

Each scenario should identify an immutable scenario ID, pressure prompt,
applicable profiles, expected agent behavior, prohibited behavior, expected
scenario result, and evidence requirements. Keep the test result separate from
the agent's workflow decision: a scenario may `PASS` because the agent stopped
with `BLOCKED`, for example.

The runner must distinguish:

- `PASS`: expected behavior and evidence were observed;
- `FAIL`: the agent violated the rule or produced forbidden behavior;
- `BLOCKED`: the scenario could not run because required harness context,
  schema, runner, authorization, or model/config resolution was unavailable;
- `INCONCLUSIVE`: the response or evidence cannot distinguish compliance from
  failure.

For every run, preserve the scenario ID, prompt or input hash, configured
`model_ref`, deployment/config reference or hash, profile, command, exit code,
result, timestamp, and evidence location. Resolve model selection through the
repository configuration; do not embed a provider or provider-specific
behavior in a scenario.

## Profile-aware verification

Run all ten initial pressure scenarios for every profile that claims to use the
skill. Strict `production` and `high_risk` profiles require RED, GREEN, and
broad verification for behavior changes. `internal_tool` and `course_project`
profiles require RED and GREEN when a viable harness exists and use risk-based
broad verification. `prototype`, `quick_change`, and `personal` profiles may
use a focused characterization check only through a recorded machine-readable
exception with an authority and follow-up; they still require scope, approval,
identity, safety, and evidence gates.

Profile flexibility changes verification depth, not the expected safety rule.
An unavailable runner is `BLOCKED`, not a passing test, and an ambiguous
response is `INCONCLUSIVE`, not evidence of compliance. A skill handoff must
include the result for every required scenario and identify any stale or
skipped evidence.
