# CLI behavior

- Exit `0`: operation succeeded or the requested state is already present.
- Exit `1`: invalid input, missing required state, unsafe claim, stale evidence, unsafe path, inconsistent task index, or write failure.
- Commands print JSON for machine-readable decisions and short uppercase tokens for simple validation results.
- Invalid object types are reported as `<OPERATION>_REJECTED` rather than raw tracebacks.
- Each individual JSON state write is atomic. A process interruption between the task-file write and state-index write may leave an orphan; validation and recovery detect it and require explicit reconciliation.
- Scripts never call a provider model, execute a merge, push a branch, deploy, or retry an uncertain side effect.

- `open_task` is a host lifecycle action, not a delegated-role capability. After `init_runtime`, the host uses `update_task_state.py` to bind the task ID, normalized scope, workflow decision, and approval; controlled `prepare_worktree.py` then maps that ID to `../<project-name>-worktrees/<task-id>` and `phongka/task/<task-id>` when `worktree.required` is true.
- `HOST-0` is an external host attestation. Missing, stale, or contradictory attestation, or a task/worktree path/branch/HEAD mismatch, fails closed before dispatch or state mutation; package scripts cannot infer or fabricate it.

- `resolve_workflow.py` uses central `default_profile` when `--profile` or request `profile` is omitted. Configuration loading rejects a default profile that has no bundled profile file.
- `init_runtime.py --decision` verifies the decision hash, validates the task index, and rejects rebinding while a task is open.
- `init_runtime.py` also creates `.phongka/settings.json` from central defaults when missing and validates without overwriting it when present.
- `load_runtime_settings.py` reads and validates the settings file; `--ensure` creates it only for an initialized runtime. It never polls or closes a model agent.
- `update_task_state.py` accepts only caller-owned fields and normalized repository-relative scope paths.
- Derived approval, decision, revision, and delivery fields are not accepted from callers.
- Delegated roles do not invoke `update_task_state.py`, `render_checklist.py`, or another state-mutating command; only the Primary Agent/host may do so at the resolved lifecycle boundary.
- Stateful completion uses `work_revision` for evidence freshness and `status_revision` for lifecycle changes.
- Verification check names are acceptance IDs; completion claims must use the exact same unique set.

- `recovery` routes inspect the existing runtime and must not call `init_runtime.py` while interrupted work is active.
- Standalone `delivery` routes may call `init_runtime.py` to rebind an idle runtime, but they must not open a new task.
