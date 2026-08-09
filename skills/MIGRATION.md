# Migration

## From 3.5.1 to 3.6.0

1. Controlled linked worktrees now live OUTSIDE the project at `../<project-name>-worktrees/<task-id>` (a sibling directory of the project root) instead of `.phongka/worktrees/<task-id>`. The decision `path_template` changed, so regenerate workflow decisions. A previously bound worktree keeps its recorded identity; re-preparation requires finishing or explicitly cleaning the old binding first.
2. `.phongka/settings.json` is now schema version `2` and adds `execution` (`mode`, `dispatch_timeout_seconds`, `max_active_subagents`) and `primary_agent_fallback`. Run `load_runtime_settings.py --project-root <project> --ensure` once: it upgrades a v1 file in place and preserves your `subagent_wait` values. A v1 file read without `--ensure` fails closed.
3. The Plan Architect now authors human-readable plan documents (`MasterPlan.md` + `Plan-<N>.md`) that `init_runtime.py --plan-docs <staging>` installs into `.phongka/plan/<date>-<feature>/`; the runtime records `plan_binding.plan_path`. This is a state-only addition and does not require regenerating decisions.
4. The checklist view now includes a per-task table (Task, Status, Plan task, Scope, Updated); no configuration change is required.

## From 3.5.0 to 3.5.1

1. Central configuration schema version `5` adds required `subagent_policy.wait` defaults. Regenerate workflow decisions because the central configuration hash changes.
2. New stateful runtimes create `.phongka/settings.json` during `init_runtime.py`. For an already-active runtime, run `load_runtime_settings.py --project-root <project> --ensure` once; it does not rebind the task.
3. Existing valid settings are never overwritten. Invalid or unsupported settings fail closed and must be corrected explicitly.
4. Primary Agents must treat each wait-tool timeout as a non-terminal poll and apply `close_on_timeout` only after the configured total timeout and a final status check.

## From 3.4.1 to 3.5.0

1. Regenerate workflow decisions: decision and state schemas are now version `8` and include the `worktree` contract plus the complete `stages` and `required_skills` plans.
2. Reinitialize an existing runtime with the regenerated decision: `init_runtime.py --project-root <project> --decision <decision>`. The runtime rejects a decision created from a different configuration.
3. Controlled source-editing tasks must run `prepare_worktree.py --project-root <project> --approval-reference <reference>` before edits. Evidence scripts hash the bound worktree; a missing or mismatched worktree fails closed.
4. The project root must be a Git repository whose top level equals the project root before a controlled task can prepare a worktree.
5. The human progress view is rendered by `render_checklist.py` (the only checklist writer) into `.phongka/checklist/task-checklist-<task-id>.md`. Task IDs are selected explicitly, from the active task, or from the latest valid task-bound stage event. Older generic checklist README files are not deleted, but new renders do not create or rewrite them; reached-stage checkboxes do not mean task completion.
6. Delivery requires approval when the worktree contract requires delivery or cleanup approval, in addition to the workflow approval matrix.

## From 3.3.0 to 3.4.0

1. Treat task `scope` as unique normalized repository-relative file paths. Do not include absolute paths, parent traversal, `.phongka`, or `.agent`.
2. Include every scoped path in task review, batch review, and verification workspace snapshots.
3. Use stable acceptance IDs as `verification.checks[].name`; completion-claim acceptance IDs must be the exact same unique set.
4. Keep the persisted `.phongka/artifacts/<task-id>/completion-claim.json`; delivery now validates it against `completion-gate.json`.
5. Reconcile missing or orphan task files before continuing. Recovery returns `RECONCILE_TASK_INDEX` and performs no automatic deletion.
6. Omit CLI `--profile` to use central `default_profile`; custom configs must name an existing bundled profile.
7. Plans must use safe normalized paths. Two tasks that modify the same file require direct or transitive dependency ordering.
8. Add `run_contract_tests.py --skills-root skills` to package validation.
