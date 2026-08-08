# State and evidence

## Authority boundary

`.phongka` is a Primary Agent/host-owned state boundary. Delegated roles may read the runtime when their contract requires it, but they never create, update, delete, or otherwise mutate state, task files, artifacts, checklist files, or evidence indexes. They return evidence to the Primary Agent, which invokes the approved deterministic state tools at lifecycle boundaries. A generated, disposable, urgent, trivial, or unrelated output is not an exception.

State is project-local and single-active-task. It binds runtime and tasks to the resolved workflow decision, profile, task route, execution depth, risk contract, approval, delivery action, and required evidence.

`work_revision` changes when work metadata changes. `status_revision` changes for lifecycle transitions. Status-only completion does not stale evidence; changed work or changed recorded files does.

A verified stateful task uses:

1. current workspace snapshot;
2. `verification.json` bound to task revision and decision;
3. task status `COMPLETED` or `ACCEPTED`;
4. a passing completion claim;
5. generated `completion-gate.json`.

Independent `review.json` is also bound to task revision and decision. Integrated `batch-review.json` is bound to the current delivery decision and an exact set of task revisions.

Hashes provide content-integrity binding. They detect inconsistent content but are not cryptographic signatures against an actor who can rewrite both content and hash.

The host `open_task` action must run after `init_runtime` and before any controlled worktree preparation. It binds the task ID and normalized scope to the current decision; `prepare_worktree` then records the same task's path, branch, HEAD, and worktree identity when `worktree.required` is true. A missing or mismatched mapping is a fail-closed boundary, not a reason for a delegated role to repair state directly.
