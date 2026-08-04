---
name: agentic-state-tools
description: Use when project-local `.agent/` artifacts must be initialized, validated, updated, rebuilt, recovered, or rendered, including state, events, task/context records, reviews, locks, leases, and checklist status.
---

# Agentic State Tools

This skill is the only approved writer for canonical `.agent/` runtime artifacts. Agents submit structured payloads; these scripts validate and persist them.

Read `agentic-engineering-wiki` for shared state-boundary, workflow, recovery, approval, rubric, and contract routing before using these tools.

Read [agentic-configuration](../agentic-configuration/SKILL.md) before resolving agent roles, model dispatch, execution limits, approvals, or runtime paths.

**REQUIRED BACKGROUND:** Use `agentic-engineering-core` when the operation belongs to an agentic delivery workflow.

## Boundary

Allowed target: the current project's `.agent/` directory.

Never write skill instructions, reusable references, plans, task definitions, or human documentation into `.agent/`. Those belong in the workspace/project documentation area or global skill packages.

## Core commands

Run from the workspace or installed skill directory:

```text
python scripts/init_runtime.py --project-root <project>
python scripts/append_event.py --project-root <project> --input <event.json>
python scripts/update_task_state.py --project-root <project> --input <task-state.json>
python scripts/create_checkpoint.py --project-root <project> --input <checkpoint.json>
python scripts/create_handoff.py --project-root <project> --task-id <id> --input <handoff.json>
python scripts/create_review.py --project-root <project> --input <review.json>
python scripts/create_batch_contract.py --project-root <project> --plan <approved-plan.json> --plan-id <id> --plan-revision <n> --batch-id <id> --expected-revision <n> --actor primary-agent
python scripts/create_batch_review.py --project-root <project> --input <batch-review.json>
python scripts/create_context.py --project-root <project> --input <context.json>
python scripts/acquire_lock.py --project-root <project> --input <lock.json>
python scripts/release_lock.py --project-root <project> --input <release.json>
python scripts/record_heartbeat.py --project-root <project> --input <heartbeat.json>
python scripts/record_approval.py --project-root <project> --input <approval.json>
python scripts/record_operation.py --project-root <project> --input <operation.json>
python scripts/validate_state.py --project-root <project>
python scripts/rebuild_state.py --project-root <project>
python scripts/inspect_recovery.py --project-root <project> --task-id <id>
python scripts/render_checklist.py --project-root <project>
python scripts/validate_payload.py --input <payload.json> --schema schemas/task-state.schema.json
python scripts/validate_schema.py --input <payload.json> --schema schemas/task-state.schema.json
python scripts/validate_transition.py --current RUNNING --next COMPLETED
python scripts/validate_state_machine.py --input schemas/state-machine.json
python scripts/generate_state_artifacts.py --input schemas/state-machine.json
python scripts/distributed_store.py snapshot --store-root <remote-store>
python scripts/distributed_store.py append-event --store-root <remote-store> --input <event.json> --expected-revision <n> --expected-etag <sha256>
python scripts/calculate_rubric_score.py --input <review.json>
python scripts/validate_planning.py --input <planning-bundle.json>
python scripts/resolve_project_profile.py --profile <profile-id>
python scripts/resolve_rubric.py --profile <profile-id> --task-type <task-type> --risk-flags '{}'
python scripts/resolve_rubric.py --profile <profile-id> --task-type strict --review-type batch --risk-flags '{}'
python scripts/validate_change_request.py --input <change-request.json> --approval <approval.json>
python scripts/apply_change_request.py --request <change-request.json> --target <old-plan.json> --approval <approval.json> --output <new-plan.json>
python scripts/resolve_runnable_tasks.py --input <queue.json>
python scripts/resolve_execution_mode.py --input <task.json>
python scripts/validate_dependency_graph.py --input <planning-bundle.json>
python scripts/detect_scope_overlap.py --input <tasks.json>
python scripts/compute_critical_path.py --input <graph.json>
python scripts/reconcile_queue.py --input <queue.json>
python scripts/dispatch_task.py --project-root <project> --input <dispatch.json>
python scripts/worktree_manager.py --project-root <git-project> --worktree-root <external-root> --task-id <id> --revision <n>
python scripts/merge_worktree.py --project-root <git-project> --worktree-root <external-root> --task-id <id> --revision <n> --target-branch <branch> --approval <approval.json> --actor <actor-id> --actor-type user
python scripts/commit_batch.py --project-root <project> --batch-id <id> --approval <approval.json> --actor <id> --actor-type user --message <message> --path <path>
python scripts/next_batch.py --project-root <project> --current-batch-id <id> --next-batch-id <id> --approval <approval.json> --actor <id> --actor-type user
python scripts/validate_examples.py --examples-root examples --deployment <deployment.json>
python scripts/package_skill.py --root <package-root> --output <release.zip>
python ../agentic-configuration/scripts/load_config.py --check
python scripts/capture_workspace.py --project-root <project>
python scripts/verify_terminal_cleanup.py --project-root <project> --task-id <id>
python scripts/plan_rollback.py --project-root <project> --input <rollback-request.json>
python scripts/execute_rollback.py --project-root <project> --plan-id <id> --approval <approval.json> --outcomes <provider-outcomes.json>
```

## Guarantees

- Validate before writing.
- Generate IDs and timestamps when omitted.
- Enforce revisions and allowed transitions.
- Enforce task, file, and resource lock ownership plus lease identity.
- Record idempotent side-effect operations and block unsafe retries.
- Write JSON atomically.
- Append immutable events.
- Rebuild snapshots from the event journal.
- Derive task and batch review outcomes from accepted evidence.
- Require a canonical review contract and complete evidence-backed hard-fail checks for every non-legacy rubric review.
- Validate planning schemas and cross-document dependencies before execution.
- Resolve immutable project profiles and task rubrics with IDs, versions, hashes, applicability, weights, and thresholds.
- Reconcile active recovery with the actual Git workspace when checkpoint evidence is present.
- Remove terminal task leases and owned locks with journal evidence.
- Resolve runnable tasks, execution mode, dependencies, and scope conflicts without mutating runtime state.
- Validate queue and dependency graph contracts, compute a deterministic critical path, and reconcile queue/task/dispatch evidence.
- Accept dispatch models only when `selected_model` matches the configured `agent_role` and deployment overlay; do not duplicate model literals in state-tools.
- Persist each dispatch to queue, graph, lease, task state, operation ledger, and event journal with a run ID, attempt ID, revision, idempotency key, and configured capacity check.
- Reject async dispatch while isolated worktree support is disabled.
- Keep async task-to-branch-to-worktree mappings isolated, lease-bound, merge-fenced, and recoverable after conflict.
- Require exact typed approval identity, target revision, target hash, policy version, and persisted approval evidence before protected side effects.
- Require canonical batch task-set equality and matching task-review contracts before an integrated batch can pass.
- Create `.agent/work/<batch-id>/batch-contract.json` only through `create_batch_contract.py`; direct writes are rejected for non-legacy reviews.
- Persist approval records through the same validated artifact and event path.
- Require approved Primary-owned records for architecture, plan, profile, and rubric overrides.
- Apply plan changes only as new versioned artifacts with immutable supersede links.
- Capture workspace evidence once and reuse it for checkpoint and recovery reconciliation.
- Refuse live-owner lock reclaim and prove terminal cleanup before reporting a clean terminal state.
- Render `.agent/checklist.md` from canonical task state and reviews.
- Return non-zero exit codes for invalid payloads or unsafe state.

Rollback is explicit and evidence-backed. `plan_rollback.py` only creates a
dry-run plan from known operation IDs; a failed task alone cannot create one.
`execute_rollback.py` requires an exact `ROLLBACK` approval, accepts provider
outcomes rather than executing arbitrary commands, records immutable ledger and
evidence artifacts, and escalates partial or stale-owner compensation without
automatic retry.

The `distributed_store.py` adapter exposes a backend-neutral remote-state
contract. Its file-backed store is a deterministic reference backend, not a
second project runtime. Event appends require both revision and etag, identical
event IDs are idempotent, conflicting IDs are rejected, and distributed locks
are bound to owner, run, and fencing token. The HTTP client sends one mutation
request with an idempotency key and reports transport uncertainty as
`NETWORK_UNCERTAIN`; it never retries an uncertain side effect automatically.

If validation fails, do not hand-edit the target artifact. Return the error to the agent, allow one focused correction, then mark the workflow blocked or escalated.

Read [artifact-contracts.md](references/artifact-contracts.md) and [cli-behavior.md](references/cli-behavior.md).
