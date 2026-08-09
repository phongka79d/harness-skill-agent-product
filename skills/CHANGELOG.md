# Changelog

## Unreleased

- Controlled linked worktrees moved out of the project to `../<project-name>-worktrees/<task-id>` (sibling directory) while keeping native `git worktree`; identity schemas and decision path templates now use `../{project_name}-worktrees/{task_id}`, and preparation/verification enforce the sibling base.
- The Plan Architect now authors human-readable plan documents (`MasterPlan.md` + `Plan-<N>.md`, Master Plan -> Plan N -> Batches -> Tasks -> Steps) in its staging scope; `init_runtime.py --plan-docs` installs them into `.phongka/plan/<date>-<feature>/` and records `plan_binding.plan_path`.
- The checklist view adds a per-task table (Task, Status, Plan task, Scope, Updated) while keeping the compact stage view.
- Runtime settings schema version `2` adds `execution` (`mode` sync/async, `dispatch_timeout_seconds`, `max_active_subagents`) and `primary_agent_fallback`, with automatic v1-to-v2 migration that preserves user `subagent_wait` values.
- Hardened delegated-role contracts: roles are non-orchestrating, non-state-mutating leaves; only the Primary may orchestrate multiple independent tasks, read-only work may parallelize, and writers remain sequential. Added the external `HOST-0` fail-closed attestation boundary, `open_task`/worktree identity mapping, Core-only public entrypoint, declared host-owned debugger scratch scope, and exact universal handoff fields.
- Added the package-local `i-have-adhd` companion skill and config-backed loading immediately after core for every resolved workflow, with generic package validation and route/state ordering coverage.
- Made `agentic-engineering-core` the sole explicit workflow entrypoint for host slash-list selection, `$agentic-engineering-core`, `/agentic-engineering-core` prompt text, implicit repository work, and continuation of the current active `.phongka` workflow/task.
- Added explicit Primary ownership, automatic route/depth resolution, ordered `required_skills` loading, host-truth activation guidance, implicit invocation metadata, and regression validation for the entrypoint contract.

## 3.5.1

- Added central subagent wait defaults and user-editable `.phongka/settings.json` with validated check interval, total timeout, and close-on-timeout policy.
- Runtime initialization now creates missing settings atomically, preserves existing user values, and fails closed on invalid settings.
- Clarified that a wait-tool timeout is a non-terminal poll result; a running subagent cannot be closed before its total deadline.
- Added adversarial and smoke coverage for settings creation, custom-config defaults, preservation, and invalid-policy rejection.
- Corrected stale package version and state-default documentation.
- Changed checklist rendering to preserve one task-specific `.phongka/checklist/task-checklist-<task-id>.md` per task, retain independent task context after terminal transitions, and check every stage reached through the recorded current stage. Existing legacy checklist README files are not deleted.

## 3.5.0

- Added deterministic Git worktree isolation for controlled source-editing tasks (`worktree.py`, `prepare_worktree.py`). Controlled source-editing decisions set `worktree.required`, bind a deterministic path/branch per task, and require approval before preparation.
- Added the initial human progress view: `render_checklist.py` records one small `WORKFLOW_STAGE_UPDATED` event per refresh and renders route, depth, current stage/skill, stage position, and task status. Later releases made the view task-specific.
- Raised decision and state schemas to version 8 with `worktree` contract and `worktree_identity` binding; evidence, review, and batch-review scripts hash the bound worktree.
- Recovery now detects worktree path, branch, HEAD, and dirty-state mismatches and returns a precise `INSPECT_WORKTREE_*` or `RECONCILE_WORKTREE_DIRTY` action.
- Delivery requires approval when the worktree contract requires delivery or cleanup approval.
- Expanded adversarial contract coverage to 51 cases, including controlled worktree preparation/binding, approval boundary, path/branch/HEAD/dirty mismatch recovery, and unsupported-schema constraints.

## 3.4.1

- Revalidated persisted workflow decisions against the current central configuration and added a configuration hash to decision/state contracts.
- Made optional state execution explicit by emitting runtime state actions only when state is required.
- Reused runtime invariant validation during recovery and rejected case-insensitive task ID collisions.
- Rejected blank verification/acceptance IDs, unsafe symlink packaging, and unsupported JSON Schema keywords.
- Expanded adversarial contract coverage for decision tampering, optional state, recovery invariants, task ID collisions, and blank evidence IDs.
