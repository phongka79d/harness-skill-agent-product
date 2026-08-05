# Harness Improvement Implementation Plan

**Plan ID:** `HARNESS-SUPERPOWERS-IMPLEMENTATION-01`  
**Version:** `1.0`  
**Source systems:** Existing Harness skill suite and the provided Superpowers skill suite  
**Purpose of this file:** Independent implementation plan delivered to the user. This plan file is not itself a Harness runtime skill and does not need to be placed inside `/skills`.

---

## 1. Objective

Improve the existing Harness skill suite by selectively adopting the strongest engineering disciplines from Superpowers while preserving Harness's stronger deterministic architecture:

- state machine and immutable runtime evidence;
- schema-validated artifacts;
- role separation;
- authorization and approval controls;
- lock, lease, worktree, and recovery safety;
- project profiles and risk-aware rubrics;
- bounded context and configurable model routing.

The improvements must add stronger behavioral discipline in the areas where Superpowers is currently better:

1. systematic root-cause debugging;
2. test-driven development with verifiable RED → GREEN evidence;
3. fresh verification before any completion claim;
4. specification review before code-quality review;
5. disciplined handling of review feedback;
6. deterministic skill selection before execution;
7. stronger brainstorming and implementation planning;
8. fresh context for implementers and reviewers;
9. safe parallel read-only investigation;
10. baseline verification for isolated workspaces;
11. controlled branch or worktree finalization;
12. behavioral testing of the skills themselves.

---

## 2. Critical Interpretation and Integration Constraint

This plan is an external implementation artifact. It may be stored anywhere convenient by the user.

However, **all Harness capabilities produced by implementing this plan must be integrated into the Harness `/skills` tree**.

That means every new or modified Harness-owned item must be placed in one of the following forms:

```text
skills/<existing-skill>/SKILL.md
skills/<existing-skill>/references/**
skills/<existing-skill>/refs/**
skills/<existing-skill>/schemas/**
skills/<existing-skill>/scripts/**
skills/<existing-skill>/examples/**
skills/<existing-skill>/config/**
skills/<existing-skill>/profiles/**
skills/<new-skill>/**
```

Files outside `/skills` may still be read or written as project artifacts, such as:

- source code;
- project `README.md`;
- project architecture documents;
- plans under the target project's documentation directory;
- `.agent/` runtime state;
- Git branches and worktrees;
- test and build output.

Those files are runtime inputs or outputs. They must not be the only location of a Harness policy, contract, reusable reference, schema, validator, or required script.

### 2.1 Integration rule

When Superpowers contains a useful skill, do not copy it as an isolated foreign subsystem. Adapt it into one of these forms:

- extend an existing Harness role skill;
- add a focused new Harness process skill;
- add a reference under the owning Harness skill;
- add a schema or deterministic validator under `agentic-state-tools`;
- add profile-aware configuration under `agentic-configuration` or `agentic-state-tools/profiles`;
- add examples and behavioral scenarios inside the owning skill.

### 2.2 Ownership rule

Use the following ownership model:

| Concern | Owning Harness component |
|---|---|
| Shared routing and universal invariants | `agentic-engineering-core` |
| Detailed cross-skill documentation | `agentic-engineering-wiki` |
| Runtime schemas, validators, state writes, evidence | `agentic-state-tools` |
| Profile and model configuration | `agentic-configuration` and profile files |
| Debugging procedure | New `agentic-systematic-debugging` skill |
| TDD execution behavior | `agentic-implementer` plus state-tools evidence |
| Completion verification | New `agentic-verification-before-completion` skill |
| Task review stages | `agentic-task-reviewer` |
| Review feedback handling | `agentic-implementer` and `agentic-task-reviewer` |
| Brainstorming | `agentic-brainstorm-facilitator` |
| Planning | `agentic-plan-architect` and `agentic-plan-reviewer` |
| Context isolation | `agentic-context-builder` |
| Read-only investigation | `agentic-explorer` |
| Integrated review | `agentic-batch-reviewer` |
| Worktree and final delivery | `agentic-state-tools`, with optional new finalizer skill |
| Skill authoring and skill behavior tests | New `agentic-skill-authoring` skill |

---

## 3. Design Decisions

### 3.1 Preserve Harness as the control plane

Superpowers provides process discipline. It must not replace Harness state, artifact identity, approval, recovery, or profile systems.

### 3.2 Convert prose rules into evidence-backed gates

A statement such as “run tests before completion” is insufficient. Where practical, Harness must store:

- command;
- exit code;
- output digest or evidence location;
- timestamp;
- run and attempt identity;
- task revision;
- workspace or Git hash;
- acceptance criterion covered.

### 3.3 Use profile-aware strictness

Not every project needs the same process weight.

| Profile | Expected strictness |
|---|---|
| `quick_change` | Minimal planning, focused verification, documented exceptions allowed |
| `personal` | Lightweight process, no unnecessary security or delivery ceremony |
| `prototype` | Fast iteration, characterization tests acceptable, assumptions explicit |
| `course_project` | Compact design, clear tasks, repeatable validation |
| `internal_tool` | Standard design, review, regression tests, maintainability checks |
| `production` | Full evidence gates, TDD for behavior changes, independent reviews |
| `high_risk` | Maximum evidence, approval, rollback, security, and recovery controls |

### 3.4 Avoid direct copies that conflict with Harness

Do not copy these Superpowers rules verbatim:

- “Load a skill if there is even a 1% chance it applies.”
- Full brainstorming ceremony for every trivial edit.
- Complete implementation code embedded in every plan step.
- Commit after every tiny implementation action.
- Delete all implementation whenever TDD order is violated, regardless of profile.
- Platform-specific assumptions about Claude Code, TodoWrite, or a specific subagent tool.
- Repeated user approval between tasks already covered by an approved plan and batch.

### 3.5 Keep `SKILL.md` concise

Each `SKILL.md` should remain a role or process router. Detailed protocol, schema explanation, examples, and anti-rationalization guidance should be placed in `references/`, `refs/`, `schemas/`, `scripts/`, or `examples/` and loaded only when applicable.

---

## 4. Target Architecture After Improvement

### 4.1 New skills

```text
skills/
├── agentic-systematic-debugging/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/debugging-protocol.md
│   ├── references/root-cause-tracing.md
│   ├── references/condition-based-waiting.md
│   ├── references/escalation-and-stop-rules.md
│   ├── examples/debug-investigation.example.json
│   └── examples/debugging-pressure-scenarios.md
│
├── agentic-verification-before-completion/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/completion-gate.md
│   ├── references/evidence-freshness.md
│   ├── references/claim-to-evidence-mapping.md
│   └── examples/completion-claim.example.json
│
├── agentic-delivery-finalizer/                 # recommended, optional if folded into state-tools/core
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/delivery-outcomes.md
│   ├── references/merge-and-cleanup-safety.md
│   └── examples/delivery-decision.example.json
│
└── agentic-skill-authoring/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── references/skill-design-guidelines.md
    ├── references/behavioral-testing.md
    ├── references/rationalization-hardening.md
    ├── schemas/behavior-scenario.schema.json
    ├── scripts/run_behavior_scenarios.py
    └── examples/*.yaml
```

### 4.2 State-tools additions

```text
skills/agentic-state-tools/
├── schemas/
│   ├── debug-investigation.schema.json
│   ├── verification-evidence.schema.json
│   ├── completion-claim.schema.json
│   ├── review-resolution.schema.json
│   ├── skill-routing.schema.json
│   ├── workspace-baseline.schema.json
│   └── delivery-decision.schema.json
├── scripts/
│   ├── create_debug_investigation.py
│   ├── record_verification_evidence.py
│   ├── verify_completion_claim.py
│   ├── create_review_resolution.py
│   ├── resolve_skill_route.py
│   ├── capture_workspace_baseline.py
│   ├── finalize_delivery.py
│   └── validate_no_placeholders.py
└── examples/
    ├── debug-investigation.json
    ├── verification-evidence.json
    ├── completion-claim.json
    ├── review-resolution.json
    ├── skill-routing.json
    ├── workspace-baseline.json
    └── delivery-decision.json
```

The exact script names may be adjusted to match existing naming conventions, but their responsibilities must remain explicit and non-overlapping.

---

# 5. Implementation Roadmap

## Batch 1 — Root-Cause Debugging and Repair Discipline

**Goal:** Prevent repair agents from guessing, patching symptoms, or repeating failed fixes.

### HSP-101 — Create `agentic-systematic-debugging`

**Priority:** P0  
**Dependencies:** None

**Superpowers sources to adapt**

- `systematic-debugging/SKILL.md`
- `systematic-debugging/root-cause-tracing.md`
- `systematic-debugging/condition-based-waiting.md`
- `systematic-debugging/defense-in-depth.md`

**Files to create**

```text
skills/agentic-systematic-debugging/SKILL.md
skills/agentic-systematic-debugging/agents/openai.yaml
skills/agentic-systematic-debugging/references/debugging-protocol.md
skills/agentic-systematic-debugging/references/root-cause-tracing.md
skills/agentic-systematic-debugging/references/condition-based-waiting.md
skills/agentic-systematic-debugging/references/escalation-and-stop-rules.md
skills/agentic-systematic-debugging/examples/debug-investigation.example.json
```

**Required workflow**

1. Reproduce the failure or explicitly document why reproduction is impossible.
2. Capture error output, environment, triggering input, and recent relevant changes.
3. Trace the failing value or state backward through the data flow.
4. Find a working pattern in the same repository when available.
5. State exactly one falsifiable hypothesis.
6. Run the smallest experiment capable of confirming or rejecting it.
7. Record the result before proposing a fix.
8. Add a regression test or equivalent reproducible check.
9. Apply the smallest root-cause fix.
10. Run focused and broader verification.

**Hard prohibitions**

- Do not modify implementation before producing investigation evidence, except temporary diagnostic instrumentation that is explicitly recorded.
- Do not combine multiple speculative fixes in one attempt.
- Do not label a symptom as the root cause without a trace.
- Do not use arbitrary sleep when a condition-based wait is possible.
- Do not repeat an identical failed hypothesis.

**Escalation rule**

After three rejected hypotheses or materially similar failed fixes:

- stop ordinary repair;
- mark the task `BLOCKED` or `ESCALATED` using existing Harness states;
- request decomposition, additional context, a different model, or architecture review;
- do not silently add a fourth speculative fix.

Do not add a new global state-machine status unless the existing `BLOCKED` and `ESCALATED` states are proven insufficient.

**Acceptance criteria**

- The skill is discoverable from its description using symptoms such as flaky, inconsistent, unexplained failure, regression, failing test, timeout, race, or incorrect output.
- The process separates evidence, hypothesis, experiment, result, and root cause.
- The stop rule is explicit.
- The skill does not overlap runtime recovery; recovery handles interrupted state and uncertain side effects, while debugging handles product or code defects.

---

### HSP-102 — Add a structured debugging artifact

**Priority:** P0  
**Dependencies:** HSP-101

**Files to create**

```text
skills/agentic-state-tools/schemas/debug-investigation.schema.json
skills/agentic-state-tools/scripts/create_debug_investigation.py
skills/agentic-state-tools/examples/debug-investigation.json
```

**Minimum schema fields**

```text
investigation_id
schema_version
task_id
run_id
attempt_id
task_revision
symptom
reproduction_status
reproduction_steps
observed_output
expected_output
environment_facts
recent_changes
data_flow_trace
working_reference
hypotheses[]
current_hypothesis
experiment
experiment_result
root_cause
regression_check
fix_attempt_count
status
created_at
updated_at
```

Each hypothesis entry must contain:

```text
hypothesis_id
statement
predicted_observation
experiment
result
outcome: CONFIRMED | REJECTED | INCONCLUSIVE
```

**Integration files to modify**

```text
skills/agentic-state-tools/SKILL.md
skills/agentic-state-tools/references/artifact-contracts.md
skills/agentic-engineering-wiki/SKILL.md
skills/agentic-engineering-wiki/refs/workflows/recovery.md
skills/agentic-engineering-wiki/refs/workflows/execution.md
skills/agentic-implementer/SKILL.md
skills/agentic-implementer/references/implementation-loop.md
```

**Enforcement**

A repair dispatch must include a valid `investigation_id`. The implementer must not return `FIXED` or `PASS` when the linked investigation lacks a confirmed root cause and verification evidence.

**Acceptance criteria**

- Invalid or incomplete investigations are rejected without partial writes.
- Attempt and task identity are validated.
- Repeated hypothesis IDs or contradictory terminal states are rejected.
- The artifact remains readable after future schema evolution through a version field.

---

## Batch 2 — TDD Evidence and Verification Before Completion

**Goal:** Replace unverifiable “test-first” and “completed” claims with fresh, task-bound evidence.

### HSP-201 — Upgrade the testing contract to evidence-backed TDD

**Priority:** P0  
**Dependencies:** HSP-102

**Superpowers sources to adapt**

- `test-driven-development/SKILL.md`
- `test-driven-development/testing-anti-patterns.md`
- `verification-before-completion/SKILL.md`

**Files to modify**

```text
skills/agentic-implementer/SKILL.md
skills/agentic-implementer/references/implementation-loop.md
skills/agentic-engineering-wiki/refs/policies/validation.md
skills/agentic-engineering-wiki/refs/contracts/testing.md
skills/agentic-engineering-wiki/refs/roles/implementer.md
skills/agentic-plan-architect/SKILL.md
skills/agentic-state-tools/schemas/planning-task.schema.json
skills/agentic-state-tools/schemas/handoff.schema.json
skills/agentic-state-tools/profiles/*.yaml
```

**Required TDD cycle for behavior changes**

1. Identify the behavior and the smallest test that expresses it.
2. Run the test and observe failure for the intended reason.
3. Store RED evidence tied to the current workspace.
4. Implement the minimum change.
5. Run the focused test and observe success.
6. Store GREEN evidence.
7. Refactor without changing behavior.
8. Re-run focused tests after every material edit.
9. Run the broader suite required by the active profile.

**Structured verification case**

Replace or supplement loose verification strings with a structure containing:

```text
verification_case_id
acceptance_criterion_ids[]
verification_type
red_required
red_command
red_exit_code
red_failure_signature
red_workspace_hash
red_recorded_at
green_command
green_exit_code
green_workspace_hash
green_recorded_at
broad_command
broad_exit_code
broad_workspace_hash
verified_at
run_id
attempt_id
task_revision
status
```

**Profile behavior**

- `production`, `high_risk`: RED → GREEN → broad suite is mandatory for behavior changes and bug fixes.
- `internal_tool`, `course_project`: RED → GREEN is mandatory when a viable test harness exists; broad suite based on risk.
- `prototype`, `quick_change`, `personal`: characterization check or focused reproducible command may replace strict TDD only through a recorded exception.

**Allowed exceptions**

- generated artifacts where source-of-truth tests exist elsewhere;
- throwaway prototype explicitly marked as such;
- data-only or configuration-only change without an executable harness;
- emergency change authorized by the active approval policy.

Every exception must include reason, approver or profile rule, alternative verification, and expiry or follow-up when applicable.

**Anti-patterns to document**

- writing a test that only verifies the mock;
- adding production-only hooks solely for tests;
- passing a test that never failed for the intended reason;
- asserting implementation details instead of behavior;
- claiming full coverage from a focused test;
- preserving stale GREEN evidence after later edits.

**Acceptance criteria**

- A behavior-change handoff cannot pass with only a command string and no result.
- RED evidence proves the test failed for the missing behavior, not due to syntax, environment, or unrelated failure.
- Any material edit after GREEN marks affected evidence stale.
- Profile exceptions are explicit and machine-readable.

---

### HSP-202 — Create `agentic-verification-before-completion`

**Priority:** P0  
**Dependencies:** HSP-201

**Files to create**

```text
skills/agentic-verification-before-completion/SKILL.md
skills/agentic-verification-before-completion/agents/openai.yaml
skills/agentic-verification-before-completion/references/completion-gate.md
skills/agentic-verification-before-completion/references/evidence-freshness.md
skills/agentic-verification-before-completion/references/claim-to-evidence-mapping.md
skills/agentic-verification-before-completion/examples/completion-claim.example.json
```

**Trigger conditions**

Use before any claim equivalent to:

- complete;
- fixed;
- passed;
- ready;
- resolved;
- successful;
- safe to merge;
- safe to release.

**Completion gate**

For every claim:

1. State the exact claim.
2. Identify the command or evidence that proves it.
3. Run the full command in the current attempt.
4. Inspect exit code and relevant output.
5. Bind the result to current workspace or Git hash.
6. Map evidence to acceptance criteria.
7. Report skipped, not-applicable, or failing checks explicitly.
8. Only then emit the claim.

**Evidence freshness rules**

Evidence is stale when any of the following changes after collection:

- relevant file content;
- task revision;
- plan revision;
- run or attempt identity;
- dependency version or lockfile relevant to the check;
- base commit or workspace hash;
- build configuration relevant to the check.

**Acceptance criteria**

- The skill explicitly rejects “it should work,” prior-run evidence, implementer confidence, and subagent success messages as proof.
- Lint, typecheck, unit test, integration test, build, packaging, and requirement coverage remain separate claims unless one command genuinely proves more than one.
- Failure output is reported honestly without converting it into a partial PASS.

---

### HSP-203 — Add verification and completion schemas/scripts

**Priority:** P0  
**Dependencies:** HSP-202

**Files to create**

```text
skills/agentic-state-tools/schemas/verification-evidence.schema.json
skills/agentic-state-tools/schemas/completion-claim.schema.json
skills/agentic-state-tools/scripts/record_verification_evidence.py
skills/agentic-state-tools/scripts/verify_completion_claim.py
skills/agentic-state-tools/examples/verification-evidence.json
skills/agentic-state-tools/examples/completion-claim.json
```

**Files to modify**

```text
skills/agentic-state-tools/scripts/create_handoff.py
skills/agentic-state-tools/scripts/create_review.py
skills/agentic-state-tools/scripts/create_batch_review.py
skills/agentic-state-tools/references/artifact-contracts.md
skills/agentic-state-tools/SKILL.md
```

**Required validation behavior**

Reject a PASS-like outcome when:

- the evidence belongs to another run, attempt, task revision, or workspace;
- the command is missing;
- exit code is missing or non-zero for a successful claim;
- evidence predates the last relevant edit;
- acceptance criteria have no evidence mapping;
- only a summarized agent statement is provided;
- output indicates skipped or failed checks that the claim hides.

**Backward compatibility**

Existing legacy handoffs may remain readable, but they must be marked `LEGACY_UNVERIFIED` and must not satisfy new strict PASS gates for production or high-risk profiles.

**Acceptance criteria**

- Strict-mode handoffs cannot pass without current verification evidence.
- The validator returns actionable errors naming the missing or stale evidence.
- Existing artifact identity and atomic write guarantees are preserved.

---

## Batch 3 — Two-Stage Review and Feedback Resolution

**Goal:** Ensure the implementation satisfies the approved task before spending review effort on code quality, and prevent blind compliance with reviewer suggestions.

### HSP-301 — Split task review into two stages

**Priority:** P0  
**Dependencies:** HSP-203

**Superpowers sources to adapt**

- `subagent-driven-development/spec-reviewer-prompt.md`
- `subagent-driven-development/code-quality-reviewer-prompt.md`
- `requesting-code-review/SKILL.md`

**Recommended approach**

Keep the existing `agentic-task-reviewer` role but add a required stage field:

```text
SPEC_COMPLIANCE
CODE_QUALITY
```

Do not create two independent reviewer skills unless the existing role becomes too large or routing becomes ambiguous.

**Files to modify**

```text
skills/agentic-task-reviewer/SKILL.md
skills/agentic-task-reviewer/references/review-contract.md
skills/agentic-task-reviewer/references/severity.md
skills/agentic-engineering-wiki/refs/workflows/review.md
skills/agentic-engineering-wiki/refs/roles/task-reviewer.md
skills/agentic-engineering-wiki/refs/rubrics/task.md
skills/agentic-state-tools/schemas/review.schema.json
skills/agentic-state-tools/schemas/review-contract.schema.json
skills/agentic-state-tools/scripts/create_review.py
skills/agentic-state-tools/scripts/review_contract.py
```

**Stage 1 — Specification compliance**

Review only:

- required behavior;
- acceptance criteria;
- approved architecture decisions;
- exact task scope;
- forbidden and out-of-scope work;
- write-scope violations;
- missing or extra behavior;
- evidence freshness and mapping.

Stage 1 must not give a passing result based on a quality score when a requirement is missing.

**Stage 2 — Code quality**

Run only after Stage 1 passes. Review:

- correctness under edge cases;
- clarity and maintainability;
- reuse of existing patterns;
- unnecessary abstractions and YAGNI violations;
- test quality;
- security and performance when applicable to the resolved rubric;
- compatibility and migration risk.

**Re-review rule**

- A specification finding returns the task to implementation and requires a new Stage 1 review.
- A code-quality finding requires a new Stage 2 review after correction.
- A Stage 2 fix that changes behavior or scope invalidates Stage 1 and sends the task back to Stage 1.

**Acceptance criteria**

- Code-quality scoring cannot hide missing requirements.
- Stage ordering is validated by artifact identity.
- Reviewers receive task contract, diff, evidence, and decisions, but not implementer private reasoning.
- Batch review consumes only tasks with valid final Stage 1 and Stage 2 outcomes as required by profile.

---

### HSP-302 — Add review feedback resolution contract

**Priority:** P0  
**Dependencies:** HSP-301

**Superpowers source to adapt**

- `receiving-code-review/SKILL.md`

**Files to create**

```text
skills/agentic-state-tools/schemas/review-resolution.schema.json
skills/agentic-state-tools/scripts/create_review_resolution.py
skills/agentic-state-tools/examples/review-resolution.json
skills/agentic-implementer/references/review-feedback-resolution.md
```

**Files to modify**

```text
skills/agentic-implementer/SKILL.md
skills/agentic-task-reviewer/SKILL.md
skills/agentic-engineering-wiki/refs/workflows/review.md
skills/agentic-engineering-wiki/refs/roles/implementer.md
skills/agentic-state-tools/references/artifact-contracts.md
```

**Finding resolution states**

```text
ACCEPTED
REJECTED_WITH_EVIDENCE
NEEDS_CLARIFICATION
SUPERSEDED
FIXED_PENDING_REREVIEW
CLOSED
```

**Resolution rules**

1. Read the complete finding and evidence.
2. Verify it against the current codebase and contract.
3. Check whether the suggestion conflicts with an approved decision or compatibility requirement.
4. Search for actual usage before adding “proper” or generalized functionality.
5. Resolve ambiguity before editing.
6. Apply one coherent correction.
7. Run targeted verification.
8. Mark `FIXED_PENDING_REREVIEW`.
9. Only the reviewer may mark `CLOSED` after inspecting new evidence.

**Rejection rule**

A finding may be rejected only with concrete evidence, such as:

- task contract contradicts the suggestion;
- existing tests or behavior prove it is incorrect;
- compatibility contract forbids the change;
- the requested feature is outside approved scope;
- another accepted decision supersedes it.

**Acceptance criteria**

- Implementers cannot silently ignore findings.
- Implementers are not forced to obey technically incorrect findings.
- Every non-closed finding has a visible status and owner.
- Closed findings retain links to the correction and re-review evidence.

---

## Batch 4 — Skill Routing, Brainstorming, and Executable Plans

**Goal:** Ensure the agent selects the correct process before action and receives plans with enough detail to execute without guessing.

### HSP-401 — Add deterministic skill routing

**Priority:** P1  
**Dependencies:** HSP-301

**Superpowers source to adapt**

- `using-superpowers/SKILL.md`

**Files to create**

```text
skills/agentic-state-tools/schemas/skill-routing.schema.json
skills/agentic-state-tools/scripts/resolve_skill_route.py
skills/agentic-state-tools/examples/skill-routing.json
skills/agentic-engineering-core/references/policies/skill-routing.md
```

**Files to modify**

```text
skills/agentic-engineering-core/SKILL.md
skills/agentic-engineering-wiki/SKILL.md
skills/agentic-engineering-wiki/refs/policies/delegation.md
skills/agentic-engineering-wiki/refs/workflows/execution.md
skills/agentic-configuration/config/agentic-config.yaml
skills/agentic-configuration/schemas/agentic-config.schema.json
skills/agentic-state-tools/schemas/dispatch.schema.json
skills/agentic-state-tools/scripts/dispatch_contract.py
skills/agentic-state-tools/scripts/dispatch_task.py
```

**Routing precedence**

```text
Process skill → Role skill → Domain-specific skill
```

Examples:

```text
Ambiguous feature request
→ agentic-brainstorm-facilitator
→ agentic-plan-architect

Bug or failing behavior
→ agentic-systematic-debugging
→ agentic-implementer
→ agentic-verification-before-completion

Completed implementation
→ agentic-verification-before-completion
→ agentic-task-reviewer (SPEC_COMPLIANCE)
→ agentic-task-reviewer (CODE_QUALITY)
```

**Routing inputs**

- user intent;
- current task state;
- task type;
- repair flag;
- risk flags;
- active project profile;
- requested role;
- available configured skills.

**Routing artifact fields**

```text
routing_id
intent_classification
task_type
current_state
risk_flags
applicable_skills[]
required_skills[]
loaded_skills[]
routing_reason
routing_policy_version
```

**Acceptance criteria**

- Dispatch fails when a mandatory process skill is omitted.
- Routing does not use the Superpowers “1% chance” rule.
- A role skill cannot bypass a mandatory debugging, planning, or verification process.
- The core remains concise and links to the detailed routing policy.

---

### HSP-402 — Upgrade Brainstorm Facilitator

**Priority:** P1  
**Dependencies:** HSP-401

**Superpowers source to adapt**

- `brainstorming/SKILL.md`
- `brainstorming/spec-document-reviewer-prompt.md`

**Files to modify**

```text
skills/agentic-brainstorm-facilitator/SKILL.md
skills/agentic-engineering-wiki/refs/roles/brainstorm-facilitator.md
skills/agentic-engineering-wiki/refs/workflows/planning.md
```

**Files to create**

```text
skills/agentic-brainstorm-facilitator/references/brainstorming-protocol.md
skills/agentic-brainstorm-facilitator/references/design-self-review.md
skills/agentic-brainstorm-facilitator/examples/brainstorm-handoff.example.md
```

**Required improvements**

- Inspect relevant project context before proposing architecture.
- Separate facts, assumptions, constraints, unknowns, and decisions.
- Identify independent subsystems and decompose over-broad requests.
- Present two or three materially different viable approaches when a real choice exists.
- Explain trade-offs and recommend one approach.
- Define scope, non-goals, error handling, testing strategy, and completion conditions.
- Ask one focused question at a time only when user input is genuinely required.
- Run a design self-review for contradiction, ambiguity, placeholder, missing requirement, and unnecessary scope.

**Profile scaling**

- `quick_change` and `personal`: short decision record.
- `prototype`: lightweight design and explicit assumptions.
- `course_project` and `internal_tool`: compact structured design.
- `production` and `high_risk`: full design handoff and required approval.

**Acceptance criteria**

- The role does not create unnecessary ceremony for small tasks.
- It never silently resolves material unknowns.
- The handoff gives the Plan Architect enough approved direction to plan without redesigning.

---

### HSP-403 — Make plans executable and self-validating

**Priority:** P1  
**Dependencies:** HSP-402, HSP-201

**Superpowers sources to adapt**

- `writing-plans/SKILL.md`
- `writing-plans/plan-document-reviewer-prompt.md`
- `executing-plans/SKILL.md`

**Files to modify**

```text
skills/agentic-plan-architect/SKILL.md
skills/agentic-plan-reviewer/SKILL.md
skills/agentic-engineering-wiki/refs/contracts/planning.md
skills/agentic-engineering-wiki/refs/workflows/planning.md
skills/agentic-engineering-wiki/refs/roles/plan-architect.md
skills/agentic-engineering-wiki/refs/roles/plan-reviewer.md
skills/agentic-state-tools/schemas/planning-task.schema.json
skills/agentic-state-tools/scripts/validate_planning.py
```

**Files to create**

```text
skills/agentic-plan-architect/references/executable-task-design.md
skills/agentic-plan-architect/references/file-responsibility-map.md
skills/agentic-state-tools/scripts/validate_no_placeholders.py
```

**Required task fields**

- objective;
- prerequisite decisions;
- exact file paths;
- relevant symbols or interfaces when known;
- files allowed to change;
- files forbidden to change;
- dependency task IDs;
- implementation steps;
- TDD or alternative validation steps;
- expected RED result when required;
- expected GREEN result;
- exact verification commands;
- acceptance criteria IDs;
- rollback or recovery note when risk requires it;
- handoff expectations.

**File responsibility map**

Before creating atomic tasks, the plan must define which component owns each file or concern. This reduces overlapping write scopes and architecture drift.

**Placeholder validator**

Reject vague instructions such as:

```text
TBD
TODO
handle edge cases
add validation
write tests
make it robust
similar to the previous task
implement as appropriate
```

unless accompanied by precise, testable details.

**Do not require full code in every task**

Include code snippets only when necessary to lock down:

- public interface;
- schema;
- migration shape;
- test fixture;
- algorithm that cannot be safely inferred;
- cross-task type or protocol contract.

**Plan self-review**

The Plan Reviewer must check:

- every requirement maps to a task and acceptance criterion;
- no task contains hidden architecture decisions;
- no conflicting file ownership;
- dependencies form a valid graph;
- symbols and interfaces are consistent across tasks;
- no placeholder or unverifiable instruction remains;
- task size is bounded and suitable for one implementer attempt.

**Acceptance criteria**

- An implementer can execute a task without reading the full master plan.
- Verification is specific enough to run directly.
- Plans do not duplicate entire implementation bodies.
- Repeated or overlapping task scope is rejected.

---

## Batch 5 — Fresh Context and Safe Parallel Investigation

**Goal:** Reduce context contamination, reviewer bias, and unnecessary serial exploration.

### HSP-501 — Enforce fresh bounded context per attempt

**Priority:** P1  
**Dependencies:** HSP-403

**Superpowers source to adapt**

- `subagent-driven-development/SKILL.md`

**Files to modify**

```text
skills/agentic-context-builder/SKILL.md
skills/agentic-context-builder/references/context-contract.md
skills/agentic-engineering-wiki/refs/roles/context-builder.md
skills/agentic-engineering-wiki/refs/workflows/execution.md
skills/agentic-state-tools/schemas/context.schema.json
skills/agentic-state-tools/scripts/create_context.py
skills/agentic-state-tools/schemas/attempt-reissue.schema.json
skills/agentic-state-tools/scripts/reissue_task_attempt.py
```

**Required context behavior**

Each implementer attempt receives a newly generated context package containing only:

- active task contract;
- inherited decisions and constraints;
- relevant source and test files;
- repository patterns;
- unresolved review findings;
- necessary prior evidence;
- explicit forbidden scope.

Each reviewer receives:

- task contract;
- approved decisions;
- actual diff or changed files;
- verification evidence;
- applicable rubric;
- previous findings relevant to re-review.

The reviewer must not receive or depend on the implementer's private chain of reasoning or confidence statements.

**Context artifact additions**

```text
context_revision
context_purpose
recipient_role
source_items[]
source_hashes[]
inclusion_reasons[]
excluded_sensitive_items[]
previous_context_id
context_delta
```

**Re-dispatch rule**

A failed or blocked attempt may be reissued only when at least one of these changes:

- corrected task contract;
- additional relevant context;
- context removed to reduce confusion;
- task decomposition;
- model escalation allowed by config;
- approved architecture decision;
- new debugging evidence.

Do not repeat the same payload to the same model without a documented delta.

**Acceptance criteria**

- Implementers are not required to scan the whole repository.
- Reviewers remain independent.
- Reissued attempts contain a visible reason and context delta.
- Context budgets and secret redaction remain enforced.

---

### HSP-502 — Separate parallel read-only exploration from async writing

**Priority:** P1  
**Dependencies:** HSP-501

**Superpowers source to adapt**

- `dispatching-parallel-agents/SKILL.md`

**Files to modify**

```text
skills/agentic-explorer/SKILL.md
skills/agentic-explorer/references/exploration-protocol.md
skills/agentic-engineering-wiki/refs/contracts/async-execution.md
skills/agentic-engineering-wiki/refs/workflows/execution.md
skills/agentic-configuration/config/agentic-config.yaml
skills/agentic-configuration/schemas/agentic-config.schema.json
skills/agentic-state-tools/schemas/execution-policy.schema.json
skills/agentic-state-tools/scripts/resolve_execution_mode.py
```

**Execution modes**

```text
SYNC_WRITE
PARALLEL_READ_ONLY
ASYNC_ISOLATED_WRITE
```

**`PARALLEL_READ_ONLY` eligibility**

- each explorer has an independent investigation question;
- all explorers are forbidden from writing;
- context and token capacity are available;
- no explorer depends on another explorer's result;
- outputs can be reconciled deterministically.

No worktree is required because writes are prohibited.

**`ASYNC_ISOLATED_WRITE` eligibility**

Retain existing Harness requirements:

- configuration explicitly enables it;
- dependencies are accepted;
- write scopes are disjoint;
- capacity exists;
- isolation proof is verified;
- task-to-branch-to-worktree identity is bound;
- merges remain sequential and approval-backed.

**Acceptance criteria**

- Read-only parallelism can be enabled without enabling async implementation.
- Explorer outputs identify facts, inferences, unknowns, and inspected files.
- Conflicting findings are reconciled before implementation.
- Async write remains disabled by default unless the current config explicitly enables it.

---

## Batch 6 — Worktree Baseline and Delivery Finalization

**Goal:** Prevent implementation on a broken baseline and make branch completion explicit and safe.

### HSP-601 — Capture a clean workspace baseline

**Priority:** P1  
**Dependencies:** HSP-203, HSP-502

**Superpowers source to adapt**

- `using-git-worktrees/SKILL.md`

**Files to create**

```text
skills/agentic-state-tools/schemas/workspace-baseline.schema.json
skills/agentic-state-tools/scripts/capture_workspace_baseline.py
skills/agentic-state-tools/examples/workspace-baseline.json
```

**Files to modify**

```text
skills/agentic-state-tools/scripts/worktree_manager.py
skills/agentic-state-tools/scripts/capture_workspace.py
skills/agentic-state-tools/schemas/worktree.schema.json
skills/agentic-state-tools/schemas/isolation-proof.schema.json
skills/agentic-state-tools/references/artifact-contracts.md
skills/agentic-engineering-wiki/refs/contracts/async-execution.md
skills/agentic-engineering-wiki/refs/workflows/execution.md
```

**Baseline procedure**

1. Detect whether the current environment is already isolated.
2. Record base branch and base commit.
3. Verify the worktree path and ownership.
4. Run dependency setup only through approved project commands.
5. Run the profile-required baseline verification.
6. Record existing failures separately from new regressions.
7. Block implementation when baseline is unexpectedly red, unless an approved decision permits proceeding.

**Minimum artifact fields**

```text
baseline_id
task_id
run_id
worktree_path
branch
base_commit
workspace_hash
setup_command
setup_exit_code
baseline_commands[]
baseline_results[]
known_failures[]
status
captured_at
```

**Acceptance criteria**

- Existing failures cannot be misreported as implementation regressions.
- A baseline tied to another worktree or base commit is rejected.
- Worktree setup does not overwrite user-owned directories.
- The implementation gate clearly distinguishes `CLEAN`, `KNOWN_FAILURES_APPROVED`, and `BLOCKED`.

---

### HSP-602 — Add controlled delivery finalization

**Priority:** P1  
**Dependencies:** HSP-601, HSP-301

**Superpowers source to adapt**

- `finishing-a-development-branch/SKILL.md`

**Recommended files to create**

```text
skills/agentic-delivery-finalizer/SKILL.md
skills/agentic-delivery-finalizer/agents/openai.yaml
skills/agentic-delivery-finalizer/references/delivery-outcomes.md
skills/agentic-delivery-finalizer/references/merge-and-cleanup-safety.md
skills/agentic-delivery-finalizer/examples/delivery-decision.example.json
skills/agentic-state-tools/schemas/delivery-decision.schema.json
skills/agentic-state-tools/scripts/finalize_delivery.py
skills/agentic-state-tools/examples/delivery-decision.json
```

**Files to modify**

```text
skills/agentic-state-tools/scripts/commit_batch.py
skills/agentic-state-tools/scripts/merge_worktree.py
skills/agentic-state-tools/scripts/verify_terminal_cleanup.py
skills/agentic-engineering-core/SKILL.md
skills/agentic-engineering-wiki/refs/workflows/execution.md
skills/agentic-engineering-wiki/refs/contracts/transactions.md
```

**Supported outcomes**

```text
MERGE_LOCAL
PUSH_AND_CREATE_PR
KEEP_BRANCH_AND_WORKTREE
DISCARD_BRANCH_AND_WORKTREE
```

**Safety rules**

- Final verification must run before presenting or executing a successful delivery outcome.
- A local merge must be verified again on the merged result.
- A pull-request outcome must preserve the worktree for review fixes unless policy says otherwise.
- Cleanup applies only to Harness-owned branches and worktrees proven by identity.
- Discard requires typed destructive approval under the existing approval policy.
- The finalizer must use state-tools and must not run uncontrolled Git commands outside the established contracts.

**Acceptance criteria**

- No worktree is removed before required evidence is persisted.
- A merge conflict produces a blocked or reconciliation result, not an automatic destructive repair.
- Delivery outcome, approver, hashes, and cleanup evidence are recorded.
- Batch Reviewer reviews integration but does not perform the merge itself.

---

## Batch 7 — Behavioral Testing of the Skill Suite

**Goal:** Test whether agents actually follow the skills under pressure, not only whether schemas and links are valid.

### HSP-701 — Create `agentic-skill-authoring`

**Priority:** P1  
**Dependencies:** HSP-401

**Superpowers source to adapt**

- `writing-skills/SKILL.md`
- `writing-skills/testing-skills-with-subagents.md`
- `writing-skills/persuasion-principles.md`
- `systematic-debugging/test-pressure-*.md`

**Files to create**

```text
skills/agentic-skill-authoring/SKILL.md
skills/agentic-skill-authoring/agents/openai.yaml
skills/agentic-skill-authoring/references/skill-design-guidelines.md
skills/agentic-skill-authoring/references/behavioral-testing.md
skills/agentic-skill-authoring/references/rationalization-hardening.md
skills/agentic-skill-authoring/schemas/behavior-scenario.schema.json
skills/agentic-skill-authoring/scripts/run_behavior_scenarios.py
skills/agentic-skill-authoring/examples/*.yaml
```

**Skill design guidance**

- descriptions must contain concrete triggers and symptoms;
- use process-oriented names and clear scope;
- keep high-frequency `SKILL.md` files short;
- move details into references;
- include explicit boundaries and stop conditions;
- distinguish rigid protocols from flexible guidance;
- include common rationalizations and direct counters only when they improve compliance.

**Behavioral test cycle**

```text
RED
→ run the scenario without the new or modified rule
→ capture the incorrect behavior and rationalization

GREEN
→ add or update the skill
→ rerun the same scenario

REFACTOR
→ add stronger pressure or ambiguity
→ close newly discovered loopholes
→ rerun all relevant scenarios
```

**Required initial scenarios**

1. Agent is told a fix is urgent and skips root-cause investigation.
2. Agent writes implementation before observing a failing test.
3. Agent claims completion using test output from before the final edit.
4. Reviewer recommends an out-of-scope feature under “best practice.”
5. Agent repeats the same failed dispatch without context change.
6. Agent uses arbitrary sleep instead of waiting for a condition.
7. Agent performs code-quality review before checking specification compliance.
8. Agent attempts destructive worktree cleanup without typed approval.
9. Agent skips a process skill because the task looks trivial.
10. Agent loads excessive skills and context for a small quick-change task.

**Acceptance criteria**

- Scenarios are stored inside the owning skill tree.
- Results distinguish pass, fail, blocked, and inconclusive.
- Scenario output records the model/config used but does not hard-code a single provider.
- A skill cannot be considered behaviorally hardened based only on prose inspection.

---

### HSP-702 — Add rationalization resistance to critical skills

**Priority:** P1  
**Dependencies:** HSP-701, HSP-101, HSP-202

**Files to modify**

```text
skills/agentic-systematic-debugging/references/escalation-and-stop-rules.md
skills/agentic-verification-before-completion/references/completion-gate.md
skills/agentic-implementer/references/implementation-loop.md
skills/agentic-task-reviewer/references/review-contract.md
skills/agentic-engineering-core/references/policies/skill-routing.md
```

**Common rationalizations to address**

- “This change is too small to need the process.”
- “I already know what the bug is.”
- “The old test result is still valid.”
- “The reviewer is probably right, so I should just implement it.”
- “The test failed, but not for the exact reason; that is close enough.”
- “A fourth fix attempt is faster than escalation.”
- “The linter passed, so the build is fine.”
- “The subagent reported success, so review can pass.”
- “The project is personal, so no verification is needed.”

**Implementation style**

Do not fill every `SKILL.md` with long warning tables. Keep detailed rationalization examples in references and put only the highest-value stop conditions in the skill entry point.

**Acceptance criteria**

- Each critical behavior has at least one pressure scenario.
- Rules do not become needlessly rigid for low-risk profiles.
- The resulting skills remain readable and token-efficient.

---

## Batch 8 — Integration, Migration, and Release Readiness

**Goal:** Connect all new capabilities to the existing Harness without breaking current artifacts or duplicating policy.

### HSP-801 — Update shared Wiki routing and cross-skill integration

**Priority:** P0  
**Dependencies:** HSP-101 through HSP-702

**Files to modify**

```text
skills/agentic-engineering-wiki/SKILL.md
skills/agentic-engineering-wiki/refs/architecture/architecture.md
skills/agentic-engineering-wiki/refs/workflows/planning.md
skills/agentic-engineering-wiki/refs/workflows/execution.md
skills/agentic-engineering-wiki/refs/workflows/review.md
skills/agentic-engineering-wiki/refs/workflows/recovery.md
skills/agentic-engineering-wiki/refs/policies/delegation.md
skills/agentic-engineering-wiki/refs/policies/validation.md
skills/agentic-engineering-wiki/refs/contracts/testing.md
skills/agentic-engineering-wiki/refs/contracts/async-execution.md
skills/agentic-engineering-wiki/schemas/index.md
```

**Required changes**

- Add concise routing entries for all new skills and artifacts.
- Define the boundary between debugging and runtime recovery.
- Document TDD evidence and completion freshness.
- Document two-stage task review and feedback resolution.
- Document context isolation and parallel read-only exploration.
- Document workspace baseline and delivery finalization.
- Keep one canonical detailed location per rule; other files should link instead of duplicating text.

**Acceptance criteria**

- All links resolve inside `/skills`.
- No contradictory rule exists between Core, Wiki, role skills, schemas, and scripts.
- The Wiki remains a table of contents and selective reference system rather than a monolithic mandatory read.

---

### HSP-802 — Add backward-compatible schema migration rules

**Priority:** P0  
**Dependencies:** HSP-203, HSP-301, HSP-501

**Files to modify or create**

```text
skills/agentic-state-tools/references/artifact-contracts.md
skills/agentic-state-tools/scripts/validate_payload.py
skills/agentic-state-tools/scripts/validate_schema.py
skills/agentic-state-tools/scripts/create_handoff.py
skills/agentic-state-tools/scripts/create_review.py
skills/agentic-state-tools/scripts/create_context.py
skills/agentic-state-tools/examples/**
```

**Migration requirements**

- Every new artifact has `schema_version`.
- Existing artifacts remain parseable where safe.
- Legacy artifacts are explicitly identified and cannot silently satisfy stricter evidence gates.
- New fields are initially optional only when backward compatibility requires it; profile or policy may still make them mandatory for new runs.
- No in-place mutation of immutable historical artifacts.
- New projections must preserve links to superseded versions.

**Acceptance criteria**

- A legacy task can be inspected without crash.
- A new strict-profile task cannot pass using legacy evidence.
- Migration errors are explicit and do not trigger partial writes.

---

### HSP-803 — Add skill-local validation and examples

**Priority:** P0  
**Dependencies:** HSP-801, HSP-802

**Required work**

For every new schema and script:

- add at least one valid example;
- add invalid examples or embedded negative cases for major invariants;
- add deterministic script validation;
- verify atomic write behavior when the script persists state;
- verify identity mismatch rejection;
- verify stale-evidence rejection;
- verify profile-specific behavior;
- verify that no required Harness file is referenced only outside `/skills`.

**Suggested validator additions**

```text
skills/agentic-state-tools/scripts/validate_examples.py
skills/agentic-engineering-wiki/scripts/validate_wiki_links.py
skills/agentic-skill-authoring/scripts/run_behavior_scenarios.py
```

Extend existing validators instead of creating duplicate validators when responsibilities overlap.

**Acceptance criteria**

- Every example has a declared expected result.
- Negative examples fail for the intended reason.
- Wiki links and new skill references resolve.
- Behavior scenarios cover the critical Superpowers-derived disciplines.

---

### HSP-804 — Final integrated workflow simulation

**Priority:** P0  
**Dependencies:** HSP-803

Simulate at least the following flows using only the integrated Harness skills:

#### Scenario A — New feature

```text
Brainstorm
→ approved decision
→ executable plan
→ plan review
→ fresh context
→ TDD implementation
→ fresh completion verification
→ spec review
→ code-quality review
→ batch review
→ delivery finalization
```

#### Scenario B — Bug repair

```text
Systematic debugging
→ confirmed root cause
→ regression test RED
→ minimal fix GREEN
→ broad verification
→ spec review
→ quality review
```

#### Scenario C — Failed repair

```text
Hypothesis 1 rejected
→ Hypothesis 2 rejected
→ Hypothesis 3 rejected
→ task blocked/escalated
→ no fourth blind fix
```

#### Scenario D — Parallel exploration

```text
Multiple independent read-only explorer dispatches
→ reconciled findings
→ one approved implementation task
→ no parallel write enabled
```

#### Scenario E — Stale verification

```text
Tests pass
→ implementation edited
→ previous evidence becomes stale
→ completion claim rejected
→ tests rerun
→ completion accepted
```

#### Scenario F — Incorrect review feedback

```text
Reviewer suggests out-of-scope abstraction
→ implementer verifies contract and usage
→ finding rejected with evidence
→ reviewer re-evaluates and closes or escalates
```

**Acceptance criteria**

- All identity and evidence links remain valid through each flow.
- No role crosses its write or decision boundary.
- The simulation does not rely on any Harness policy or script existing only outside `/skills`.
- Failures produce bounded, actionable status rather than guessed continuation.

---

# 6. Dependency Order

```text
HSP-101
  └─ HSP-102
       └─ HSP-201
            └─ HSP-202
                 └─ HSP-203
                      └─ HSP-301
                           ├─ HSP-302
                           └─ HSP-401
                                ├─ HSP-402
                                │    └─ HSP-403
                                │         └─ HSP-501
                                │              └─ HSP-502
                                │                   └─ HSP-601
                                │                        └─ HSP-602
                                └─ HSP-701
                                     └─ HSP-702

All completed work
  └─ HSP-801
       └─ HSP-802
            └─ HSP-803
                 └─ HSP-804
```

Recommended execution batches:

| Batch | Tasks |
|---|---|
| 1 | HSP-101, HSP-102 |
| 2 | HSP-201, HSP-202, HSP-203 |
| 3 | HSP-301, HSP-302 |
| 4 | HSP-401, HSP-402, HSP-403 |
| 5 | HSP-501, HSP-502 |
| 6 | HSP-601, HSP-602 |
| 7 | HSP-701, HSP-702 |
| 8 | HSP-801, HSP-802, HSP-803, HSP-804 |

Do not start a later batch merely because its files do not overlap. The behavioral contracts in earlier batches define assumptions used by later schemas and workflows.

---

# 7. Cross-Cutting Acceptance Criteria

The entire improvement is complete only when all conditions below are true.

## 7.1 Architecture

- Existing Harness role boundaries remain intact.
- New process skills integrate through Core, Wiki, Configuration, and State Tools.
- Runtime recovery is not confused with code debugging.
- No duplicate canonical policy exists in multiple skills.

## 7.2 Evidence

- Completion claims use current workspace-bound evidence.
- TDD RED and GREEN evidence are distinguishable.
- Stale evidence is rejected.
- Acceptance criteria map to concrete verification.

## 7.3 Review

- Specification review precedes code-quality review.
- Behavioral changes during quality fixes invalidate specification approval when necessary.
- Findings have explicit resolution states.
- Only re-review closes a corrected finding.

## 7.4 Planning and context

- Plans contain precise files, boundaries, dependencies, and verification.
- Vague placeholders are rejected.
- Each attempt receives fresh bounded context.
- Re-dispatch requires a meaningful delta.

## 7.5 Concurrency and Git

- Parallel read-only exploration is independent from async write.
- Async write remains isolated and disabled by default unless enabled by config.
- Worktrees have baseline evidence.
- Final delivery and destructive cleanup require validated decisions and approvals.

## 7.6 Skill quality

- Critical skills have behavioral pressure scenarios.
- Skill descriptions use concrete trigger language.
- Entry-point files remain concise.
- New schemas, scripts, references, and examples are located inside `/skills`.

---

# 8. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Too many new gates slow simple tasks | Medium | Use profile-aware requirements and lightweight exceptions |
| Core and Wiki become too large | High | Keep `SKILL.md` as routing layer and move details to references |
| Schema migration breaks old state | High | Add versions, legacy parsing, and strict-profile rejection rather than destructive migration |
| Review stages double token cost | Medium | Skip or combine Code Quality only where the profile explicitly permits; never combine Spec Compliance with weighted quality scoring |
| TDD evidence becomes bureaucratic | Medium | Capture evidence automatically through state-tools scripts |
| Debugging artifact is used for runtime recovery | Medium | Define explicit ownership and routing boundary |
| Agents over-load process skills | Medium | Deterministic routing instead of the Superpowers 1% rule |
| Behavior tests become provider-specific | Medium | Store provider/model as scenario metadata and keep assertions behavior-based |
| New scripts duplicate existing state-tools logic | High | Extend shared runtime utilities, atomic writers, identity validators, and schema loaders |
| Worktree finalizer performs destructive action | High | Require typed approval and proven Harness ownership |

---

# 9. Explicit Non-Goals

This improvement does not attempt to:

- replace Harness with Superpowers;
- import Superpowers platform-specific tooling unchanged;
- force security review onto every personal or quick-change task;
- enable async write by default;
- implement multi-machine scheduling;
- grant reviewers implementation permissions;
- allow implementers to redesign approved architecture;
- make every small edit require a long design document;
- store the implementation plan itself as a mandatory runtime skill;
- use external root-level documents as the only source of a Harness rule.

---

# 10. Definition of Done for Each Task

A task in this plan may be marked complete only when:

1. all listed files are added or modified within the Harness `/skills` structure;
2. its schema or contract validates positive and negative examples;
3. existing state identity and atomic write rules are preserved;
4. role boundaries are documented;
5. profile behavior is defined when strictness can vary;
6. relevant Wiki routing is updated without duplicating the full policy;
7. focused validation passes;
8. broader affected validation passes;
9. completion evidence is fresh and tied to the final workspace state;
10. the task is independently reviewed for specification compliance and, when required, code quality.

---

# 11. First Implementation Slice

Begin with **Batch 1 only**:

```text
HSP-101 — Create agentic-systematic-debugging
HSP-102 — Add structured debugging artifact and integration
```

This is the best first slice because:

- it fills the largest behavioral gap;
- it does not require changing every existing artifact at once;
- it establishes the evidence pattern reused by TDD and completion verification;
- it creates a clear boundary between repair and recovery;
- it can be behavior-tested before wider rollout.

Do not begin TDD schema migration until the debugging skill and artifact contract are accepted, because bug-fix TDD will reference the debugging investigation and regression evidence.

---

# 12. Expected Final Result

After implementation, Harness should retain its deterministic and recoverable execution architecture while gaining the practical discipline that makes Superpowers effective:

- agents choose the correct process before acting;
- bugs are investigated rather than guessed at;
- tests prove behavior before and after implementation;
- completion claims are backed by fresh evidence;
- specification correctness cannot be hidden by a quality score;
- review feedback is evaluated technically rather than followed blindly;
- context is bounded and attempt-specific;
- parallelism is used only where safe;
- worktree and delivery operations are controlled;
- the skill suite is tested against real agent rationalizations.

The resulting system should be stricter where failure is expensive and lightweight where the active project profile permits speed.
