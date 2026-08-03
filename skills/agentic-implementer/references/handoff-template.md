# Implementer Handoff

```yaml
status: COMPLETE | BLOCKED | ESCALATED
summary: "..."
files_read: []
files_changed: []
findings: []
implementation_details: []
validation_results:
  - command: "..."
    result: PASS | FAIL | NOT_RUN
    evidence: "..."
risks: []
next_steps: []
```

Do not call a task complete when required verification is `NOT_RUN` or when an unresolved blocker affects an acceptance criterion.
