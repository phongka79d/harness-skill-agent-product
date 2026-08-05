# Execution Workflow

1. Resolve runnable tasks from accepted dependencies and current state.
2. Resolve the deterministic skill route in process -> role -> domain order and load every skill in `required_skills`.
3. Select exactly one mode using the [execution modes contract](../contracts/async-execution.md). Treat `SYNC_WRITE` as the safe default; the contract owns eligibility, fallback, and the disabled-by-default rule for async writes.
4. For `PARALLEL_READ_ONLY`, follow the [exploration protocol](../../../agentic-explorer/references/exploration-protocol.md), preserve inspected files and evidence, and reconcile conflicts or material unknowns before implementation. No write may be delegated.
5. Read the central config and deployment overlay, select the model from the configured role ref, and reject refs outside `model_policy.allowed_model_refs` or inside `model_policy.forbidden_model_refs`.
6. For an isolated write, require the [workspace baseline schema](../../../agentic-state-tools/schemas/workspace-baseline.schema.json) and [baseline capture command](../../../agentic-state-tools/scripts/capture_workspace_baseline.py), then verify its identity against the worktree proof. A `REPAIR_REQUIRED` task also requires the task-bound debugging investigation defined by the [debugging skill](../../../agentic-systematic-debugging/SKILL.md).
7. Build a fresh attempt package through the [context builder](../../../agentic-context-builder/SKILL.md), preserving task/run/attempt/dispatch identity and a meaningful context delta for reissues. Reviewers receive contract and evidence, never private reasoning.
8. Use locks, leases, checkpoints, operations, and events through `agentic-state-tools`; preserve the investigation ID and require matching root-cause and regression evidence before a `COMPLETE` handoff.
9. Apply the [testing contract](../contracts/testing.md) and [verification gate](../../../agentic-verification-before-completion/SKILL.md) for RED/GREEN/BROAD evidence and fresh completion claims.
10. Record one controlled delivery outcome through the [delivery finalizer](../../../agentic-delivery-finalizer/SKILL.md) before any merge, push, or discard side effect.
11. Merge isolated writes sequentially with required approval and fresh target-branch validation. Neither async workers nor the Batch Reviewer performs an automatic merge.
