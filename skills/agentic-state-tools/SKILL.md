---
name: agentic-state-tools
description: Use deterministic scripts to resolve workflows and manage project-local `.phongka` state for resolved required workflows; preserve explicit stateless opt-outs; never use them as an autonomous agent runtime.
---

# Agentic State Tools

The Primary Agent classifies intent and resolves the state mode. When the decision says `state_mode: required`, initialize the project-local `.phongka` runtime before executing the route. These scripts validate and expand that decision, bind state/evidence, and fail closed on invalid transitions.

## State authority and host boundary

`.phongka` is a Primary Agent/host-owned state boundary. Delegated model roles may read state when assigned, but they never write, delete, or repair runtime files, task files, artifacts, checklist files, or evidence indexes, and they never invoke a state-mutating CLI on their own. Only the Primary Agent or the host invokes these deterministic scripts at approved lifecycle points; urgency, triviality, unrelated cleanup, and generated/config-only labels do not change that boundary. The scripts are not an autonomous agent runtime and do not grant roles orchestration authority.

## Stateless path

The stateless path applies only when the resolved decision explicitly says `state_mode: off`. In that case, do not create `.phongka`. Run only required skills and report fresh evidence directly.

## Required-state path

```bash
python scripts/resolve_workflow.py --profile personal --task-route feature --estimated-files 3 --output /tmp/decision.json
python scripts/init_runtime.py --project-root <project> --decision /tmp/decision.json
python scripts/load_runtime_settings.py --project-root <project>
python scripts/prepare_worktree.py --project-root <project> --approval-reference <reference>
```

Use the same `--config` path (or `AGENTIC_CONFIG_FILE`) for both commands when a non-default central configuration is used.

Canonical runtime files:

```text
.phongka/settings.json
.phongka/state.json
.phongka/events.jsonl
.phongka/tasks/<task-id>.json
.phongka/artifacts/<task-id>/verification.json
.phongka/artifacts/<task-id>/completion-claim.json
.phongka/artifacts/<task-id>/completion-gate.json
.phongka/artifacts/<task-id>/review.json
.phongka/artifacts/<task-id>/worktree-cleanup.json
.phongka/batch-review.json
.phongka/delivery-decision.json
.phongka/checklist/task-checklist-<task-id>.md
.phongka/plan/manifest.json
.phongka/plan/review.json
.phongka/plan/<date>-<feature>/*.md
```

`init_runtime.py` creates `settings.json` (schema version 2) from central `subagent_policy` and `execution` defaults when it is missing and validates but never overwrites an existing file; a schema v1 file is upgraded in place by `load_runtime_settings.py --ensure`, preserving the user's `subagent_wait` values. Settings carry the subagent wait policy, `execution` (`mode`, `dispatch_timeout_seconds`, `max_active_subagents`), and `primary_agent_fallback`. Before each stateful model dispatch, the Primary Agent reads it with `load_runtime_settings.py` and snapshots the returned values for that dispatch. Invalid settings fail closed.

Controlled source-editing also records the linked Git worktree `../<project-name>-worktrees/<task-id>` (a sibling of the project root) in both the runtime and task state. Run `prepare_worktree.py` only after the task is `IN_PROGRESS` and its approval reference is present. Evidence scripts hash the bound worktree; recovery reports path, branch, HEAD, or dirty-state mismatches. After the task is `COMPLETED` or `ACCEPTED`, run `cleanup_worktree.py` to record the removal, keep, or rebind decision; delivery fails closed when a worktree-bound task has no recorded cleanup decision. No script merges, pushes, or removes a worktree.

The host `open_task` action must run after `init_runtime` and before `prepare_worktree`; it uses `update_task_state.py` to bind the task ID, scope, workflow decision, and approval. When `worktree.required` is true, `prepare_worktree.py` maps that same task ID to `../<project-name>-worktrees/<task-id>` and branch `phongka/task/<task-id>`, then records path/branch/HEAD identity in task and runtime state. Missing `HOST-0` attestation or any identity mismatch is fail-closed `BLOCKED`; a delegated role must not invent a mapping or repair the state.

## Read-only dashboard

Summarize an existing runtime without changing it:

```bash
python scripts/project_dashboard.py --project-root <project>
```

The dashboard reports recorded state only; finalization scripts recheck evidence freshness. Missing artifacts are not success.

## Human progress view

Only the Primary Agent writes checklist state. `render_checklist.py` is the only checklist writer. The Primary Agent refreshes it at stage boundaries; role skills return their normal handoff and do not write `.phongka`:

```bash
python scripts/render_checklist.py \
  --project-root <project> \
  --task-id <task-id> \
  --current-stage <stage> \
  --current-skill <skill>
```

The command records one small `WORKFLOW_STAGE_UPDATED` event bound to the selected task and renders `.phongka/checklist/task-checklist-<task-id>.md`. Task selection uses an explicit `--task-id`, then the active task, then the latest valid task-bound stage event; it fails closed when no task can be selected. Without the two marker arguments it only reads the last valid event for that task. Reached-stage checkboxes mean reached, not completion; when no valid stage event exists, the view shows `unknown` and leaves every stage unchecked. Existing legacy checklist README files are not deleted.

Scripts do not infer intent, spawn models, merge, deploy, publish, delete, or retry uncertain side effects. Read [artifact contracts](references/artifact-contracts.md) and [CLI behavior](references/cli-behavior.md).
