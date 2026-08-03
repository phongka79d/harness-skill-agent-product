# Rubric Contract

A resolved rubric records profile ID and version, profile hash, task or batch type, criteria, weights, applicability evidence, threshold, hard-fail rules, and its own hash. The same inputs and approved overrides produce byte-identical output. Review artifacts store the resolved rubric or a clearly marked legacy migration reference. For a canonical rubric, the review must also provide exactly one evidence-backed `hard_fail_checks` entry for every canonical hard-fail rule; triggered checks force repair regardless of weighted score.
