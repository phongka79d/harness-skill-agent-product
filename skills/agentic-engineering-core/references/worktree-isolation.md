# Worktree isolation

Controlled source-editing decisions set `worktree.required` and expose the deterministic path and branch templates. Worktree state is Primary Agent/host-owned; delegated roles edit only the bound worktree files in their contract and never create, rebind, clean up, or mutate `.phongka` identity records.

1. Open the approved task.
2. The host `open_task` action uses `update_task_state.py` (or an equivalent approved state-tool invocation) to bind the task ID, normalized scope, decision, and approval before preparation.
3. Run `prepare_worktree.py` with the task approval reference.
4. Perform edits and capture evidence from the returned worktree path.
5. Let review, verification, recovery, and delivery recheck the recorded path, branch, HEAD, and file hashes.
6. After the task is `COMPLETED` or `ACCEPTED`, run `cleanup_worktree.py` with the task approval reference to record the removal, keep, or rebind decision.

The `open_task` mapping and `worktree.required` value are prerequisites for controlled dispatch. If the host cannot attest to them under `HOST-0`, or the path/branch/HEAD identity does not match the task and runtime records, fail closed with `BLOCKED`; do not let a role invent an alternate worktree or write a state repair.

The runtime rejects a missing Git root, dirty base, path or branch collision, missing approval, stale identity, mismatched branch/HEAD, and dirty worktree during recovery inspection. Delivery fails closed when a worktree-bound task has no recorded cleanup decision.

`prepare_worktree.py` and `cleanup_worktree.py` record decisions only. They never merge, push, or remove a worktree. The package does not provide a queue, lease, distributed worktree manager, or automatic cleanup.
