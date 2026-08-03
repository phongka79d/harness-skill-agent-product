# Batch Review Contract

```yaml
review_id: "BATCH-REV-SP-01-B01"
batch_id: "SP-01-B01"
task_reviews:
  - "REV-SP-01-B01-T01"
integration_checks:
  - kind: integration
    name: api_compatibility
    result: PASS
    evidence: "..."
  - kind: regression
    name: regression_suite
    result: PASS
    evidence: "..."
  - kind: scope
    name: write_scope
    result: PASS
    evidence: "..."
hard_fail_checks:
  - rule: unresolved_major_correctness_issue
    triggered: false
    evidence: "The integrated diff and task findings were checked."
findings: []
verdict: PASS | REPAIR_REQUIRED | BLOCKED | PLAN_INVALID
```

`task_reviews` must equal the canonical batch contract's expected task IDs exactly
once, and every referenced task must be accepted. Each non-legacy task review must
match its task-state review contract and canonical rubric. The verdict must be
supported by task review IDs, all integration/regression/scope evidence, hard-fail
checks, and any required approval record.

Submit this payload to `create_batch_review.py`. The script resolves the final
verdict from accepted task reviews, integration check results, scope validity,
and unresolved severe findings; a reviewer-provided verdict is not authoritative.
