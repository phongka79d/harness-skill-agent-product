# Execution Workflow

1. Resolve runnable tasks from accepted dependencies and current state.
2. Resolve the deterministic skill route in process -> role -> domain order and load every skill in `required_skills`.
3. Select `ASYNC` only for independent, non-conflicting work; force `SYNC` for repairs, conflicts, recovery, or unaccepted dependencies.
4. Read the central config and deployment overlay, select the model from the configured role ref, and reject refs outside `model_policy.allowed_model_refs` or inside `model_policy.forbidden_model_refs`.
5. Record a dispatch boundary with input revisions, owner, mode, approvals, evidence, and the routing artifact. A `REPAIR_REQUIRED` task also requires a canonical, task-bound debugging investigation whose status is `ROOT_CAUSE_CONFIRMED` or `COMPLETED`.
6. Use locks, leases, checkpoints, operations, and events through `agentic-state-tools`.
7. Preserve the investigation ID through the repair dispatch identity chain and require matching root-cause and passing regression evidence before a `COMPLETE` handoff.
