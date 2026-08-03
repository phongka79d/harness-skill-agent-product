# Exploration Protocol

Use this compact report shape:

```yaml
status: COMPLETE | BLOCKED
summary: "..."
files_read:
  - path: "src/example.ts"
    symbols: ["ExampleService"]
findings:
  - category: existing_pattern
    evidence: "..."
    location: "src/example.ts:12"
unknowns:
  - "..."
risks:
  - "..."
next_steps:
  - "..."
```

Use `BLOCKED` when the task contract, required context, or authorization is missing. The report itself may be returned to the Primary Agent; do not write it into `.agent/` by hand.
