# Planning Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/validate_planning.py`)

Every executable task declares objective, dependencies, read scope, write scope,
acceptance criteria, verification commands, risk flags, out-of-scope items,
owner, and version. `validate_planning.py --input <planning-bundle.json>` checks
the planning schemas, requirement traceability, owner aliases and capabilities,
dependency cycles, and write-scope overlap. A task with no owner, an unknown
owner, or an owner without the task capability is rejected.

The planning sequence is `PENDING -> READY -> QUEUED -> RUNNING -> COMPLETED ->
REVIEWING -> ACCEPTED`; blocked, repair, stale, recovery, cancellation, and
supersede transitions are explicit state-machine transitions. The task state
schema supplies the enum, while `validate_transition.py` and
`validate_state_machine.py` validate the executable transition registry.

Each task pins its resolved review contract: project profile, profile hash, task
type, normalized risk flags, rubric ID/version/hash, and review-policy version.
Dispatch must carry the same pin. Parent plans trace requirements to task
acceptance criteria; an untraced requirement is a validation error unless it is
deprecated.

- Feature: planning validation command=`skills/agentic-state-tools/scripts/validate_planning.py` schema=`skills/agentic-state-tools/schemas/planning-task.schema.json`
- Feature: placeholder validation command=`skills/agentic-state-tools/scripts/validate_no_placeholders.py`

## Executable task contract

Legacy tasks remain readable. A new task opts into the stricter contract with
`contract_mode: executable` (or `strict: true`). Such a task is independently
executable: it carries prerequisite decision IDs, exact repository paths,
relevant symbols/interfaces, allowed and forbidden files, dependency IDs,
implementation and validation steps, expected RED/GREEN results, exact
verification commands, acceptance-criterion IDs, handoff expectations, and a
file responsibility map. Active risk flags also require a rollback/recovery
note.

The validator rejects path ambiguity, mismatched dependency or acceptance IDs,
hidden architecture choices, conflicting file ownership, inconsistent qualified
symbols (`path/to/file.py::symbol`), unbounded task size, and vague placeholder
instructions. `verification` remains readable for old artifacts; executable
tasks use `verification_commands` as the exact command list.

## Transition Matrix

The following is the executable registry, including every source state and its
allowed target group. The default artifact is `task_state` unless the row lists
additional artifacts. Executor transitions are performed by the state tools;
reviewer transitions are review-only and require the pinned review artifacts.

| Source | Allowed target states | Role | Guards | Required artifacts |
| --- | --- | --- | --- | --- |
| `PENDING` | `CANCELLED`, `DEFERRED`, `READY` | executor | none | task_state |
| `READY` | `CANCELLED`, `DEFERRED`, `QUEUED`, `QUEUED_ASYNC`, `QUEUED_SYNC`, `WAITING`, `WAITING_DEPENDENCY`, `WAITING_RESOURCE_LOCK` | executor | none | task_state |
| `QUEUED` | `CANCELLED`, `QUEUED_ASYNC`, `QUEUED_SYNC`, `RUNNING`, `WAITING`, `WAITING_DEPENDENCY`, `WAITING_RESOURCE_LOCK` | executor | queue/dependency policy | task_state |
| `QUEUED_ASYNC` | `CANCELLED`, `RUNNING`, `WAITING_DEPENDENCY`, `WAITING_RESOURCE_LOCK` | executor | verified isolation, lease, identity | task_state |
| `QUEUED_SYNC` | `CANCELLED`, `RUNNING`, `WAITING_DEPENDENCY`, `WAITING_RESOURCE_LOCK` | executor | lease and dependency policy | task_state |
| `WAITING` | `CANCELLED`, `QUEUED`, `QUEUED_ASYNC`, `QUEUED_SYNC`, `RUNNING` | executor | resource/dependency guard | task_state |
| `WAITING_DEPENDENCY` | `BLOCKED`, `CANCELLED`, `QUEUED`, `QUEUED_ASYNC`, `QUEUED_SYNC`, `RUNNING` | executor | dependency clearance | task_state |
| `WAITING_RESOURCE_LOCK` | `BLOCKED`, `CANCELLED`, `QUEUED`, `QUEUED_ASYNC`, `QUEUED_SYNC`, `RUNNING` | executor | lock clearance | task_state |
| `RUNNING` | `BLOCKED`, `CANCELLED`, `CHECKPOINTED`, `COMPLETED`, `ESCALATED`, `PAUSED`, `REPAIR_REQUIRED`, `REVIEWING`, `STALE`, `WAITING`, `WAITING_DEPENDENCY`, `WAITING_RESOURCE_LOCK` | executor | checkpoint/lease/side-effect guards | task_state |
| `CHECKPOINTED` | `BLOCKED`, `CANCELLED`, `RUNNING`, `STALE` | executor | checkpoint and workspace evidence | task_state |
| `PAUSED` | `CANCELLED`, `QUEUED`, `QUEUED_SYNC`, `RUNNING` | executor | pause/resume policy | task_state |
| `BLOCKED` | `CANCELLED`, `DEFERRED`, `ESCALATED`, `QUEUED`, `QUEUED_SYNC`, `REPAIR_REQUIRED` | executor | blocker resolution | task_state |
| `REPAIR_REQUIRED` | `CANCELLED`, `QUEUED`, `QUEUED_SYNC`, `RUNNING` | executor | repair scope and verification | task_state |
| `COMPLETED` | `REVIEWING` | executor or reviewer | same_run and same_attempt | task_state, review, review_contract |
| `COMPLETED` | `REPAIR_REQUIRED` | executor | same_run and same_attempt | task_state, review, review_contract |
| `REVIEWING` | `ACCEPTED`, `BLOCKED`, `REPAIR_REQUIRED` | reviewer only | same_run and same_attempt; canonical hard-fail evidence | task_state, review, review_contract |
| `STALE` | `ABORTED_UNSAFE`, `ESCALATED`, `RECOVERY_PENDING` | reviewer only | recovery inspection and workspace evidence | task_state |
| `RECOVERY_PENDING` | `ABORTED_UNSAFE`, `BLOCKED`, `ESCALATED`, `RESUMING` | reviewer only | reconciliation classification | task_state |
| `RESUMING` | `ABORTED_UNSAFE`, `BLOCKED`, `RUNNING` | executor | new run/attempt and safe recovery | task_state |
| `DEFERRED` | `CANCELLED`, `QUEUED_SYNC`, `READY`, `SUPERSEDED` | executor | replan/dependency policy | task_state |
| `ESCALATED` | `BLOCKED`, `CANCELLED`, `DEFERRED`, `SUPERSEDED` | executor | Primary/user decision where required | task_state |
| `ACCEPTED` | `ARCHIVED` | cleanup | terminal_cleanup | task_state |
| `CANCELLED` | `ARCHIVED` | cleanup | terminal_cleanup | task_state |
| `SUPERSEDED` | `ARCHIVED` | cleanup | terminal_cleanup | task_state |
| `ABORTED_UNSAFE` | none | none | terminal | none |
| `ARCHIVED` | none | none | terminal | none |

`COMPLETED -> REVIEWING` and all `REVIEWING` exits are review paths; an
executor cannot mark a task accepted. `STALE -> RECOVERY_PENDING`,
`RECOVERY_PENDING -> RESUMING`, and `RESUMING -> RUNNING` are the documented
recovery path. The registry records these transitions with their role
allowances but no additional required guard or artifact; `inspect_recovery.py`
produces the workspace and operation-ledger evidence used by the recovery
workflow, while `update_task_state.py` enforces the allowed transition. Terminal
cleanup archives only after leases and owned locks are proven released. The
same-run and same-attempt guards bind review evidence to the execution that
produced it.

Write-scope overlap is sequential only when a dependency path exists. Shared
writes require a synchronous execution mode and a persisted approval for the
same shared-write group. Distributed scheduling and remote state are
NOT_IMPLEMENTED because this release has no production remote-state command and
release test for them.
