# Context Contract

```yaml
task:
  task_id: "SP-01-B01-T01"
  objective: "..."
required_documents: []
code_context:
  files_to_read: []
  symbols_to_inspect: []
  existing_patterns: []
constraints:
  inherited: []
  task_specific: []
examples: []
review_history: []
budget: {}
```

The `budget` object is optional. When it is omitted, its canonical defaults are loaded from `agentic-configuration.context_budget`; any provided limits may only lower those configured maxima.

The context package is an input to the implementer. It is not a substitute for the task contract and must not authorize writes outside the task's declared scope.

Submit the package to `create_context.py`; do not hand-write `.agent/work/<task-id>/context.json`.
