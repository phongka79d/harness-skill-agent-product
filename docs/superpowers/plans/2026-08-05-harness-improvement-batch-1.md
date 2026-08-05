# Harness Improvement Batch 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]` syntax for tracking.

**Goal:** Add a systematic debugging process and a task-bound debugging artifact that prevent speculative repairs while preserving Harness state, identity, recovery, and approval boundaries.

**Architecture:** Implement HSP-101 as a concise process skill with detailed references under its own skill directory. Implement HSP-102 as a schema-validated artifact owned by `agentic-state-tools`; the CLI writes only to `.agent/work/<task-id>/debug-investigation.json`, binds the investigation to the current task/run/attempt, and emits a normal runtime event. Repair dispatch and implementer handoffs consume the artifact but do not become alternate writers. Existing `BLOCKED` and `ESCALATED` states remain the escalation boundary.

**Tech Stack:** Markdown skill packages, OpenAI UI metadata YAML, Python 3 standard library, the repository's JSON Schema subset validator, atomic state-tool writers, runtime locks, JSONL events, `unittest`, and subprocess-based CLI tests.

---

## Source and scope

This plan is derived from:

```text
docs/superpowers/plans/Harness_Improvement_Implementation_Plan.md
```

It deliberately implements only the source plan's **First Implementation Slice**:

- HSP-101: create `agentic-systematic-debugging`.
- HSP-102: create the structured debugging artifact and integrate it with repair dispatch and handoff validation.

Later batches remain in the source plan and are out of scope for this document. Do not start TDD evidence migration, review-stage changes, routing redesign, context changes, worktree finalization, or behavioral scenario infrastructure from this plan.

### Assumptions and approval gate

- The user-designated source plan is treated as the approved engineering direction for this slice because no project-local brainstorm handoff or `.agent/` runtime state exists.
- Scope authorization: the user explicitly approved adding `skills/agentic-state-tools/schemas/state-machine.json` to HSP-102 because the new non-state event must remain synchronized with the registry and event schema.
- Before implementation, the Primary Agent must resolve the active project profile and review contract. This plan does not invent a profile-specific threshold.
- A plan reviewer must run the deterministic planning validator and independently check the actual task scopes before either task is dispatched.
- The Superpowers source files named by the source plan are not present in this repository. The implementation may use the behavioral requirements transcribed in the source plan, but must stop for a new decision if an exact external source rule conflicts with Harness contracts.

## File map

### HSP-101 files

| Path | Responsibility |
|---|---|
| `skills/agentic-systematic-debugging/SKILL.md` | Trigger, routing, workflow, boundaries, and required evidence summary. |
| `skills/agentic-systematic-debugging/agents/openai.yaml` | Discoverable UI metadata and prompt entry point. |
| `skills/agentic-systematic-debugging/references/debugging-protocol.md` | Detailed evidence-to-fix protocol. |
| `skills/agentic-systematic-debugging/references/root-cause-tracing.md` | Backward data-flow and working-reference procedure. |
| `skills/agentic-systematic-debugging/references/condition-based-waiting.md` | Condition polling, timeout, and observability rules. |
| `skills/agentic-systematic-debugging/references/escalation-and-stop-rules.md` | Three-rejection stop rule and existing Harness status mapping. |
| `skills/agentic-systematic-debugging/examples/debug-investigation.example.json` | Human-readable example of a complete investigation payload. |
| `tests/unit/test_systematic_debugging_skill.py` | Focused trigger, boundary, and reference-link tests. |

### HSP-102 files

| Path | Responsibility |
|---|---|
| `skills/agentic-state-tools/schemas/debug-investigation.schema.json` | Versioned payload shape and field-level constraints. |
| `skills/agentic-state-tools/scripts/create_debug_investigation.py` | Locked, identity-bound, atomic artifact writer. |
| `skills/agentic-state-tools/examples/debug-investigation.json` | Positive state-tools payload example. |
| `skills/agentic-state-tools/schemas/event.schema.json` | Accept `DEBUG_INVESTIGATION_CREATED` as a non-state event. |
| `skills/agentic-state-tools/scripts/state_transition_registry.py` | Register the same event as non-state metadata. |
| `skills/agentic-state-tools/schemas/state-machine.json` | Keep the canonical non-state event list synchronized with the registry. |
| `skills/agentic-state-tools/schemas/dispatch.schema.json` | Carry `investigation_id` on repair dispatches. |
| `skills/agentic-state-tools/schemas/task-state.schema.json` | Persist the repair investigation binding with task state. |
| `skills/agentic-state-tools/schemas/handoff.schema.json` | Carry the investigation binding into implementer handoffs. |
| `skills/agentic-state-tools/scripts/dispatch_transaction.py` | Require and persist a valid investigation for `REPAIR_REQUIRED` tasks. |
| `skills/agentic-state-tools/scripts/create_handoff.py` | Reject a successful repair handoff without confirmed root cause and regression evidence. |
| `skills/agentic-state-tools/scripts/task_state_contract.py` | Keep the investigation binding immutable after repair dispatch. |
| `skills/agentic-state-tools/scripts/validate_examples.py` | Register and exercise the positive investigation example through its owning CLI. |
| `skills/agentic-state-tools/SKILL.md` | Document the writer command and rejection semantics. |
| `skills/agentic-state-tools/references/artifact-contracts.md` | Document the canonical artifact path and ownership. |
| `skills/agentic-engineering-wiki/SKILL.md` | Add routing for debugging versus runtime recovery. |
| `skills/agentic-engineering-wiki/refs/workflows/execution.md` | Document the repair-dispatch precondition. |
| `skills/agentic-engineering-wiki/refs/workflows/recovery.md` | State that product debugging is not runtime recovery. |
| `skills/agentic-implementer/SKILL.md` | Require investigation evidence before repair work and successful claims. |
| `skills/agentic-implementer/references/implementation-loop.md` | Add the investigation checkpoint to the repair loop. |
| `tests/unit/test_debug_investigation.py` | Schema and CLI behavior tests. |
| `tests/integration/test_debug_repair_integration.py` | Dispatch and handoff enforcement tests. |

## Dependency and parallelism

```text
P1-A (read-only runtime pattern scan)  --\
P1-B (read-only recovery boundary scan) ---> HSP-101 ---> HSP-102 ---> Batch 1 review
```

P1-A and P1-B may run in parallel when read-only explorer tooling is available. They may read only the files named in their lane and return findings; they do not edit files, create branches, or write `.agent/` state.

HSP-101 and HSP-102 must run sequentially. HSP-102 consumes the exact vocabulary, stop rule, and evidence boundary defined by HSP-101, and it modifies the implementer/dispatch boundary. Splitting the schema and writer into parallel write tasks would allow the CLI and schema to drift and would create overlapping changes in `agentic-state-tools`. No parallel write lane is authorized in Batch 1.

The repository configuration currently has synchronous execution as the default and async execution disabled. Even if the two tasks have mostly disjoint paths, do not opt into async execution without a later approved isolation decision.

## Optional read-only exploration lanes

These lanes are preparatory only and can run concurrently.

### P1-A: Inspect state-tool writer patterns

Read:

```text
skills/agentic-state-tools/scripts/create_checkpoint.py
skills/agentic-state-tools/scripts/create_context.py
skills/agentic-state-tools/scripts/write_artifact.py
skills/agentic-state-tools/scripts/runtime_utils.py
skills/agentic-state-tools/schemas/checkpoint.schema.json
skills/agentic-state-tools/schemas/context.schema.json
```

Return the exact conventions for runtime locking, `next_revision`, identity binding, `write_validated`, event emission, and error prefixes. Do not modify any file.

### P1-B: Inspect the debugging/recovery boundary

Read:

```text
skills/agentic-runtime-recovery/SKILL.md
skills/agentic-runtime-recovery/references/recovery-model.md
skills/agentic-engineering-wiki/refs/workflows/recovery.md
skills/agentic-engineering-wiki/refs/workflows/execution.md
skills/agentic-implementer/SKILL.md
skills/agentic-implementer/references/implementation-loop.md
```

Return the exact distinction between code/product defects and interrupted runtime side effects. Do not modify any file.

## Task 1: Create the systematic debugging skill

**Files:**

- Create: `skills/agentic-systematic-debugging/SKILL.md`
- Create: `skills/agentic-systematic-debugging/agents/openai.yaml`
- Create: `skills/agentic-systematic-debugging/references/debugging-protocol.md`
- Create: `skills/agentic-systematic-debugging/references/root-cause-tracing.md`
- Create: `skills/agentic-systematic-debugging/references/condition-based-waiting.md`
- Create: `skills/agentic-systematic-debugging/references/escalation-and-stop-rules.md`
- Create: `skills/agentic-systematic-debugging/examples/debug-investigation.example.json`
- Test: `tests/unit/test_systematic_debugging_skill.py`

### Step 1: Write the focused failing skill-contract test

Create `tests/unit/test_systematic_debugging_skill.py` with this complete test surface:

```python
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "agentic-systematic-debugging"


class SystematicDebuggingSkillTests(unittest.TestCase):
    def test_entrypoint_contains_triggers_workflow_and_boundaries(self) -> None:
        body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "flaky",
            "unexplained failure",
            "root cause",
            "one falsifiable hypothesis",
            "condition-based wait",
            "BLOCKED",
            "ESCALATED",
            "agentic-engineering-core",
            "agentic-engineering-wiki",
            "agentic-state-tools",
        ):
            self.assertIn(phrase, body)
        self.assertIn("Do not modify implementation", body)
        self.assertIn("Do not repeat an identical failed hypothesis", body)

    def test_references_and_example_exist_and_are_local(self) -> None:
        for relative in (
            "references/debugging-protocol.md",
            "references/root-cause-tracing.md",
            "references/condition-based-waiting.md",
            "references/escalation-and-stop-rules.md",
            "examples/debug-investigation.example.json",
        ):
            self.assertTrue((SKILL / relative).is_file(), relative)
        example = json.loads((SKILL / "examples/debug-investigation.example.json").read_text(encoding="utf-8"))
        self.assertEqual(example["schema_version"], 1)
        self.assertEqual(example["status"], "COMPLETED")
        self.assertEqual(example["hypotheses"][0]["outcome"], "CONFIRMED")

    def test_ui_metadata_points_to_the_new_skill(self) -> None:
        metadata = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$agentic-systematic-debugging", metadata)


if __name__ == "__main__":
    unittest.main()
```

### Step 2: Run the focused test and verify the expected failure

Run:

```text
python -m unittest discover -s tests/unit -p "test_systematic_debugging_skill.py" -v
```

Expected result before the skill exists: the test run fails because `skills/agentic-systematic-debugging/` is missing.

### Step 3: Create the concise skill entry point and UI metadata

Create `skills/agentic-systematic-debugging/SKILL.md` with these exact front-matter values and entry-point rules:

```markdown
---
name: agentic-systematic-debugging
description: Use when a task has a flaky, inconsistent, unexplained, failing, timing-related, racing, or incorrect behavior that requires root-cause investigation before repair.
---

# Agentic Systematic Debugging

Read the shared `agentic-engineering-wiki` package before this workflow.
Read `agentic-configuration/SKILL.md` for routing and `agentic-engineering-core` for role and handoff boundaries.

Use this process for product or code defects. Use `agentic-runtime-recovery` for interrupted runs, uncertain side effects, stale leases, corrupt runtime state, or resume decisions.

## Workflow

1. Reproduce the symptom, or record why reproduction is impossible.
2. Capture the trigger, output, environment facts, and relevant recent changes.
3. Trace the failing value or state backward through the data flow.
4. Compare the failure with a working repository pattern when one exists.
5. State one falsifiable hypothesis and its predicted observation.
6. Run the smallest experiment that can confirm or reject that hypothesis.
7. Record the experiment result before proposing a repair.
8. Add a regression test or reproducible check.
9. Apply the smallest root-cause repair.
10. Run focused and broader verification.

## Boundaries

- Do not modify implementation before investigation evidence exists, except recorded diagnostic instrumentation.
- Do not combine speculative fixes in one attempt.
- Do not call a symptom the root cause without a data-flow trace.
- Do not use arbitrary sleep when a condition-based wait is available.
- Do not repeat an identical rejected hypothesis.
- After three rejected hypotheses or materially similar failed fixes, use the existing `BLOCKED` or `ESCALATED` state and stop ordinary repair.

Read the detailed protocol only when the debugging trigger is active:

- [debugging-protocol.md](references/debugging-protocol.md)
- [root-cause-tracing.md](references/root-cause-tracing.md)
- [condition-based-waiting.md](references/condition-based-waiting.md)
- [escalation-and-stop-rules.md](references/escalation-and-stop-rules.md)
```

Create `skills/agentic-systematic-debugging/agents/openai.yaml`:

```yaml
interface:
  display_name: "Agentic Systematic Debugging"
  short_description: "Trace defects before repair"
  default_prompt: "Use $agentic-systematic-debugging to investigate a failure before proposing a fix."
```

### Step 4: Add the detailed references and positive example

Write the four references with these concrete contracts:

`references/debugging-protocol.md` must define the investigation record in this order:

```text
symptom -> reproduction -> environment/recent changes -> data-flow trace
-> working reference -> one hypothesis -> smallest experiment -> result
-> regression check -> minimal fix -> focused verification -> broad verification
```

Each stage must state its required evidence and its stop condition. It must state that a repair handoff cannot claim `FIXED` or `PASS` without a confirmed root cause and verification evidence.

`references/root-cause-tracing.md` must require the implementer to name the failing value/state, its producer, each transformation, the first incorrect transition, and the owning boundary. It must distinguish observed facts from inference and require a repository working reference before inventing a new pattern when one exists.

`references/condition-based-waiting.md` must require a named condition, polling interval, maximum deadline, observed state per poll, and timeout result. It must explicitly reject a bare `sleep` as evidence that a condition became true.

`references/escalation-and-stop-rules.md` must map three rejected hypotheses or materially similar failed fixes to `BLOCKED` or `ESCALATED`, require a new context/decision before another attempt, and state that runtime recovery owns uncertain side effects while this skill owns product/code defects.

Create `examples/debug-investigation.example.json` as a complete status-bearing example. Use this shape and values:

```json
{
  "schema_version": 1,
  "investigation_id": "DBG-T-EXAMPLE-1",
  "task_id": "T-EXAMPLE",
  "run_id": "RUN-T-EXAMPLE",
  "attempt_id": "ATTEMPT-T-EXAMPLE",
  "task_revision": 3,
  "symptom": "The parser returns an empty result for a valid input.",
  "reproduction_status": "REPRODUCED",
  "reproduction_steps": ["Run the parser with the fixture input."],
  "observed_output": "[]",
  "expected_output": "[item]",
  "environment_facts": {"python": "repository-configured"},
  "recent_changes": ["Parser normalization changed in the previous attempt."],
  "data_flow_trace": ["fixture -> parser input", "input -> normalization", "normalization -> empty result"],
  "working_reference": "tests/unit/test_parser.py::test_valid_input",
  "hypotheses": [
    {
      "hypothesis_id": "H-1",
      "statement": "Normalization drops the field before parsing.",
      "predicted_observation": "The field is absent immediately after normalization.",
      "experiment": "Log the normalized object for the fixture input.",
      "result": "The field is absent.",
      "outcome": "CONFIRMED"
    }
  ],
  "current_hypothesis": "H-1",
  "experiment": {
    "command": "python -m unittest tests/unit/test_parser.py -v",
    "expected_observation": "The focused regression test fails before the fix."
  },
  "experiment_result": {
    "observed": "The normalized field is absent.",
    "outcome": "CONFIRMED",
    "recorded_at": "2026-08-05T00:00:00Z"
  },
  "root_cause": "The normalization branch removes the valid field when its value is an empty-looking string.",
  "regression_check": {
    "command": "python -m unittest tests/unit/test_parser.py -v",
    "exit_code": 0,
    "workspace_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "status": "PASS"
  },
  "fix_attempt_count": 1,
  "status": "COMPLETED",
  "created_at": "2026-08-05T00:00:00Z",
  "updated_at": "2026-08-05T00:00:00Z",
  "revision": 1
}
```

### Step 5: Run skill-level validation

Run:

```text
python -m unittest discover -s tests/unit -p "test_systematic_debugging_skill.py" -v
python -m unittest discover -s tests/unit -p "test_skill_metadata.py" -v
python -m unittest discover -s tests/unit -p "test_wiki_routing.py" -v
python skills/agentic-engineering-wiki/scripts/validate_wiki_links.py --root skills/agentic-engineering-wiki
```

Expected result: all focused tests pass, `WIKI_VALID` is printed, and the generic metadata test discovers the new skill without exceptions.

### Step 6: Review the HSP-101 diff and checkpoint

Inspect only the approved paths:

```text
git status --short
git diff -- skills/agentic-systematic-debugging tests/unit/test_systematic_debugging_skill.py
```

Confirm that no state-tools, source-code, runtime, or unrelated documentation file changed. Record the HSP-101 checkpoint and stop if the new skill references an external file or creates a runtime-recovery rule. Commit only after the Primary Agent approves the diff:

```text
git add skills/agentic-systematic-debugging tests/unit/test_systematic_debugging_skill.py
git commit -m "feat: add systematic debugging skill"
```

## Task 2: Add the structured debugging artifact and enforcement

**Files:**

- Create: `skills/agentic-state-tools/schemas/debug-investigation.schema.json`
- Create: `skills/agentic-state-tools/scripts/create_debug_investigation.py`
- Create: `skills/agentic-state-tools/examples/debug-investigation.json`
- Modify: `skills/agentic-state-tools/schemas/event.schema.json`
- Modify: `skills/agentic-state-tools/scripts/state_transition_registry.py`
- Modify: `skills/agentic-state-tools/schemas/state-machine.json`
- Modify: `skills/agentic-state-tools/schemas/dispatch.schema.json`
- Modify: `skills/agentic-state-tools/schemas/task-state.schema.json`
- Modify: `skills/agentic-state-tools/schemas/handoff.schema.json`
- Modify: `skills/agentic-state-tools/scripts/task_state_contract.py`
- Modify: `skills/agentic-state-tools/scripts/dispatch_transaction.py`
- Modify: `skills/agentic-state-tools/scripts/create_handoff.py`
- Modify: `skills/agentic-state-tools/SKILL.md`
- Modify: `skills/agentic-state-tools/references/artifact-contracts.md`
- Modify: `skills/agentic-engineering-wiki/SKILL.md`
- Modify: `skills/agentic-engineering-wiki/refs/workflows/execution.md`
- Modify: `skills/agentic-engineering-wiki/refs/workflows/recovery.md`
- Modify: `skills/agentic-implementer/SKILL.md`
- Modify: `skills/agentic-implementer/references/implementation-loop.md`
- Test: `tests/unit/test_debug_investigation.py`
- Test: `tests/integration/test_debug_repair_integration.py`

### Step 1: Write failing schema and CLI tests

Create `tests/unit/test_debug_investigation.py`. The fixture must initialize a temporary runtime, create a task state through `write_validated`, and bind it to this identity:

```python
{
    "task_id": "T-DBG-1",
    "batch_id": "B-DBG-1",
    "plan_revision": 1,
    "revision": 3,
    "status": "REPAIR_REQUIRED",
    "run_id": "RUN-DBG-1",
    "attempt_id": "ATTEMPT-DBG-1",
    "dispatch_id": "DISPATCH-DBG-1"
}
```

Because this slice creates the investigation before the repair dispatch advances the task state, the valid investigation payload uses `task_revision: 4` (`current task revision 3 + 1`). After dispatch, revision `4` is the revision checked by the successful handoff.

The test module must invoke the CLI with `subprocess.run(..., capture_output=True, check=False, timeout=15)` and assert the exact outcomes below:

1. A valid payload writes `.agent/work/T-DBG-1/debug-investigation.json`, assigns revision `1`, and appends `DEBUG_INVESTIGATION_CREATED` to `.agent/runtime/events.jsonl`.
2. A payload with a duplicate `hypothesis_id` exits non-zero, prints `DEBUG_INVESTIGATION_REJECTED`, and leaves the existing artifact bytes unchanged.
3. A payload with a different `run_id`, `attempt_id`, or `task_revision` exits non-zero and leaves no new artifact when no prior artifact exists.
4. `COMPLETED` without a non-empty `root_cause` and a passing `regression_check` is rejected.
5. `fix_attempt_count` greater than `3` is rejected; a fourth speculative attempt is never persisted.
6. A payload with an unknown `schema_version` is rejected before any write.
7. A second valid revision preserves `investigation_id`, `task_id`, `run_id`, and `attempt_id`, increments `revision`, and sets `updated_at`.

Use the exact payload contract from Step 3 below rather than constructing an underspecified test object.

### Step 2: Run the tests to verify the expected failure

Run:

```text
python -m unittest discover -s tests/unit -p "test_debug_investigation.py" -v
```

Expected result before implementation: collection or subprocess failures because the schema and `create_debug_investigation.py` do not exist.

### Step 3: Create the versioned investigation schema

Create `skills/agentic-state-tools/schemas/debug-investigation.schema.json` with `additionalProperties: false` and the following contract:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "investigation_id", "task_id", "run_id", "attempt_id",
    "task_revision", "symptom", "reproduction_status", "reproduction_steps",
    "observed_output", "expected_output", "environment_facts", "recent_changes",
    "data_flow_trace", "working_reference", "hypotheses", "current_hypothesis",
    "experiment", "experiment_result", "root_cause", "regression_check",
    "fix_attempt_count", "status", "created_at", "updated_at", "revision"
  ],
  "properties": {
    "schema_version": {"type": "integer", "minimum": 1, "maximum": 1},
    "investigation_id": {"type": "string", "minLength": 1, "pattern": "^DBG-[A-Za-z0-9._-]+$"},
    "task_id": {"type": "string", "minLength": 1, "pattern": "^[A-Za-z0-9._-]+$"},
    "run_id": {"type": "string", "minLength": 1},
    "attempt_id": {"type": "string", "minLength": 1},
    "task_revision": {"type": "integer", "minimum": 1},
    "symptom": {"type": "string", "minLength": 1},
    "reproduction_status": {"type": "string", "enum": ["REPRODUCED", "NOT_REPRODUCED", "IMPOSSIBLE"]},
    "reproduction_steps": {"type": "array", "items": {"type": "string"}},
    "observed_output": {"type": "string"},
    "expected_output": {"type": "string"},
    "environment_facts": {"type": "object"},
    "recent_changes": {"type": "array", "items": {"type": "string"}},
    "data_flow_trace": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
    "working_reference": {"type": ["string", "null"]},
    "hypotheses": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["hypothesis_id", "statement", "predicted_observation", "experiment", "result", "outcome"],
        "properties": {
          "hypothesis_id": {"type": "string", "minLength": 1},
          "statement": {"type": "string", "minLength": 1},
          "predicted_observation": {"type": "string", "minLength": 1},
          "experiment": {"type": "string", "minLength": 1},
          "result": {"type": "string"},
          "outcome": {"type": "string", "enum": ["CONFIRMED", "REJECTED", "INCONCLUSIVE"]}
        }
      }
    },
    "current_hypothesis": {"type": ["string", "null"]},
    "experiment": {
      "type": "object",
      "additionalProperties": false,
      "required": ["command", "expected_observation"],
      "properties": {
        "command": {"type": "string", "minLength": 1},
        "expected_observation": {"type": "string", "minLength": 1}
      }
    },
    "experiment_result": {
      "type": "object",
      "additionalProperties": false,
      "required": ["observed", "outcome", "recorded_at"],
      "properties": {
        "observed": {"type": "string"},
        "outcome": {"type": "string", "enum": ["CONFIRMED", "REJECTED", "INCONCLUSIVE"]},
        "recorded_at": {"type": "string", "minLength": 1}
      }
    },
    "root_cause": {"type": ["string", "null"]},
    "regression_check": {
      "type": "object",
      "additionalProperties": false,
      "required": ["command", "exit_code", "workspace_hash", "status"],
      "properties": {
        "command": {"type": "string", "minLength": 1},
        "exit_code": {"type": "integer"},
        "workspace_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "status": {"type": "string", "enum": ["PASS", "FAIL", "NOT_RUN"]}
      }
    },
    "fix_attempt_count": {"type": "integer", "minimum": 0, "maximum": 3},
    "status": {"type": "string", "enum": ["INVESTIGATING", "ROOT_CAUSE_CONFIRMED", "VERIFICATION_PENDING", "COMPLETED", "BLOCKED", "ESCALATED"]},
    "created_at": {"type": "string", "minLength": 1},
    "updated_at": {"type": "string", "minLength": 1},
    "revision": {"type": "integer", "minimum": 1},
    "previous_revision": {"type": ["integer", "null"], "minimum": 0}
  }
}
```

The schema is intentionally versioned at `1` and rejects unknown fields. Future changes must add a new schema version or a new migration projection; they must not mutate historical artifacts in place.

### Step 4: Implement the locked atomic writer

Create `skills/agentic-state-tools/scripts/create_debug_investigation.py` using the existing imports and conventions from `create_checkpoint.py` and `create_context.py`.

The implementation must expose this CLI:

```text
python skills/agentic-state-tools/scripts/create_debug_investigation.py --project-root <project> --task-id <task-id> --input <payload.json> --actor <actor>
```

Implement these exact phases in `main()`:

1. Parse `--project-root`, `--task-id`, `--input`, and `--actor`.
2. Read the payload with `read_payload`, validate the task identifier, inject `task_id`, default `schema_version` to `1`, and reject a supplied task ID that differs from the CLI task ID.
3. Enter `runtime_lock` and require `.agent/runtime/state.json` and `.agent/runtime/events.jsonl` through the normal runtime initializer.
4. Load `.agent/work/<task-id>/task-state.json`. Reject the operation as `DEBUG_INVESTIGATION_BLOCKED` if task state is absent because the investigation cannot be bound to a task attempt.
5. Require task state to contain non-empty `run_id` and `attempt_id`. Copy those fields when the payload omits them. For a `REPAIR_REQUIRED` task at revision `N`, set `task_revision` to the planned dispatch revision `N + 1`; reject any supplied value other than `N + 1`.
6. Load the existing investigation artifact if present. Preserve its `investigation_id`, reject an ID change, require the next revision to be exactly the current revision plus one, and preserve `created_at`.
7. Validate the domain invariants before writing:
   - every `hypothesis_id` is unique;
   - `current_hypothesis` is null or names an existing hypothesis;
   - `ROOT_CAUSE_CONFIRMED` and `COMPLETED` require a non-empty root cause and at least one `CONFIRMED` hypothesis;
   - `COMPLETED` requires `regression_check.status == "PASS"` and `exit_code == 0`;
   - `BLOCKED` or `ESCALATED` cannot carry a successful regression check while the root cause is absent;
   - `fix_attempt_count` never exceeds three;
   - timestamps parse using `parse_timestamp` and `updated_at` is not earlier than `created_at`.
8. Set `revision`, `previous_revision`, `created_at`, and `updated_at` with `next_revision` and `utc_now`.
9. Call `write_validated` with `schemas/debug-investigation.schema.json`. No event or artifact write may occur before every validation in steps 2-7 succeeds.
10. Append `DEBUG_INVESTIGATION_CREATED` through `append_event_for_root` with `investigation_id`, `task_id`, and `revision`, then render the checklist.
11. Return `0` and print `DEBUG_INVESTIGATION_WRITTEN: <path>` on success; return `2` with `DEBUG_INVESTIGATION_BLOCKED: ...` for missing runtime/task binding; return `1` with `DEBUG_INVESTIGATION_REJECTED: ...` for malformed, stale, mismatched, or contradictory payloads.

Do not create a fourth repair-attempt state, do not add a new global state-machine status, and do not write directly to `.agent/` outside `write_validated` and the existing event/checklist helpers.

### Step 5: Register the event and artifact ownership

Make these small, non-overlapping contract changes:

- Add `DEBUG_INVESTIGATION_CREATED` to the event type enum in `skills/agentic-state-tools/schemas/event.schema.json`.
- Add the same value to `NON_STATE_EVENTS` in `skills/agentic-state-tools/scripts/state_transition_registry.py`; it must not create a task-state transition.
- Add the same value to the `non_state_events` array in `skills/agentic-state-tools/schemas/state-machine.json`, without changing statuses, transitions, guards, or terminal-state definitions. Run `validate_state_machine.py` after this synchronization.
- Add `.agent/work/<id>/debug-investigation.json` to the canonical artifact table in `skills/agentic-state-tools/references/artifact-contracts.md`.
- Document the CLI, exit semantics, versioning, identity binding, and no-partial-write rule in `skills/agentic-state-tools/SKILL.md`.
- Add `investigation_id` as a string field to `dispatch.schema.json`, `task-state.schema.json`, and `handoff.schema.json`.
- Add `investigation_id` to the immutable task binding set in `task_state_contract.py`; the dispatch transaction may establish it once, but later task updates may not replace it.

Create `skills/agentic-state-tools/examples/debug-investigation.json` by copying the positive example from HSP-101 into the state-tools example location and retaining the exact schema-valid values. Do not add a second, divergent example shape.

### Step 6: Enforce the repair-dispatch precondition

Modify `skills/agentic-state-tools/scripts/dispatch_transaction.py` immediately after it loads the current task and before it creates the next queue/lease/task records.

Add a helper with this behavior:

```python
def require_repair_investigation(root: Path, task: dict[str, object], dispatch: dict[str, object]) -> dict[str, object] | None:
    if str(task.get("status", "")).upper() != "REPAIR_REQUIRED":
        return None
    investigation_id = dispatch.get("investigation_id")
    if not isinstance(investigation_id, str) or not investigation_id.strip():
        raise ValueError("repair dispatch requires investigation_id")
    path = root / "work" / str(task["task_id"]) / "debug-investigation.json"
    investigation = read_object(path)
    if investigation.get("investigation_id") != investigation_id:
        raise ValueError("repair dispatch investigation_id does not match canonical artifact")
    for field in ("task_id", "run_id", "attempt_id"):
        if investigation.get(field) != task.get(field):
            raise ValueError(f"repair investigation {field} does not match task state")
    expected_dispatch_revision = int(task.get("revision", 0)) + 1
    if investigation.get("task_revision") != expected_dispatch_revision:
        raise ValueError("repair investigation task_revision does not match the next dispatch revision")
    if investigation.get("status") not in {"ROOT_CAUSE_CONFIRMED", "COMPLETED"}:
        raise ValueError("repair dispatch requires a confirmed root cause")
    return investigation
```

Persist the validated `investigation_id` into the dispatch envelope, queue task record, lease, and next task state. The repair binding must remain identical in the generated records. Preserve existing behavior for non-repair tasks.

### Step 7: Enforce successful repair handoffs

Modify `skills/agentic-state-tools/scripts/create_handoff.py` so a handoff with `status == "COMPLETE"` for a task whose current or dispatch record carries `investigation_id` must:

1. contain the same top-level `investigation_id`;
2. load the canonical investigation artifact from the task directory;
3. match `task_id`, `run_id`, `attempt_id`, and `task_revision`;
4. require investigation status `ROOT_CAUSE_CONFIRMED` or `COMPLETED`;
5. require a non-empty `root_cause` and `regression_check.status == "PASS"` with exit code `0`.

Return `HANDOFF_REJECTED` before writing when any condition fails. A blocked or escalated handoff may preserve the investigation ID and failed evidence, but it must not be normalized to `COMPLETE`.

### Step 8: Update the Wiki and implementer routing

Update only the routing and boundary statements:

- `skills/agentic-engineering-wiki/SKILL.md`: route debugging symptoms to `agentic-systematic-debugging`; route interrupted runtime state and uncertain side effects to `agentic-runtime-recovery`.
- `skills/agentic-engineering-wiki/refs/workflows/execution.md`: state that `REPAIR_REQUIRED` dispatches require a valid, confirmed investigation artifact.
- `skills/agentic-engineering-wiki/refs/workflows/recovery.md`: state that debugging does not decide whether an interrupted side effect is safe to resume.
- `skills/agentic-implementer/SKILL.md`: add the investigation artifact to repair preconditions and prohibit `FIXED`/`PASS` without linked root-cause and regression evidence.
- `skills/agentic-implementer/references/implementation-loop.md`: use this repair loop:

```text
read repair contract
-> read confirmed investigation
-> checkpoint intent through state tools
-> make the smallest root-cause change
-> run the regression check
-> run broader verification
-> prepare investigation-bound handoff
-> validate and persist handoff
```

Do not add the debugging procedure to the Wiki as a second canonical copy; keep details in the new skill references.

### Step 9: Add integration tests for dispatch and handoff enforcement

Create `tests/integration/test_debug_repair_integration.py` with temporary-runtime tests that use the existing `run_script` pattern:

- `REPAIR_REQUIRED` without `investigation_id` returns non-zero and leaves task state, queue, and lease unchanged.
- A dispatch with a missing investigation file, mismatched task identity, or `INVESTIGATING` status is rejected.
- A dispatch with a confirmed investigation persists the same investigation ID to the dispatch envelope and task state.
- A `COMPLETE` handoff without the investigation ID or with a failed regression check returns `HANDOFF_REJECTED` and creates no handoff artifact.
- A `COMPLETE` handoff with matching identity, confirmed root cause, and fresh passing regression evidence is accepted.

Use a test fixture helper that writes the investigation only through `create_debug_investigation.py`; do not write `debug-investigation.json` directly in the fixture.

### Step 10: Run focused validation and inspect the full diff

Run in this order:

```text
python -m unittest discover -s tests/unit -p "test_debug_investigation.py" -v
python -m unittest discover -s tests/integration -p "test_debug_repair_integration.py" -v
python -m unittest discover -s tests/unit -p "test_skill_metadata.py" -v
python -m unittest discover -s tests/unit -p "test_wiki_routing.py" -v
python skills/agentic-state-tools/scripts/validate_state_machine.py --input skills/agentic-state-tools/schemas/state-machine.json
python skills/agentic-state-tools/scripts/validate_examples.py --examples-root skills/agentic-state-tools/examples --deployment skills/agentic-configuration/config/deployment.test.json
python skills/agentic-engineering-wiki/scripts/validate_wiki_links.py --root skills/agentic-engineering-wiki
python -m compileall -q skills tests run_tests.py
```

Expected result: focused unit and integration tests pass, generic metadata and Wiki tests pass, the state machine prints `STATE_MACHINE_VALID`, the Wiki validator prints `WIKI_VALID`, and `compileall` exits `0`.

Then inspect:

```text
git status --short
git diff --stat
git diff --name-only
git diff -- skills/agentic-state-tools/schemas/debug-investigation.schema.json skills/agentic-state-tools/scripts/create_debug_investigation.py skills/agentic-state-tools/scripts/validate_examples.py skills/agentic-state-tools/examples/debug-investigation.json skills/agentic-state-tools/schemas/event.schema.json skills/agentic-state-tools/scripts/state_transition_registry.py skills/agentic-state-tools/schemas/state-machine.json skills/agentic-state-tools/schemas/dispatch.schema.json skills/agentic-state-tools/schemas/task-state.schema.json skills/agentic-state-tools/schemas/handoff.schema.json skills/agentic-state-tools/scripts/task_state_contract.py skills/agentic-state-tools/scripts/dispatch_transaction.py skills/agentic-state-tools/scripts/create_handoff.py skills/agentic-state-tools/SKILL.md skills/agentic-state-tools/references/artifact-contracts.md skills/agentic-engineering-wiki/SKILL.md skills/agentic-engineering-wiki/refs/workflows/execution.md skills/agentic-engineering-wiki/refs/workflows/recovery.md skills/agentic-implementer/SKILL.md skills/agentic-implementer/references/implementation-loop.md tests/unit/test_debug_investigation.py tests/integration/test_debug_repair_integration.py
```

Reject the task if any file outside the approved HSP-102 list changed, if a failed validation is hidden by a prose claim, or if the writer can leave a partially updated artifact after schema/domain rejection.

### Step 11: Run the affected broader suite and commit

Run:

```text
python run_tests.py --all
```

Record the exit code and every failed, skipped, or timed-out group. A full-suite failure is not a PASS for HSP-102; repair the approved scope or escalate with the exact failure evidence.

After the Primary Agent reviews the actual diff and test logs, commit only the HSP-102 paths:

```text
git add skills/agentic-state-tools/schemas/debug-investigation.schema.json skills/agentic-state-tools/scripts/create_debug_investigation.py skills/agentic-state-tools/scripts/validate_examples.py skills/agentic-state-tools/examples/debug-investigation.json skills/agentic-state-tools/schemas/event.schema.json skills/agentic-state-tools/scripts/state_transition_registry.py skills/agentic-state-tools/schemas/state-machine.json skills/agentic-state-tools/schemas/dispatch.schema.json skills/agentic-state-tools/schemas/task-state.schema.json skills/agentic-state-tools/schemas/handoff.schema.json skills/agentic-state-tools/scripts/task_state_contract.py skills/agentic-state-tools/scripts/dispatch_transaction.py skills/agentic-state-tools/scripts/create_handoff.py skills/agentic-state-tools/SKILL.md skills/agentic-state-tools/references/artifact-contracts.md skills/agentic-engineering-wiki/SKILL.md skills/agentic-engineering-wiki/refs/workflows/execution.md skills/agentic-engineering-wiki/refs/workflows/recovery.md skills/agentic-implementer/SKILL.md skills/agentic-implementer/references/implementation-loop.md tests/unit/test_debug_investigation.py tests/integration/test_debug_repair_integration.py
git commit -m "feat: bind repair work to debugging investigations"
```

## Batch 1 review and completion gate

The Primary Agent must review both actual diffs and generated evidence. The Batch 1 review must report the required handoff fields:

```text
Status
Summary
Files Read
Files Changed
Findings
Implementation details
Validation results
Risks
Next Steps
```

Accept the batch only when all of the following are true:

- HSP-101 is discoverable by concrete failure symptoms and clearly separated from runtime recovery.
- HSP-102 rejects malformed, stale, identity-mismatched, duplicate-hypothesis, contradictory, and fourth-attempt payloads without partial writes.
- Repair dispatch carries a valid investigation ID and only proceeds after a confirmed root cause.
- Successful repair handoffs carry fresh passing regression evidence bound to the same task/run/attempt/revision.
- No new global state-machine status or uncontrolled `.agent/` writer was introduced.
- All listed focused and broader validation commands have recorded results.
- The actual diff contains no unauthorized files or unrelated cleanup.

Do not begin Batch 2 until this gate is accepted and the HSP-102 artifact contract is stable.

## Self-review checklist

Before implementation handoff, scan this document for:

- every source-plan HSP-101 and HSP-102 requirement mapped to a task step;
- exact paths for every created or modified file;
- no unfinished marker or implementation placeholder;
- consistent names for `debug-investigation.json`, `investigation_id`, `DEBUG_INVESTIGATION_CREATED`, `ROOT_CAUSE_CONFIRMED`, and `REPAIR_REQUIRED`;
- focused tests before implementation and expected failures before the implementation steps;
- explicit validation of task/run/attempt/revision identity and current workspace evidence;
- no parallel write task that overlaps HSP-101 or HSP-102.
