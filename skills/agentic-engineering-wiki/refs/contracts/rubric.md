# Rubric Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/calculate_rubric_score.py`)

A resolved rubric records profile ID and version, profile hash, task or batch
type, criteria, weights, applicability evidence, threshold, hard-fail rules,
and its own hash. The same inputs and approved overrides produce byte-identical
output. Review artifacts store the resolved rubric or a clearly marked legacy
migration reference.

For a canonical rubric, the review must provide exactly one evidence-backed
`hard_fail_checks` entry for every canonical hard-fail rule. Triggered checks
force repair regardless of weighted score. The scorer derives the weighted
percentage and verdict; reviewer-supplied thresholds, weights, mandatory flags,
minimum scores, or verdicts are not authoritative.

Use `resolve_rubric.py` to create the immutable contract and
`calculate_rubric_score.py --input <review.json>` to calculate the result.
Applicability must include evidence, and `N/A` without evidence is rejected.
