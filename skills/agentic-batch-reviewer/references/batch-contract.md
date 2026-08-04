# Batch Review Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/create_batch_review.py`)

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

The batch contract revision and hash are pinned at review and commit time. The
writer command is `create_batch_contract.py`; a stale pin, missing approval,
missing task review, or task-set mismatch rejects the batch. The Batch Reviewer
does not merge worktrees or approve the next batch.
