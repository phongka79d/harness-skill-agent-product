# Review Workflow

1. Load the task or batch contract and the resolved rubric recorded with the artifact.
2. Verify acceptance criteria, scope, tests, required evidence, and every canonical hard-fail rule; record one `hard_fail_checks` evidence entry per rule.
3. Record findings with severity, evidence, and required change.
4. Calculate the result from the stored rubric; do not invent criteria or override hard fails.
5. Persist the review through `agentic-state-tools` and read the generated projection.

For staged task reviews, follow the [review contract](../../../agentic-task-reviewer/references/review-contract.md): `SPEC_COMPLIANCE` gates `CODE_QUALITY`, and a later implementation revision invalidates the prior stages. The contract and resolved rubric remain canonical; a quality score cannot make a missing specification requirement pass.

Resolve findings through [review feedback resolution](../../../agentic-implementer/references/review-feedback-resolution.md). Use evidence to accept, reject, clarify, supersede, or mark a correction `FIXED_PENDING_REREVIEW`; only a reviewer can mark it `CLOSED` after fresh re-review.
