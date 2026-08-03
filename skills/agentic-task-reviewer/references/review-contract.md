# Review Contract

```yaml
review_id: "REV-SP-01-B01-T01"
task_id: "SP-01-B01-T01"
review_type: task
criteria:
  - id: CORRECTNESS
    score: 4
    weight: 25
    applicability: APPLICABLE
    evidence: "..."
findings: []
hard_fail: false
reviewer: "task-reviewer"
```

Scores are inputs. The deterministic scoring script calculates the weighted percentage and final verdict.
