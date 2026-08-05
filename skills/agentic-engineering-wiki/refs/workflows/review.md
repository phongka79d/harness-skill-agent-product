# Review Workflow

1. Load the task or batch contract and the resolved rubric recorded with the artifact.
2. Verify acceptance criteria, scope, tests, required evidence, and every canonical hard-fail rule; record one `hard_fail_checks` evidence entry per rule.
3. Record findings with severity, evidence, and required change.
4. Calculate the result from the stored rubric; do not invent criteria or override hard fails.
5. Persist the review through `agentic-state-tools` and read the generated projection.

For staged task reviews, `SPEC_COMPLIANCE` is the gate before `CODE_QUALITY`.
Stage ordering, re-review invalidation, and the final artifact identity are checked
by `review_contract.py`; a quality score cannot make a missing specification
requirement pass. Batch consumers use the profile's required final stage: lightweight
profiles may finish at specification compliance, while standard and strict profiles
require both stages with the same implementation identity.
