# Architecture

The runtime follows Model A:

- Reusable instructions, references, schemas, scripts, and tests live in installed skill packages under `skills/`.
- Project plans, decisions, risks, and task definitions live in the project documentation area, normally `docs/agentic/`.
- Generated runtime state, event journals, locks, leases, checkpoints, reviews, and projections live under the project `.agent/` directory.

The Primary Agent remains the architecture owner. The Harness records and validates queue, dependency, dispatch, recovery, and approval decisions; it does not become a second architecture owner.

The canonical state machine is `skills/agentic-state-tools/schemas/state-machine.json`. Its validator must pass before consumers or schemas are released.

## Ownership map

Keep detailed rules in the owning package and route to them from the Wiki:

| Concern | Canonical owner |
|---|---|
| Product or code defect investigation | [systematic debugging](../../../agentic-systematic-debugging/SKILL.md) |
| Interrupted runs, stale leases, or uncertain side effects | [runtime recovery](../../../agentic-runtime-recovery/SKILL.md) |
| Attempt-bound context and context deltas | [context builder](../../../agentic-context-builder/SKILL.md), [context contract](../../../agentic-context-builder/references/context-contract.md) |
| Workspace baseline and isolation evidence | [baseline capture](../../../agentic-state-tools/scripts/capture_workspace_baseline.py), [async contract](../contracts/async-execution.md) |
| Delivery outcomes, merge, and cleanup fencing | [delivery finalizer](../../../agentic-delivery-finalizer/SKILL.md), [delivery safety](../../../agentic-delivery-finalizer/references/merge-and-cleanup-safety.md) |

The Wiki routes these boundaries; it does not replace the owning skill, state
tool, or contract with a second implementation of the rule.
