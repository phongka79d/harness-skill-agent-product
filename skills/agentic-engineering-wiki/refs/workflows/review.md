# Review Workflow

1. Load the task or batch contract and the resolved rubric recorded with the artifact.
2. Verify acceptance criteria, scope, tests, required evidence, and every canonical hard-fail rule; record one `hard_fail_checks` evidence entry per rule.
3. Record findings with severity, evidence, and required change.
4. Calculate the result from the stored rubric; do not invent criteria or override hard fails.
5. Persist the review through `agentic-state-tools` and read the generated projection.
