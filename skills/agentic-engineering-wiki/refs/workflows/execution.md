# Execution Workflow

1. Resolve runnable tasks from accepted dependencies and current state.
2. Resolve the deterministic skill route in process -> role -> domain order and load every skill in `required_skills`.
3. Select exactly one mode from the [execution modes contract](../contracts/async-execution.md):
   - use `SYNC_WRITE` for implementation, repairs, recovery, conflicts, unaccepted dependencies, or any work whose async proof is incomplete;
   - use `PARALLEL_READ_ONLY` only when each explorer has an independent question, writes are forbidden, context and capacity are available, explorers do not depend on one another, and reports can be reconciled deterministically;
   - use `ASYNC_ISOLATED_WRITE` only when configuration opt-in, accepted dependencies, disjoint scopes, capacity, lease, and verified task-to-branch-to-worktree isolation are all present.
4. For `PARALLEL_READ_ONLY`, collect protocol-compliant reports, preserve their inspected files and evidence, and reconcile conflicts or material unknowns before implementation. No worktree is required and no write may be delegated.
5. Read the central config and deployment overlay, select the model from the configured role ref, and reject refs outside `model_policy.allowed_model_refs` or inside `model_policy.forbidden_model_refs`.
6. For `ASYNC_ISOLATED_WRITE`, record a dispatch boundary with input revisions, owner, mode, approvals, evidence, and the verified isolation proof. A `REPAIR_REQUIRED` task also requires a canonical, task-bound debugging investigation whose status is `ROOT_CAUSE_CONFIRMED` or `COMPLETED`.
7. Use locks, leases, checkpoints, operations, and events through `agentic-state-tools`.
8. Preserve the investigation ID through the repair dispatch identity chain and require matching root-cause and passing regression evidence before a `COMPLETE` handoff.
9. Build a fresh context for every attempt. Bind it to task/run/attempt/dispatch identity, retain immutable context lineage, and require a meaningful context delta before reissuing a failed or blocked attempt. Reviewers receive contract and evidence, never implementer private reasoning.
10. Merge isolated writes sequentially only with the required approval and fresh target-branch validation. Neither async workers nor the Batch Reviewer performs an automatic merge.

Async write remains disabled unless the current configuration explicitly enables
it. Read-only parallel exploration and async implementation are independent
capabilities: enabling the former never implies enabling the latter.
