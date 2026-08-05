# Merge and Cleanup Safety

Use this order for every delivery decision:

```text
fresh verification and review
        -> select one outcome
        -> persist decision, hashes, and approvals
        -> execute the approved state-tool operation
        -> re-verify or reconcile
        -> perform only authorized cleanup
```

## Preconditions and evidence

- Final verification is current for the exact task, run, attempt, dispatch,
  task revision, plan revision, and workspace hash. Record each command, exit
  code, status, timestamp, and evidence identifier. Missing, stale, or failed
  verification blocks a successful delivery claim.
- The task review and Batch Reviewer integration review are accepted as
  required by the active batch contract. The Batch Reviewer reviews the
  result; it never performs the merge.
- The delivery decision persists the selected outcome, approver, approval
  target revision/hash, input and output artifact hashes, branch/worktree
  identity, verification evidence, and cleanup evidence before the side effect.
- Protected actions use the existing typed approval contract. Discard is a
  destructive action and requires an explicit, current approval whose target
  and hash still match. A missing, expired, wrong-actor, or stale approval
  blocks the action.

## Merge and conflict handling

Use `agentic-state-tools` transaction and merge boundaries; do not run
uncontrolled Git commands or hand-write canonical `.agent/` state.

- For `MERGE_LOCAL`, verify the source branch/worktree identity and target
  branch before the merge. After the merge, run final verification against the
  merged target and persist the new target hash before reporting success.
- For `PUSH_AND_CREATE_PR`, persist the available push/PR result and retain the
  source branch and worktree for review fixes. A PR outcome is not permission
  to clean up the source workspace.
- If a merge or target check conflicts, stop and record `BLOCKED` or
  `NEEDS_RECONCILIATION` with the conflict evidence. Preserve both identities;
  do not reset, force-delete, or apply an automatic destructive repair.

## Cleanup fencing

Cleanup is allowed only after the delivery evidence is durable and the target
is proven to be Harness-owned. The proof must match the persisted task/run,
attempt, and dispatch identity plus the registered worktree path, branch name,
base commit, plan revision, worktree revision, and ownership record. A path or
branch name alone is never sufficient.

- `KEEP_BRANCH_AND_WORKTREE` and `PUSH_AND_CREATE_PR` preserve the branch and
  worktree.
- `MERGE_LOCAL` may clean up only through a separately authorized cleanup gate
  after post-merge verification is persisted.
- `DISCARD_BRANCH_AND_WORKTREE` requires typed destructive approval before the
  cleanup operation. Persist the decision first; then record cleanup status,
  identity proof, operation ID, hashes, and timestamp through state-tools.

If ownership, identity, evidence, or approval cannot be proven, retain the
workspace and return `BLOCKED` or `NEEDS_RECONCILIATION`. Never remove a
user-owned or ambiguously mapped branch/worktree.
