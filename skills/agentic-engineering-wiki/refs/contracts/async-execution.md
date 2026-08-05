# Execution Modes and Async Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/resolve_execution_mode.py` and dispatch validation)

Harness has three execution modes. Selecting a mode does not grant permissions
outside the task's approved read and write scopes.

This is the canonical mode-eligibility contract. Use the [exploration protocol](../../../agentic-explorer/references/exploration-protocol.md) for read-only reports, the [context builder](../../../agentic-context-builder/SKILL.md) for attempt-bound context, and the [baseline capture command](../../../agentic-state-tools/scripts/capture_workspace_baseline.py) for isolated-worktree baseline evidence.

| Mode | Purpose | Writes | Eligibility and default |
| --- | --- | --- | --- |
| `SYNC_WRITE` | Execute implementation, repair, recovery, or other work that changes the repository or runtime state. | Allowed only within the approved scope and state-tool boundaries. | Safe default for all work; required when async conditions are not proven. |
| `PARALLEL_READ_ONLY` | Run independent explorer investigations concurrently to gather evidence. | Prohibited, including source, tests, docs, `.agent/`, branches, worktrees, and runtime artifacts. | Eligible only when every read-only condition below is satisfied. It does not enable async implementation. |
| `ASYNC_ISOLATED_WRITE` | Execute independent implementation tasks concurrently in isolated workspaces. | Allowed only in the task's disjoint isolated scope. | Eligible only after every async condition below is satisfied and configuration explicitly opts in. |

## `PARALLEL_READ_ONLY` eligibility

Parallel exploration is eligible only when all of these conditions hold:

- each explorer has an independent investigation question;
- every explorer is explicitly forbidden from writing (`write_forbidden: true` and an empty `write_scope`);
- context and token capacity are available for every explorer (`context_capacity_available: true` and `token_capacity_available: true`);
- no explorer depends on another explorer's result to begin or complete its investigation;
- outputs have a deterministic reconciliation procedure, including `reconciliation_contract.order: [task_id, path, symbol]`, preserved source locations, and blocking conflict/material-unknown policies.

No branch or worktree is required because writes are prohibited. Read-only
parallelism may be enabled while `ASYNC_ISOLATED_WRITE` remains disabled. Each
report follows `skills/agentic-explorer/references/exploration-protocol.md`,
and conflicting findings or material unknowns are resolved before implementation
starts.

## `ASYNC_ISOLATED_WRITE` eligibility

Retain all existing Harness requirements:

- configuration explicitly enables async capability and permits task opt-in;
- all dependencies are accepted and no recovery, repair, or conflict guard forces synchronous execution;
- write scopes are disjoint from active work;
- execution capacity and a valid lease are available;
- an isolation proof is verified before dispatch;
- a workspace baseline is captured for the exact external worktree and base
  commit; `CLEAN` or explicitly approved known failures are required before
  implementation;
- task-to-branch-to-worktree identity is bound to the task, run, attempt, dispatch, base commit, plan revision, and write-scope hash;
- merges remain sequential and approval-backed; async workers and the Batch Reviewer do not merge automatically.

The isolation proof must bind task ID, run ID, external worktree path, branch,
base commit, plan revision, write-scope hash, conflict-check timestamp, and
`isolation_status: VERIFIED`. Missing, stale, or mismatched proof falls back to
`SYNC_WRITE` when fallback is allowed, or blocks an explicitly required async
request.

The baseline contract is owned by the [baseline capture command](../../../agentic-state-tools/scripts/capture_workspace_baseline.py). It verifies
the Git worktree identity before running explicitly approved, shell-free setup
and baseline commands. Existing failures are listed separately and can only be
carried forward through an explicit approval token; unexpected failures produce
`BLOCKED`. A baseline from another worktree or base commit is rejected.

`ASYNC_ISOLATED_WRITE` is disabled by default. It must not be inferred from
available capacity, a request for parallelism, or the eligibility of
`PARALLEL_READ_ONLY`; the current configuration must explicitly enable it and
the task must explicitly opt in. A completed isolated task still requires
sequential, approval-backed merge and fresh validation on the target branch.

Dispatch persists queue, dependency, lease, task, and operation identity through
`dispatch_transaction.py`; run ID, attempt ID, dispatch ID, revision, and
idempotency key remain bound throughout the attempt.

Recovery classifications are `SAFE_TO_RESUME`, `NEEDS_RECONCILIATION`, and
`UNSAFE_TO_RESUME`. Unknown side effects, workspace mismatch, stale identity,
or an invalid ledger require reconciliation or escalation.

Multi-machine scheduling, remote lock services, and remote async execution are
NOT_IMPLEMENTED because no release-backed remote implementation exists.
