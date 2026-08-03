# Agentic Runtime Gaps Implementation Plan

> **For agentic workers:** Execute the tasks in order with test-first validation. Keep the Primary Agent as the architecture owner and use the existing state scripts for canonical runtime writes.

**Goal:** Implement the report's P0 corrections so the staged agentic skill package has complete planning entry points, machine-validated planning and rubric contracts, workspace-aware recovery, coherent terminal state cleanup, and deterministic test execution.

**Architecture:** Preserve the specification's Primary-controlled execution routing and Model A boundary (`docs/agentic/` for planning, `.agent/` for generated runtime state). Add planning roles as thin global skill entry points. Add dependency-free JSON-compatible YAML profile definitions, a resolver that emits immutable profile/rubric metadata, and a planning validator that checks both individual schemas and cross-document integrity.

**Tech Stack:** Python 3 standard library, existing JSON-schema subset validator, unittest, Markdown skill entry points, JSON-compatible YAML profile files.

---

### Task 1: Establish P0 regression coverage

**Files:**
- Modify: `skills/agentic-engineering-core/tests/test_skill_metadata.py`
- Modify: `skills/agentic-state-tools/tests/test_state_tools.py`
- Modify: `run_tests.py`

- [ ] Add failing tests for the specification path, terminal `next_action` cleanup, lease and lock cleanup, expired lock reclaim, workspace mismatch recovery, handoff reconciliation status, planning validation, profile/rubric resolution, and subprocess timeout behavior.
- [ ] Run `python run_tests.py` and confirm the new tests fail for the intended missing behavior while preserving the existing baseline failures.

### Task 2: Add missing planning skill entry points

**Files:**
- Create: `skills/agentic-brainstorm-facilitator/SKILL.md`
- Create: `skills/agentic-brainstorm-facilitator/agents/openai.yaml`
- Create: `skills/agentic-plan-architect/SKILL.md`
- Create: `skills/agentic-plan-architect/agents/openai.yaml`
- Create: `skills/agentic-plan-reviewer/SKILL.md`
- Create: `skills/agentic-plan-reviewer/agents/openai.yaml`
- Modify: `skills/agentic-engineering-core/SKILL.md`
- Modify: `skills/agentic-engineering-core/references/architecture/architecture.md`
- Modify: `skills/agentic_engineering_system_complete_specification.md`

- [ ] Define each role as a thin entry point that loads the shared core, reads project planning documents, and submits no canonical runtime writes directly.
- [ ] State the existing Primary-controlled routing decision explicitly and do not add a separate Orchestrator skill.
- [ ] Extend metadata tests through the existing directory discovery.

### Task 3: Add machine-validated planning contracts

**Files:**
- Create: `skills/agentic-state-tools/schemas/master-plan.schema.json`
- Create: `skills/agentic-state-tools/schemas/sub-plan.schema.json`
- Create: `skills/agentic-state-tools/schemas/planning-batch.schema.json`
- Create: `skills/agentic-state-tools/schemas/planning-task.schema.json`
- Create: `skills/agentic-state-tools/schemas/decision.schema.json`
- Create: `skills/agentic-state-tools/schemas/assumption.schema.json`
- Create: `skills/agentic-state-tools/schemas/risk.schema.json`
- Create: `skills/agentic-state-tools/schemas/change-request.schema.json`
- Create: `skills/agentic-state-tools/scripts/validate_planning.py`
- Modify: `skills/agentic-state-tools/SKILL.md`
- Modify: `skills/agentic-state-tools/tests/test_state_tools.py`

- [ ] Validate each document against its schema.
- [ ] Validate duplicate IDs, missing dependencies, dependency cycles, untraceable master requirements, overlapping write scopes, missing acceptance criteria, and unapproved architecture decisions.
- [ ] Return structured validation errors and a non-zero exit code without mutating `.agent/`.

### Task 4: Add project profile and rubric resolution

**Files:**
- Create: `skills/agentic-state-tools/profiles/prototype.yaml`
- Create: `skills/agentic-state-tools/profiles/quick_change.yaml`
- Create: `skills/agentic-state-tools/profiles/personal.yaml`
- Create: `skills/agentic-state-tools/profiles/course_project.yaml`
- Create: `skills/agentic-state-tools/profiles/internal_tool.yaml`
- Create: `skills/agentic-state-tools/profiles/production.yaml`
- Create: `skills/agentic-state-tools/profiles/high_risk.yaml`
- Create: `skills/agentic-state-tools/scripts/resolve_project_profile.py`
- Create: `skills/agentic-state-tools/scripts/resolve_rubric.py`
- Modify: `skills/agentic-state-tools/scripts/calculate_rubric_score.py`
- Modify: `skills/agentic-state-tools/scripts/create_review.py`
- Modify: `skills/agentic-state-tools/schemas/review.schema.json`
- Modify: `skills/agentic-state-tools/SKILL.md`
- Modify: `skills/agentic-state-tools/tests/test_state_tools.py`

- [ ] Resolve a named project profile and task type into a deterministic profile and rubric.
- [ ] Include rubric ID, version, hash, applicability decisions, resolved weights, and threshold in review payloads when a resolved rubric is supplied.
- [ ] Preserve direct score calculation compatibility while making the documented review workflow use resolved rubric metadata.

### Task 5: Unify state, handoff, and terminal cleanup

**Files:**
- Modify: `skills/agentic-state-tools/scripts/runtime_utils.py`
- Modify: `skills/agentic-state-tools/scripts/update_task_state.py`
- Modify: `skills/agentic-state-tools/scripts/create_review.py`
- Modify: `skills/agentic-state-tools/scripts/validate_transition.py`
- Modify: `skills/agentic-state-tools/schemas/task-state.schema.json`
- Modify: `skills/agentic-state-tools/schemas/event.schema.json`
- Modify: `skills/agentic-state-tools/schemas/handoff.schema.json`
- Modify: `skills/agentic-state-tools/scripts/acquire_lock.py`
- Modify: `skills/agentic-state-tools/scripts/release_lock.py`
- Modify: `skills/agentic-state-tools/SKILL.md`
- Modify: `skills/agentic-engineering-core/references/contracts/handoff-contract.md`
- Modify: `skills/agentic-state-tools/tests/test_state_tools.py`

- [ ] Make supported status values, event mappings, transition rules, and schema enums agree.
- [ ] Clear terminal `next_action`, remove the task lease, and release owned task/file/resource locks on terminal review transitions.
- [ ] Allow `NEEDS_RECONCILIATION` in the handoff contract and reject unsafe terminal cleanup when lock identity is ambiguous.
- [ ] Reclaim expired task/file/resource locks only with recorded evidence and never reclaim a live, unexpired owner.

### Task 6: Make recovery reconcile the actual workspace

**Files:**
- Modify: `skills/agentic-state-tools/scripts/inspect_recovery.py`
- Modify: `skills/agentic-state-tools/schemas/checkpoint.schema.json`
- Modify: `skills/agentic-state-tools/SKILL.md`
- Modify: `skills/agentic-runtime-recovery/references/recovery-model.md`
- Modify: `skills/agentic-state-tools/tests/test_state_tools.py`

- [ ] Inspect Git status, staged and unstaged changed paths, base commit, and untracked files when the task has active checkpoint evidence.
- [ ] Compare the workspace paths with checkpoint `files_modified` and classify mismatches as `NEEDS_RECONCILIATION`.
- [ ] Persist reconciliation evidence in the recovery result while preserving safe behavior for non-Git completed/queued fixture projects.

### Task 7: Repair packaging and test harness behavior

**Files:**
- Modify: `skills/agentic-engineering-core/tests/test_skill_metadata.py`
- Modify: `skills/agentic-state-tools/tests/test_state_tools.py`
- Modify: `skills/agentic_engineering_system_complete_specification.md`

- [ ] Resolve the specification path relative to the actual `skills/` directory.
- [ ] Add a bounded timeout to child test processes and convert timeout exceptions into explicit failures.
- [ ] Run focused tests, then the full suite, then inspect the changed-file list and final behavior against every P0 item.

### Task 8: Add P1 dispatch and routing helpers

**Files:**
- Create: `skills/agentic-state-tools/scripts/resolve_runnable_tasks.py`
- Create: `skills/agentic-state-tools/scripts/resolve_execution_mode.py`
- Create: `skills/agentic-state-tools/scripts/validate_dependency_graph.py`
- Create: `skills/agentic-state-tools/scripts/detect_scope_overlap.py`
- Create: `skills/agentic-engineering-core/references/wiki.md`

- [ ] Select only ready tasks whose dependencies are accepted.
- [ ] Resolve async/sync mode and report active write-scope conflicts without mutating runtime state.
- [ ] Route agents to the minimum relevant shared reference.

### Task 9: Add approval records

**Files:**
- Create: `skills/agentic-state-tools/schemas/approval.schema.json`
- Create: `skills/agentic-state-tools/scripts/record_approval.py`
- Modify: `skills/agentic-state-tools/scripts/runtime_utils.py`
- Modify: `skills/agentic-state-tools/schemas/event.schema.json`

- [ ] Validate and persist approval records under `.agent/approvals/`.
- [ ] Append an `APPROVAL_RECORDED` event without allowing direct canonical edits.

### Deferred Scope

Dashboard, distributed scheduling, remote state storage, automatic rollback, and multi-machine locking remain P2 capabilities as specified in the report.
