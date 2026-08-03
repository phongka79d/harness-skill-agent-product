# Agentic Runtime Gap Closure Follow-up Plan

> **For agentic workers:** This is a proposed follow-up plan. Execute it only after the user approves the phase boundaries. Use test-first validation for every behavior change and keep the Primary Agent as the architecture owner.

**Goal:** Close the remaining report gaps in dependency order so the package can move from `Execution Core Prototype` to a demonstrably complete V1 runtime, then plan the deferred P2 capabilities without mixing them into V1.

**Architecture:** Keep Model A from the report and specification: reusable instructions, Wiki, schemas, scripts, and tests live in installed skill packages; project plans live under `docs/agentic/`; generated runtime artifacts live only under `.agent/`. Keep execution routing in the Primary Agent. The planned Harness layer records and validates queue, dependency, mode, dispatch, recovery, and approval decisions; it does not silently become a second architecture owner.

**Tech Stack:** Python 3 standard library, the existing JSON-schema subset validator, JSON-compatible YAML profile files, `unittest`, Git CLI reconciliation, atomic JSON/JSONL runtime artifacts.

**Baseline:** The preceding implementation plan is `2026-08-02-agentic-runtime-gaps.md`. Its P0 work and selected P1 helpers are implemented and validated by 52 tests. This plan owns only the remaining work described below.

**Planning status:** Approved by the user and implemented through the P1-E release gate. No `Master_Plan.md` or formal `Plan_N.md` portfolio exists in this workspace, so the current architecture specification and the supplied review report remain the authorities for this follow-up.

**Master impact:** None proposed. The plan preserves Primary-controlled routing, Model A workspace boundaries, the existing Python/runtime stack, and the current `.agent/` ownership rules. Any later change to those decisions must be a separately approved change request.

---

## Gap Register

| Report item | Current state after baseline work | Follow-up owner |
|---|---|---|
| 5.2 Shared Skill Wiki | A routing reference exists, but there is no complete shared Wiki package or migrated source of truth. | P1-A |
| 5.3 Profiles and rubrics | Basic profiles and hash-aware rubric resolution exist; task-type extensions, approval-bound overrides, and strict review integration remain. | P1-C |
| 5.4 Planning contracts | Individual schemas and cross-document checks exist; versioned plan change application and supersede flow remain. | P1-C |
| 5.5 Async/sync orchestration | Read-only runnable-task and mode helpers exist; queue schemas, critical path, dispatch records, and queue reconciliation remain. | P1-B |
| 5.6 Recovery workspace | Git mismatch detection exists; checkpoint capture, persisted reconciliation evidence, and full recovery transitions remain. | P1-D |
| 5.8 Lease cleanup | Terminal cleanup exists; operation verification and cleanup failure handling remain. | P1-D |
| 5.9 State/recovery mismatch | Statuses and maps were expanded manually; one authoritative state definition and generated consumers remain. | P1-A |
| 5.11 Lock expiry | Expiry detection and reclaim evidence exist; owner liveness/identity and recovery-safe reclaim policy remain. | P1-D |
| 5.12 Boundary | Model A is selected and documented. | P1-A verification |
| P1 approval records | Basic approval records exist; approval matrix enforcement and plan-change linkage remain. | P1-C |
| P1 packaging/tests | Baseline package checks pass; the final integrated workflow and fault matrix remain. | P1-E |
| P2 capabilities | Deferred by the report and not implemented. | P2-A through P2-C |

## Execution Order

```text
P1-A Source of truth and state machine
  -> P1-B Queue, graph, and dispatch Harness
  -> P1-C Profiles, rubrics, approvals, and plan changes
  -> P1-D Recovery, locks, and terminal cleanup hardening
  -> P1-E Integrated V1 workflow and release gate
  -> P2-A Dashboard and observability
  -> P2-B Distributed scheduling and remote state
  -> P2-C Rollback and multi-machine locking
```

P1-A is the only prerequisite for all later phases. P1-B and P1-C may proceed in separate workstreams after P1-A, but P1-E consumes both. P1-D may proceed in parallel with P1-C after P1-A, but its recovery contracts must be frozen before P1-E.

## P1-A: Shared Wiki and Authoritative State Machine

**Purpose:** Remove duplicated policy/state definitions and make the existing Model A boundary executable and auditable.

**Files:**

- Create: `skills/agentic-engineering-wiki/SKILL.md`
- Create: `skills/agentic-engineering-wiki/agents/openai.yaml`
- Create: `skills/agentic-engineering-wiki/refs/architecture/architecture.md`
- Create: `skills/agentic-engineering-wiki/refs/roles/brainstorm-facilitator.md`
- Create: `skills/agentic-engineering-wiki/refs/roles/plan-architect.md`
- Create: `skills/agentic-engineering-wiki/refs/roles/plan-reviewer.md`
- Create: `skills/agentic-engineering-wiki/refs/roles/explorer.md`
- Create: `skills/agentic-engineering-wiki/refs/roles/implementer.md`
- Create: `skills/agentic-engineering-wiki/refs/roles/context-builder.md`
- Create: `skills/agentic-engineering-wiki/refs/roles/task-reviewer.md`
- Create: `skills/agentic-engineering-wiki/refs/roles/batch-reviewer.md`
- Create: `skills/agentic-engineering-wiki/refs/roles/runtime-recovery.md`
- Create: `skills/agentic-engineering-wiki/refs/workflows/planning.md`
- Create: `skills/agentic-engineering-wiki/refs/workflows/execution.md`
- Create: `skills/agentic-engineering-wiki/refs/workflows/review.md`
- Create: `skills/agentic-engineering-wiki/refs/workflows/recovery.md`
- Create: `skills/agentic-engineering-wiki/refs/policies/delegation.md`
- Create: `skills/agentic-engineering-wiki/refs/policies/state-boundary.md`
- Create: `skills/agentic-engineering-wiki/refs/policies/validation.md`
- Create: `skills/agentic-engineering-wiki/refs/contracts/handoff.md`
- Create: `skills/agentic-engineering-wiki/refs/contracts/planning.md`
- Create: `skills/agentic-engineering-wiki/refs/contracts/rubric.md`
- Create: `skills/agentic-engineering-wiki/refs/profiles/profiles.md`
- Create: `skills/agentic-engineering-wiki/refs/rubrics/task.md`
- Create: `skills/agentic-engineering-wiki/refs/rubrics/batch.md`
- Create: `skills/agentic-engineering-wiki/schemas/index.md`
- Create: `skills/agentic-engineering-wiki/scripts/validate_wiki_links.py`
- Create: `skills/agentic-engineering-wiki/tests/test_wiki_routing.py`
- Create: `skills/agentic-state-tools/schemas/state-machine.json`
- Create: `skills/agentic-state-tools/scripts/validate_state_machine.py`
- Create: `skills/agentic-state-tools/scripts/generate_state_artifacts.py`
- Modify: `skills/agentic-engineering-core/SKILL.md`
- Modify: all role `SKILL.md` files to route through the Wiki
- Modify: `skills/agentic-state-tools/scripts/runtime_utils.py`
- Modify: `skills/agentic-state-tools/scripts/validate_transition.py`
- Modify: `skills/agentic-state-tools/schemas/task-state.schema.json`
- Modify: `skills/agentic-state-tools/schemas/event.schema.json`
- Modify: `skills/agentic-engineering_system_complete_specification.md`

**Steps:**

- [x] Write a failing test that loads `state-machine.json` and proves every status has one event mapping, one schema value, and a transition definition.
- [x] Write a failing test that rejects a Wiki link outside the installed Wiki or an accidental `.agent/wiki/` reference.
- [x] Define the state source with statuses, terminal states, actor permissions, required artifacts, event names, and allowed transitions.
- [x] Make runtime validation consume the source definition or generated artifacts; remove manually duplicated status lists only after generated output is verified identical.
- [x] Move shared architecture, role, workflow, policy, contract, profile, and rubric guidance into the Wiki package while keeping compatibility links in existing skills.
- [x] Run `python skills/agentic-state-tools/scripts/validate_state_machine.py --input skills/agentic-state-tools/schemas/state-machine.json` and `python run_tests.py`.

**Acceptance criteria:** No status/event/transition drift is possible without the state-machine validator failing. All role entry points route to one Wiki table of contents. Model A remains explicit and `.agent/` contains runtime state only.

**Handoff:** Produce the validated state definition, Wiki routing contract, and a migration map for P1-B through P1-D.

## P1-B: Queue, Dependency Graph, and Dispatch Harness

**Purpose:** Complete the hybrid async/sync orchestration gap without adding a separate architecture owner.

**Files:**

- Create: `skills/agentic-state-tools/schemas/queue.schema.json`
- Create: `skills/agentic-state-tools/schemas/graph.schema.json`
- Create: `skills/agentic-state-tools/schemas/dispatch.schema.json`
- Create: `skills/agentic-state-tools/scripts/compute_critical_path.py`
- Create: `skills/agentic-state-tools/scripts/reconcile_queue.py`
- Create: `skills/agentic-state-tools/scripts/dispatch_task.py`
- Modify: `skills/agentic-state-tools/scripts/resolve_runnable_tasks.py`
- Modify: `skills/agentic-state-tools/scripts/resolve_execution_mode.py`
- Modify: `skills/agentic-state-tools/scripts/validate_dependency_graph.py`
- Modify: `skills/agentic-state-tools/scripts/detect_scope_overlap.py`
- Modify: `skills/agentic-state-tools/scripts/init_runtime.py`
- Modify: `skills/agentic-state-tools/scripts/runtime_utils.py`
- Modify: `skills/agentic-state-tools/SKILL.md`
- Create: `skills/agentic-state-tools/tests/test_orchestration.py`

**Steps:**

- [x] Write failing tests for missing dependencies, dependency cycles, accepted-only dependency readiness, async independent tasks, sync repair/conflict tasks, critical-path ordering, and overlapping write scopes.
- [x] Define `queue.schema.json` with task ID, queue state, execution mode, dependency snapshot, scope snapshot, owner, and revision.
- [x] Define `dispatch.schema.json` with dispatch ID, task ID, selected mode, selected owner/model, input revisions, approval references, and evidence.
- [x] Make `resolve_runnable_tasks.py` return deterministic reasons for blocked, conflicted, and runnable tasks; never treat `COMPLETED` as an accepted dependency.
- [x] Add `compute_critical_path.py` using the validated DAG and stable tie-breaking by task ID.
- [x] Add `reconcile_queue.py` to compare queue state with task state, locks, accepted dependencies, and dispatch records.
- [x] Add `dispatch_task.py` as a record-and-validate boundary. It may create a dispatch handoff, but it must not spawn an agent or change architecture without Primary authorization.
- [x] Run the orchestration test file and then `python run_tests.py`.

**Acceptance criteria:** The Harness can produce a reproducible runnable queue and dispatch record. Async is selected only for independent tasks with no conflict/blocker; sync is forced for dependencies not yet accepted, repairs, conflicts, or recovery. Queue reconciliation reports stale or contradictory entries instead of guessing.

**Handoff:** Produce queue, graph, dispatch, and critical-path contracts for P1-E.

## P1-C: Adaptive Rubrics, Approval Matrix, and Plan Change Control

**Purpose:** Ensure every review and planning change is tied to an immutable, approved decision rather than reviewer-specific judgment.

**Files:**

- Create: `skills/agentic-state-tools/profiles/rubrics/task/general.yaml`
- Create: `skills/agentic-state-tools/profiles/rubrics/task/backend.yaml`
- Create: `skills/agentic-state-tools/profiles/rubrics/task/frontend.yaml`
- Create: `skills/agentic-state-tools/profiles/rubrics/task/data.yaml`
- Create: `skills/agentic-state-tools/profiles/rubrics/task/infrastructure.yaml`
- Create: `skills/agentic-state-tools/profiles/rubrics/task/documentation.yaml`
- Create: `skills/agentic-state-tools/profiles/rubrics/task/testing.yaml`
- Create: `skills/agentic-state-tools/profiles/rubrics/batch/standard.yaml`
- Create: `skills/agentic-state-tools/profiles/rubrics/batch/strict.yaml`
- Create: `skills/agentic-state-tools/schemas/rubric.schema.json`
- Create: `skills/agentic-state-tools/schemas/change-approval.schema.json`
- Create: `skills/agentic-state-tools/scripts/validate_change_request.py`
- Create: `skills/agentic-state-tools/scripts/apply_change_request.py`
- Modify: `skills/agentic-state-tools/scripts/resolve_project_profile.py`
- Modify: `skills/agentic-state-tools/scripts/resolve_rubric.py`
- Modify: `skills/agentic-state-tools/scripts/create_review.py`
- Modify: `skills/agentic-state-tools/scripts/create_batch_review.py`
- Modify: `skills/agentic-state-tools/scripts/record_approval.py`
- Modify: `skills/agentic-state-tools/schemas/review.schema.json`
- Modify: `skills/agentic-state-tools/schemas/batch-review.schema.json`
- Modify: `skills/agentic-state-tools/schemas/change-request.schema.json`
- Create: `skills/agentic-state-tools/tests/test_adaptive_quality.py`

**Steps:**

- [x] Write failing tests for profile aliases, task-type rubric extensions, explicit threshold/weight overrides, missing approval, stale rubric hash, and a reviewer attempting to omit an applicable criterion.
- [x] Define canonical profile IDs with compatibility aliases for existing underscore filenames; do not maintain two independent definitions.
- [x] Define task and batch rubric extensions that merge deterministically with the base quality profile and record the source IDs and versions.
- [x] Require `resolved_rubric` for newly created reviews; keep a clearly marked legacy migration path only for existing artifacts.
- [x] Require approval records for overrides that raise risk, lower thresholds, exclude a mandatory criterion, alter architecture, or supersede a plan.
- [x] Validate change requests against target type, target version, requested change, impact, approval, and superseded ID before applying them.
- [x] Apply a plan change by writing a new version and an immutable supersede link; never mutate historical plan evidence in place.
- [x] Run `python skills/agentic-state-tools/scripts/resolve_rubric.py --profile personal --task-type quick_change --risk-flags '{}'`, the adaptive-quality tests, and `python run_tests.py`.

**Acceptance criteria:** Two reviewers given the same profile, task type, risk flags, and approved overrides receive byte-identical rubric hashes. Unauthorized overrides and unresolved change requests cannot produce `PASS` or replace a prior plan.

**Handoff:** Produce immutable profile/rubric/change-control contracts for P1-E.

## P1-D: Recovery, Lock, and Terminal-State Hardening

**Purpose:** Make recovery evidence complete and ensure cleanup cannot hide active work or uncertain side effects.

**Files:**

- Create: `skills/agentic-state-tools/schemas/reconciliation.schema.json`
- Create: `skills/agentic-state-tools/schemas/lock-reclaim.schema.json`
- Create: `skills/agentic-state-tools/scripts/capture_workspace.py`
- Create: `skills/agentic-state-tools/scripts/verify_terminal_cleanup.py`
- Modify: `skills/agentic-state-tools/scripts/create_checkpoint.py`
- Modify: `skills/agentic-state-tools/scripts/inspect_recovery.py`
- Modify: `skills/agentic-state-tools/scripts/runtime_utils.py`
- Modify: `skills/agentic-state-tools/scripts/acquire_lock.py`
- Modify: `skills/agentic-state-tools/scripts/update_task_state.py`
- Modify: `skills/agentic-state-tools/scripts/create_review.py`
- Modify: `skills/agentic-state-tools/schemas/checkpoint.schema.json`
- Modify: `skills/agentic-state-tools/schemas/lease.schema.json`
- Modify: `skills/agentic-state-tools/schemas/lock.schema.json`
- Modify: `skills/agentic-runtime-recovery/references/recovery-model.md`
- Create: `skills/agentic-state-tools/tests/test_recovery_hardening.py`

**Steps:**

- [x] Write failing tests for checkpoint capture of `base_commit`, staged/unstaged/untracked paths, missing expected files, malformed Git output, expired locks with a live owner identity, unresolved operations, and terminal cleanup with a malformed artifact.
- [x] Make `create_checkpoint.py` capture a normalized workspace snapshot through one helper; permit explicit evidence from non-Git fixtures only when no Git claim is made.
- [x] Persist reconciliation evidence as a schema-validated artifact and include its ID/hash in the recovery result and `RECOVERY_INSPECTED` event.
- [x] Add `verify_terminal_cleanup.py` to prove no task lease, owned lock, or unresolved operation remains after a terminal transition; return `NEEDS_RECONCILIATION` when proof is incomplete.
- [x] Extend lock records with a stable owner identity or process evidence and refuse reclaim when the recorded owner is live despite an inconsistent expiry record.
- [x] Make cleanup failures visible and non-successful; never report a terminal task as clean when an artifact could not be inspected.
- [x] Run the recovery hardening tests, the existing end-to-end workflow, and `python run_tests.py`.

**Acceptance criteria:** Recovery never resumes from checkpoint data alone. Every non-safe classification has machine-readable reasons and reconciliation evidence. Terminal cleanup is verifiable, idempotent, and conservative under malformed or live-owner artifacts.

**Handoff:** Produce a stable recovery/lock contract for P1-E and record any intentionally unsupported Git environments.

## P1-E: Integrated V1 Workflow and Release Gate

**Purpose:** Validate the full planning-to-recovery path as one system and close documentation/package drift.

**Files:**

- Create: `skills/agentic-state-tools/tests/test_v1_workflow.py`
- Create: `skills/agentic-state-tools/examples/v1-planning-bundle.json`
- Create: `skills/agentic-state-tools/examples/v1-dispatch.json`
- Create: `skills/agentic-state-tools/examples/v1-recovery.json`
- Modify: `run_tests.py`
- Modify: `skills/agentic-engineering-core/SKILL.md`
- Modify: `skills/agentic-brainstorm-facilitator/SKILL.md`
- Modify: `skills/agentic-plan-architect/SKILL.md`
- Modify: `skills/agentic-plan-reviewer/SKILL.md`
- Modify: `skills/agentic-explorer/SKILL.md`
- Modify: `skills/agentic-implementer/SKILL.md`
- Modify: `skills/agentic-context-builder/SKILL.md`
- Modify: `skills/agentic-task-reviewer/SKILL.md`
- Modify: `skills/agentic-batch-reviewer/SKILL.md`
- Modify: `skills/agentic-runtime-recovery/SKILL.md`
- Modify: `skills/agentic-state-tools/SKILL.md`
- Modify: `skills/agentic_engineering_system_complete_specification.md`
- Modify: `docs/superpowers/plans/2026-08-02-agentic-runtime-gaps-follow-up.md`

**Steps:**

- [x] Add one end-to-end test that validates a planning bundle, resolves profile/rubric, resolves queue/mode, records approval, dispatches a task, records checkpoint/lease/lock, completes and reviews it, performs batch review, and inspects recovery after an injected workspace mismatch.
- [x] Add fault cases for stale revisions, missing approvals, rejected transitions, malformed event, unresolved operation, expired lock, and queue/task disagreement.
- [x] Validate every bundled example against its schema and run all skill metadata/reference checks.
- [x] Compare the implementation against every P0/P1 row in the report and update the gap register with evidence, not assertions.
- [x] Run `python run_tests.py`, `python -m compileall -q skills run_tests.py`, JSON parsing, and all skill validators as the V1 release gate.

**Acceptance criteria:** The integrated workflow passes from planning through recovery with no direct canonical writes, no invented rubric, no unapproved architecture change, and no unsafe automatic resume. The package can be labeled `Agentic Engineering Runtime V1` only after this gate passes.

## P2-A: Read-Only Dashboard and Observability

**Purpose:** Add visibility without creating a second source of truth or a mutation path.

**Dependencies:** P1-E.

**Planned outputs:**

- `skills/agentic-dashboard/SKILL.md` and UI metadata.
- Read-only projections for task queue, state history, review/rubric status, locks, leases, recovery classifications, and event timelines.
- Snapshot/export schema and tests proving dashboard output is derived from `.agent/` and cannot write it.

**Acceptance criteria:** Dashboard views are reproducible from canonical artifacts, redact configured sensitive fields, identify stale evidence, and have no state-mutating command.

### P2-A Execution Checklist

- [x] Define the dashboard snapshot and external configuration contracts with stable view names, source hashes, redaction metadata, stale evidence, and diagnostics.
- [x] Add failing tests for deterministic projections, recursive configured redaction, stale evidence, malformed source diagnostics, output-path safety, and no `.agent/` mutation.
- [x] Add the minimal read-only collector that reads runtime, queue, work, lock, lease, and recovery artifacts without importing mutation helpers.
- [x] Add skill instructions and UI metadata that expose the dashboard as a read-only projection command and route state ownership to `agentic-state-tools`.
- [x] Validate snapshots and configuration with the existing JSON-schema subset validator, including external export behavior.
- [x] Run dashboard tests, all skill metadata/reference checks, and `python run_tests.py`; mark this phase `[x]` only after the full gate passes.

## P2-B: Distributed Scheduling and Remote State

**Purpose:** Support multiple machines only after local contracts and recovery are stable.

**Dependencies:** P2-A and P1-E.

**Planned outputs:**

- Backend-neutral state-store interface with local filesystem adapter retained as the reference implementation.
- Remote event append, snapshot read, optimistic revision/etag checks, distributed task/file/resource lock service, heartbeat ownership, and network failure classification.
- Migration and compatibility tests showing local and remote stores replay to the same state.

**Acceptance criteria:** Concurrent writers cannot lose events or overwrite newer revisions; leases and locks remain owner-bound across machines; network uncertainty produces reconciliation rather than duplicate side effects.

### P2-B Execution Checklist

- [x] Define remote event, snapshot, lock, and structured network-error schemas with revision, etag, idempotency, owner, and fencing fields.
- [x] Add failing tests for stale revision/etag, idempotent event replay, conflicting event IDs, owner-bound heartbeat/release, fencing-token reclaim, malformed store state, and network uncertainty.
- [x] Implement the backend-neutral store protocol and file-backed reference adapter with atomic append/snapshot writes.
- [x] Implement the HTTP JSON transport/client boundary with explicit operation IDs and no automatic mutation retry.
- [x] Add CLI/read-only and mutation commands documented through `agentic-state-tools`, preserving `.agent/` as the local adapter boundary.
- [x] Validate local/remote replay parity and run all existing tests, package validators, and compilation; mark this phase `[x]` only after the full gate passes.

## P2-C: Rollback, Compensation, and Multi-Machine Safety

**Purpose:** Add controlled rollback and compensation for side effects once operation contracts are mature.

**Dependencies:** P1-D, P1-E, and P2-B.

**Planned outputs:**

- Compensating-action schema linked to operation IDs and approval records.
- Dry-run rollback planner, explicit approval gate, execution ledger, partial-rollback classification, and recovery evidence.
- Multi-machine lock fencing/token validation and stale-owner recovery.

**Acceptance criteria:** Rollback is never inferred from a failed task alone, destructive compensation requires approval, partial rollback is escalated, and stale owners cannot continue after fencing.

### P2-C Execution Checklist

- [x] Define compensation-action, rollback-plan, rollback-ledger, and rollback-evidence schemas, plus explicit rollback event types in the authoritative state source.
- [x] Add failing tests for explicit-request-only planning, operation linkage, destructive approval gates, unknown/failed outcomes, partial rollback escalation, and stale fencing-token rejection.
- [x] Implement a dry-run rollback planner that never executes side effects and an execution ledger that records provider outcomes without automatic retry.
- [x] Enforce exact approval linkage and current distributed fencing tokens before each compensation action.
- [x] Add recovery evidence/event integration and CLI commands while preserving canonical `.agent/` writes through validated state tools.
- [x] Run rollback tests, full workflow, state-machine generation/validation, all skill validators, compilation, and JSON checks; mark this phase `[x]` only after the full gate passes.

## Cross-Phase Invariants

- Keep planning source in `docs/agentic/` or the approved installed Wiki; keep generated state in `.agent/` only.
- Keep the Primary Agent responsible for architecture, scope, delegation, approval, conflict decisions, and final validation.
- Use one canonical state-machine definition and one canonical resolved-rubric representation.
- Never allow a high score to override hard fails, an unaccepted dependency to become runnable, or an uncertain side effect to be repeated automatically.
- Require evidence for `NOT_APPLICABLE`, `PASS`, terminal cleanup, recovery safety, approvals, and every release claim.
- Do not add the standalone Orchestrator skill unless the specification is explicitly amended; current routing is Primary-controlled.

## Execution Evidence

- P1-A: `skills/agentic-engineering-wiki`, `state-machine.json`, state-machine validator/generator, runtime consumer wiring, and Wiki routing tests.
- P1-B: queue/graph/dispatch schemas, deterministic critical-path and runnable-queue scripts, queue reconciliation, and dispatch boundary tests.
- P1-C: profile aliases, task/batch rubric extensions, approval matrix, immutable change-request application, and adaptive-quality tests.
- P1-D: normalized workspace capture, checkpoint/reconciliation evidence, owner-aware lock reclaim, terminal cleanup proof, and recovery hardening tests.
- P1-E: `test_v1_workflow.py`, bundled V1 planning/dispatch/recovery examples, and the release-example preflight in `run_tests.py`.
- Current validation evidence: `python run_tests.py` passes the complete suite; each installed skill passes `quick_validate.py`.
- P2-A, P2-B, and P2-C remain deferred roadmap capabilities and are not represented as implemented.

## Validation Matrix

| Gate | Command | Required result |
|---|---|---|
| State definition | `python skills/agentic-state-tools/scripts/validate_state_machine.py --input skills/agentic-state-tools/schemas/state-machine.json` | Valid, no drift |
| Planning contracts | `python skills/agentic-state-tools/scripts/validate_planning.py --input <bundle>` | `PLANNING_VALID` |
| Queue/graph | `python skills/agentic-state-tools/scripts/reconcile_queue.py --input <queue>` | No contradictory entries |
| Profile/rubric | `python skills/agentic-state-tools/scripts/resolve_rubric.py ...` | Stable hash and resolved weights |
| Recovery | `python skills/agentic-state-tools/scripts/inspect_recovery.py --project-root <project>` | Evidence-backed classification |
| Package | `python run_tests.py` | Zero failures |
| Skill metadata | `python .../quick_validate.py skills/<skill>` | `Skill is valid!` |

## Completion Contract

This follow-up plan is complete when P1-E passes and every P1 row in the report has an evidence link or an explicitly approved exception. P2 remains a separate roadmap until P1-E stabilizes; it must not be represented as implemented merely because these design phases exist.

**Next consumer:** The user/Primary Agent reviews and approves the phase boundaries. After approval, create one executable task contract per phase, beginning with P1-A, and execute phases in dependency order.
