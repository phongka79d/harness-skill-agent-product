# Worktree isolation

Controlled source-editing decisions set `worktree.required` and expose the deterministic path and branch templates.

1. Open the approved task.
2. Run `prepare_worktree.py` with the task approval reference.
3. Perform edits and capture evidence from the returned worktree path.
4. Let review, verification, recovery, and delivery recheck the recorded path, branch, HEAD, and file hashes.
5. After the task is `COMPLETED` or `ACCEPTED`, run `cleanup_worktree.py` with the task approval reference to record the removal, keep, or rebind decision.

The runtime rejects a missing Git root, dirty base, path or branch collision, missing approval, stale identity, mismatched branch/HEAD, and dirty worktree during recovery inspection. Delivery fails closed when a worktree-bound task has no recorded cleanup decision.

`prepare_worktree.py` and `cleanup_worktree.py` record decisions only. They never merge, push, or remove a worktree. The package does not provide a queue, lease, distributed worktree manager, or automatic cleanup.
