# Execution Workflow

1. Resolve runnable tasks from accepted dependencies and current state.
2. Select `ASYNC` only for independent, non-conflicting work; force `SYNC` for repairs, conflicts, recovery, or unaccepted dependencies.
3. Read the central config and deployment overlay, select the model from the configured role ref, and reject refs outside `model_policy.allowed_model_refs` or inside `model_policy.forbidden_model_refs`.
4. Record a dispatch boundary with input revisions, owner, mode, approvals, and evidence.
5. Use locks, leases, checkpoints, operations, and events through `agentic-state-tools`.
6. Validate task state and handoff evidence before review.
