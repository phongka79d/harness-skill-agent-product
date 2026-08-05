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
context_revision: 1
context_purpose: "IMPLEMENTATION"
recipient_role: "IMPLEMENTER"
run_id: "RUN-..."
attempt_id: "ATTEMPT-..."
dispatch_id: "DISPATCH-..."
source_items: []
source_hashes: []
inclusion_reasons: []
excluded_sensitive_items: []
forbidden_scope: []
previous_context_id: null
context_delta: null
```

The `budget` object is optional. When it is omitted, its canonical defaults are loaded from `agentic-configuration.context_budget`; any provided limits may only lower those configured maxima.

The context package is an input to the implementer. It is not a substitute for the task contract and must not authorize writes outside the task's declared scope.

For a reviewer, set `recipient_role` to `REVIEWER` and include only the active contract, approved decisions, changed files or diff, verification evidence, rubric, and relevant prior findings. Do not include private reasoning, confidence statements, or unrelated user data. `source_hashes` are stable SHA-256 identities for the corresponding `source_items`.

The latest `context.json` is a compatibility projection. New contexts are also retained under `work/<task-id>/contexts/<context-id>.json`; a fresh attempt links to the prior context with `previous_context_id`. A reissue must carry a non-empty `context_delta` describing a corrected contract, context addition/removal, decomposition, model escalation, approved decision, or new debugging evidence. Reissue is rejected when the current attempt has no context package; the caller must build the package first so every new attempt has an auditable context lineage.

Submit the package to `create_context.py`; do not hand-write `.agent/work/<task-id>/context.json`.
