# Review Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/review_contract.py`)

```yaml
review_id: "REV-SP-01-B01-T01"
task_id: "SP-01-B01-T01"
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

The contract and resolved rubric are canonical. A reviewer supplies achieved scores,
evidence, findings, and one evidence-backed `hard_fail_checks` entry for every
canonical hard-fail rule. The deterministic scoring script calculates the weighted
percentage and final verdict; a reviewer-provided threshold, weight, mandatory flag,
minimum score, hard-fail policy, or verdict is not authoritative.

The task reviewer may accept only the task's current run/attempt evidence and
the pinned review contract. Findings must identify evidence and location where
applicable. A hard fail overrides the weighted score, and acceptance is not a
reviewer shortcut around the canonical state transition.
