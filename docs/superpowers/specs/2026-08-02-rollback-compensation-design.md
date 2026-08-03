# Rollback, Compensation, and Fencing Safety Design

**Status:** Approved for inline implementation under the P2 continuation approval.

**Goal:** Make rollback an explicit, approved, evidence-backed workflow that
cannot be inferred from task failure and cannot be continued by a stale owner.

## Scope

Rollback starts only from an explicit request containing operation IDs and
compensating actions. The planner reads the task operation ledger, validates
that every action references one known operation, and emits a dry-run plan.
Planning never executes a command or writes a side effect.

The executor accepts only an approved rollback plan and provider-confirmed
outcomes. It writes an immutable execution ledger. It does not execute shell
commands supplied in JSON; a provider owns the real side effect and returns
`COMPLETED`, `FAILED`, or `UNKNOWN` evidence. Unknown outcomes are never
retried automatically.

## Approval and Classification

Every plan is linked to `target_type=ROLLBACK` and its approval ID. Any action
marked `DESTRUCTIVE` requires an `APPROVED` record for that exact plan. A task
failure without an explicit rollback request produces no plan.

Execution is `ROLLED_BACK` only when every action completes. If one action
completes and a later action is failed, unknown, or blocked by a stale fencing
token, the ledger is `PARTIAL_ROLLBACK` and the workflow is `ESCALATED`.

## Fencing

Actions that touch a distributed resource carry a lock kind/key, owner ID, run
ID, and fencing token. The active distributed store validates this tuple before
the provider runs. A reclaimed lock has a higher token; an old owner therefore
cannot continue, heartbeat, release, or execute a compensation action.

## Runtime Evidence

Plans and ledgers are validated under `.agent/recovery/` by the canonical state
tools. Planning and execution append non-state evidence events. Recovery
inspection can surface rollback classification and evidence IDs without
assuming that a failed task was rolled back.
