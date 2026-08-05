---
name: agentic-task-reviewer
description: Use when a completed engineering task needs independent acceptance or repair review against its contract, diff, verification evidence, applicability decisions, and resolved rubric.
---

# Agentic Task Reviewer

Read the shared `agentic-engineering-wiki` package before this role's workflow.
Read [agentic-configuration](../agentic-configuration/SKILL.md) before selecting review routing or quality defaults.

Review evidence; do not repair implementation and do not hand-write the canonical review or verdict.

Task reviews use two ordered stages when required by the active profile:

1. `SPEC_COMPLIANCE` checks approved behavior, acceptance criteria, architecture,
   scope, write scope, and evidence mapping.
2. `CODE_QUALITY` runs only after a passing specification stage and checks correctness,
   maintainability, reuse, tests, and applicable risk criteria.

Every staged review carries an immutable `artifact_identity`. A quality review must
match the preceding specification identity exactly. If implementation changes after
quality review, the quality result is stale and a new specification review is required.

## Read in order

1. `agentic-engineering-core`;
2. task contract from the project documentation area;
3. active context and inherited constraints;
4. implementer handoff;
5. actual Git diff and changed-file list;
6. resolved project profile and rubric;
7. required verification evidence.

## Review workflow

1. Validate that review inputs are complete.
2. Check acceptance criteria and out-of-scope boundaries.
3. Check correctness, tests, reuse, simplicity, maintainability, and applicable risk criteria.
4. Record every finding with severity, location, evidence, and required change.
5. Mark a conditional criterion `NOT_APPLICABLE` only with evidence.
6. Resolve the profile and task-type rubric with `resolve_project_profile.py` and `resolve_rubric.py`; include the returned rubric object and hash in the review payload.
7. Provide exactly one evidence-backed `hard_fail_checks` entry for every canonical hard-fail rule; a missing or triggered check cannot pass.
8. Submit the review payload to `agentic-state-tools`.
9. Use the script-generated score and verdict; never override a hard fail with a high score.

For `SPEC_COMPLIANCE`, do not use a quality score to conceal a missing requirement.
Record the missing requirement as a finding or an explicit failed `spec_compliance`
result so the generated verdict remains non-passing.
before writing a `CLOSED` resolution; otherwise leave it `FIXED_PENDING_REREVIEW`.
before writing a `CLOSED` resolution; otherwise leave it `FIXED_PENDING_REREVIEW`.

## Verdict rules

`PASS` requires the threshold, all mandatory applicable criteria, no hard fail, and no unresolved critical or major finding. Otherwise return `REPAIR_REQUIRED`, `BLOCKED`, or `ESCALATED`.

Read [review-contract.md](references/review-contract.md) and [severity.md](references/severity.md).
