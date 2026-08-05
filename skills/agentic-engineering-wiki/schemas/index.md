# Schema Index

Policy status: VALIDATED_ONLY

The installed state-tools package owns executable schemas for task state, events, planning, queues, dispatch, reviews, approvals, locks, leases, checkpoints, operations, and recovery. The authoritative state source is `skills/agentic-state-tools/schemas/state-machine.json`; its consumer schemas must match its enum sets.

Validate the Wiki links with `scripts/validate_wiki_links.py`. Validate the
state source with `skills/agentic-state-tools/scripts/validate_state_machine.py`.
Use `validate_payload.py` or the owning runtime command for payload behavior;
the presence of a schema field alone does not establish enforcement.

The release-backed contract set includes task state, planning, handoff,
batch-contract, dispatch, isolation-proof, transaction, change-request,
approval, review, lock, lease, checkpoint, operation, recovery,
verification-evidence, and completion-claim schemas.
Distributed and remote schemas are descriptive until a command and release
test consume them.

## Cross-package schema routes

The Wiki indexes schema ownership; it does not duplicate executable definitions:

- Skill behavior scenarios: [behavior-scenario schema](../../agentic-skill-authoring/schemas/behavior-scenario.schema.json) and [scenario runner](../../agentic-skill-authoring/scripts/run_behavior_scenarios.py).
- Attempt context and lineage: [context contract](../../agentic-context-builder/references/context-contract.md) and [context schema](../../agentic-state-tools/schemas/context.schema.json).
- Execution modes and isolation: [async contract](../refs/contracts/async-execution.md), [execution-policy schema](../../agentic-state-tools/schemas/execution-policy.schema.json), and [isolation-proof schema](../../agentic-state-tools/schemas/isolation-proof.schema.json).
- Workspace baseline: [baseline schema](../../agentic-state-tools/schemas/workspace-baseline.schema.json) and [baseline capture](../../agentic-state-tools/scripts/capture_workspace_baseline.py).
- Staged review and feedback: [review contract](../../agentic-task-reviewer/references/review-contract.md), [review schema](../../agentic-state-tools/schemas/review.schema.json), and [resolution schema](../../agentic-state-tools/schemas/review-resolution.schema.json).
- Delivery and cleanup: [delivery decision schema](../../agentic-state-tools/schemas/delivery-decision.schema.json) and [delivery finalizer](../../agentic-delivery-finalizer/SKILL.md).
