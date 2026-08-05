# Review Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/review_contract.py`)

```yaml
review_id: "REV-SP-01-B01-T01"
task_id: "SP-01-B01-T01"
schema_version: 2
stage: SPEC_COMPLIANCE
artifact_identity:
  task_id: "SP-01-B01-T01"
  task_revision: 3
  run_id: "RUN-1"
  attempt_id: "ATT-1"
  dispatch_id: "DSP-1"
  workspace_hash: "<sha256>"
  artifact_hash: "<sha256 of the identity without artifact_hash>"
review_type: task
review_contract:
  project_profile: "personal"
  profile_hash: "<sha256>"
  task_type: "backend"
  risk_flags: {}
  review_type: task
  rubric_id: "<canonical-rubric-id>"
  rubric_version: "<version>"
  rubric_hash: "<sha256>"
  review_policy_version: "1"
resolved_rubric: "the canonical resolved rubric object"
criteria:
  - id: CORRECTNESS
    score: 4
    applicability: APPLICABLE
    evidence: "..."
hard_fail_checks:
  - rule: acceptance_criteria_not_met
    triggered: false
    evidence: "Acceptance criteria were checked against the handoff and tests."
findings: []
reviewer: "task-reviewer"
```

`CODE_QUALITY` must additionally include `previous_review_id`,
`previous_stage: SPEC_COMPLIANCE`, and `previous_artifact_identity`. The state-tools
writer checks that these values identify the immediately preceding passing
specification review. A staged review without an artifact identity is rejected.

Profiles `personal`, `quick_change`, and `prototype` require a passing final
`SPEC_COMPLIANCE` stage. `course_project`, `internal_tool`, `production`, and
`high_risk` require a passing `SPEC_COMPLIANCE` followed by a passing
`CODE_QUALITY` stage. A later implementation revision invalidates both prior stages.

The contract and resolved rubric are canonical. A reviewer supplies achieved scores,
evidence, findings, and one evidence-backed `hard_fail_checks` entry for every
canonical hard-fail rule. The deterministic scoring script calculates the weighted
percentage and final verdict; a reviewer-provided threshold, weight, mandatory flag,
minimum score, hard-fail policy, or verdict is not authoritative.

The task reviewer may accept only the task's current run/attempt evidence and
the pinned review contract. Findings must identify evidence and location where
applicable. A hard fail overrides the weighted score, and acceptance is not a
reviewer shortcut around the canonical state transition.

## Pressure resistance

“Best practice” does not expand the approved scope. Treat an out-of-scope
feature recommendation as a finding or change request; do not implement it
just because the reviewer sounds confident. A subagent's success message is
also not evidence: inspect the scoped diff, artifact identity, and current
verification records before issuing a passing review. The `HSP-701-04` and
`HSP-702-08` scenarios cover
these boundaries; low-risk profiles may reduce optional quality scoring but
cannot remove specification or scope compliance.
