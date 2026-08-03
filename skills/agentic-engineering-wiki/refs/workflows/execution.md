# Execution Workflow

1. Resolve runnable tasks from accepted dependencies and current state.
2. Select `ASYNC` only for independent, non-conflicting work; force `SYNC` for repairs, conflicts, recovery, or unaccepted dependencies.
3. Read the central config and select the model from the configured role entry; reject values outside `model_policy.allowed_models` or inside `model_policy.forbidden_models`.
4. Record a dispatch boundary with input revisions, owner, mode, approvals, and evidence.
5. Use locks, leases, checkpoints, operations, and events through `agentic-state-tools`.
6. Validate task state and handoff evidence before review.
