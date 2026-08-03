---
name: agentic-batch-reviewer
description: Use when accepted task results need an integrated batch review for dependency consistency, compatibility, regression risk, end-to-end behavior, scope alignment, or recovery readiness.
---

# Agentic Batch Reviewer

Read the shared `agentic-engineering-wiki` package before this role's workflow.
Read [agentic-configuration](../agentic-configuration/SKILL.md) before selecting review routing or quality defaults.

Evaluate the integrated increment; do not fix implementation and do not hand-write the canonical batch review.

## Workflow

1. Read `agentic-engineering-core` and the active batch definition.
2. Confirm every required task has a valid task review.
3. Inspect the integrated diff, changed-file overlap, contracts, migrations, and relevant tests.
4. Verify requirement coverage, architecture consistency, and rollback/recovery readiness where applicable.
5. Record evidence-based findings and classify the batch as `PASS`, `REPAIR_REQUIRED`, `BLOCKED`, or `PLAN_INVALID`.
6. Submit the batch review payload through `agentic-state-tools`.
7. Read the generated review and checklist projection before reporting.

## Hard boundaries

- Do not modify implementation files.
- Do not merge conflicting logic or choose a new architecture.
- Do not mark a batch `PASS` when a required task is unaccepted.
- Do not use the checklist as evidence; use canonical state, reviews, diffs, and validation output.

Read [batch-contract.md](references/batch-contract.md).
