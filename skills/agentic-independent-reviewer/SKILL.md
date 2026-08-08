---
name: agentic-independent-reviewer
description: Use only when dispatched by agentic-engineering-core for fresh read-only review of a plan, completed task, or integrated multi-task change.
---

# Agentic Independent Reviewer

## Contract

- **Owner:** Primary Agent dispatches a fresh reviewer.
- **Boundary:** Read-only; never repairs its own findings.
- **Canonical rubric:** Read [review-rubrics.json](references/review-rubrics.json) before reviewing. Use exactly the rubric for the requested mode; criteria are gate checks, not scores.
- **Evidence contract:** Report `review_mode`, `review_rubric_id`, `review_rubric_version`, and exactly one PASS, FAIL, or NOT_APPLICABLE evidence result for every canonical criterion. NOT_APPLICABLE evidence must state its reason.
- **Mode mapping:** `plan_review → plan`, `review → task`, `batch_review → integration`.
- **Prompt:** [reviewer.md](prompts/reviewer.md), appended after `agentic-engineering-core/prompts/subagent-envelope.md`.
- **Return:** `PASS`, `REPAIR_REQUIRED`, or `BLOCKED` with exact evidence and next step.

## Workflow

1. Validate the supplied scope, artifact, acceptance criteria, and review mode.
2. Resolve the matching canonical rubric id and version, then evaluate every criterion with direct evidence.
3. Read only the minimum evidence needed for that mode.
4. Report only actionable findings that affect correctness, safety, acceptance, or delivery.
5. Bind task and integration review to the exact reviewed work revision, workspace paths, and hashes. Integration review may inspect implemented work while the final task is still `IN_PROGRESS`; completion remains a later gate.
6. Return repairs to the responsible implementer or planner.
7. Re-review the repaired bounded scope before verification.

Read [review modes](references/review-modes.md) and [severity](references/severity.md). Do not infer permission, broaden scope, rewrite the artifact, or block on preference-only style.
