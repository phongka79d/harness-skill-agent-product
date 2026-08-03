# Batch Review Contract

```yaml
review_id: "BATCH-REV-SP-01-B01"
batch_id: "SP-01-B01"
task_reviews:
  - "REV-SP-01-B01-T01"
integration_checks:
  - name: api_compatibility
    result: PASS
    evidence: "..."
findings: []
verdict: PASS | REPAIR_REQUIRED | BLOCKED | PLAN_INVALID
```

The verdict must be supported by task review IDs, integration evidence, and any required approval record.

Submit this payload to `create_batch_review.py`. The script resolves the final
verdict from accepted task reviews, integration check results, scope validity,
and unresolved severe findings; a reviewer-provided verdict is not authoritative.
