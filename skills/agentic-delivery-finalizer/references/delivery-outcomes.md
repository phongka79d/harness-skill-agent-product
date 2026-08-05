# Delivery Outcomes

The finalizer records exactly one controlled outcome for an accepted task. The
outcome is not successful until current final-verification evidence, task and
batch review evidence, relevant approval evidence, and delivery hashes are
persisted.

| Outcome | Use when | Required result |
| --- | --- | --- |
| `MERGE_LOCAL` | The accepted change should land on the local target branch. | Perform the approved local merge through state-tools, then run final verification again on the merged result. Keep the source worktree until the post-merge evidence and any separately authorized cleanup are recorded. |
| `PUSH_AND_CREATE_PR` | The change should be handed off for remote review. | Record the push/PR evidence available to the configured workflow and preserve the branch and worktree for review fixes unless an explicit policy says otherwise. |
| `KEEP_BRANCH_AND_WORKTREE` | The change is complete enough to retain but must not be merged or discarded yet. | Preserve the branch and worktree, record the decision and identity evidence, and leave cleanup unrequested. |
| `DISCARD_BRANCH_AND_WORKTREE` | The change is intentionally abandoned. | Require a current typed destructive approval, persist the decision and verification evidence first, then remove only the Harness-owned branch/worktree proven by identity. |

An outcome cannot silently change into another outcome after execution starts.
If its preconditions fail, record `BLOCKED` or `NEEDS_RECONCILIATION` and retain
the workspace for inspection.

`MERGE_LOCAL` is the only outcome in this set that changes the local target
branch. A local merge conflict is evidence for reconciliation, not permission
to reset, delete, or invent a repair. `PUSH_AND_CREATE_PR` does not authorize
worktree cleanup: the review fix loop needs the source identity and workspace.

The Batch Reviewer may review integration, hashes, verification, and cleanup
readiness. It does not select or perform the merge on behalf of the finalizer.
