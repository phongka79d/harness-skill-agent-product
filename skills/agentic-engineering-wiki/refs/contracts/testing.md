# Testing Contract

Policy status: VALIDATED_ONLY

This is the canonical contract for behavior-change and bug-fix verification
evidence. The [validation policy](../policies/validation.md) routes profile
strictness, and the [verification skill](../../../agentic-verification-before-completion/SKILL.md)
consumes current evidence before a positive completion claim.

## Evidence-backed verification

For every behavior-change or bug-fix verification case, store one structured
evidence record for each executed phase. The record must contain:

| Field | Requirement |
| --- | --- |
| `evidence_id`, `verification_case_id` | Stable IDs for the record and planned case |
| `phase` | `RED`, `GREEN`, or `BROAD` |
| `command`, `exit_code` | Exact command invoked and actual exit code; `exit_code` is null only when it did not run |
| `recorded_at` | UTC timestamp in an unambiguous machine-readable format |
| `workspace_hash` | Hash of the workspace used for that invocation |
| `task_id`, `plan_revision`, `run_id`, `attempt_id`, `task_revision` | Runtime identity binding; values must match the current task state |
| `acceptance_criterion_ids` | Criteria directly covered by the result |
| `failure_signature` | Required for RED; identifies the intended missing-behavior failure |
| `output_digest` or `evidence_location` | Inspectable output, not a summary-only claim |
| `status` | `PASS`, `FAIL`, `SKIPPED`, `NOT_APPLICABLE`, or `BLOCKED` |

The TDD sequence is:

1. `RED`: run the smallest exact test command and record the expected non-zero result and failure signature for the missing behavior. Syntax, environment, collection, timeout, and unrelated failures do not satisfy RED.
2. `GREEN`: implement the minimum change, run the exact focused command, and record `PASS` with exit code `0`.
3. `BROAD`: run the suite required by the resolved profile and record its actual result; a focused test is not evidence of broad verification.

The evidence set used by a completion claim must share `task_id`,
`plan_revision`, `run_id`, and `attempt_id`. RED normally has the pre-change
baseline hash; GREEN and BROAD have the hashes of the workspaces on which they
ran. The final GREEN/BROAD evidence and claim must match the current final
workspace and task revision. A material edit is any implementation, test,
configuration, dependency-lock, generated-output, or build-input change that
can affect the case. It makes affected prior evidence `STALE` for claims about
the edited workspace; retain it for history but do not reuse it. Re-run the
affected phases from the current workspace.

## Profile strictness and exceptions

| Profile | Required behavior-change verification |
| --- | --- |
| `production`, `high_risk` | RED -> GREEN -> broad; all phases mandatory |
| `internal_tool`, `course_project` | RED -> GREEN when a viable harness exists; broad suite is risk-based |
| `prototype`, `quick_change`, `personal` | Focused characterization/reproducible verification may replace strict TDD only through an exception |

The resolved profile ID, version, and hash are part of the planning/review
context and must remain pinned for the verification case. A changed profile
version or hash requires policy re-resolution; old evidence cannot silently
inherit the new policy. An Implementer cannot lower the resolved policy. An
exception is structured, scoped, and machine-readable; at minimum it has this
shape:

```json
{
  "exception_id": "EX-001",
  "type": "NO_VIABLE_HARNESS",
  "applies_to": ["RED", "GREEN"],
  "reason": "No executable harness exists for this data-only change.",
  "authority": {"kind": "profile_rule", "id": "quick_change"},
  "alternative_verification": {
    "command": "python tools/check_config.py",
    "exit_code": 0,
    "recorded_at": "2026-08-05T00:00:00Z",
    "workspace_hash": "sha256:...",
    "task_id": "TASK-001",
    "plan_revision": 1,
    "run_id": "RUN-001",
    "attempt_id": "ATT-001",
    "task_revision": 2,
    "acceptance_criterion_ids": ["AC-001"]
  },
  "follow_up": "Add an executable harness before the next behavior change."
}
```

The exception must include `expires_at` or `follow_up`; `authority` must name
the applicable profile rule or approving authority. A prose waiver, missing
alternative result, or expired exception cannot satisfy a required phase.

## Anti-patterns and result reporting

Reject or report as invalid:

- writing the implementation before observing the intended RED result;
- a test that only verifies a mock, a test-only production hook, or assertions tied to implementation details rather than behavior;
- claiming GREEN because a test never failed for the intended reason;
- calling a focused test “full coverage” or “broad verification”;
- reusing GREEN evidence after a material edit, prior run, or changed workspace;
- hiding failed, timed-out, collected, or skipped tests behind “tests passed” or a summary.

For every command, report the exact command, actual exit code, status,
timestamp, workspace and identity binding, covered criteria, and output
location/digest. `SKIPPED` or `NOT_APPLICABLE` requires a reason and follow-up
(and an approved exception when it replaces a required phase); a handoff with
no record reports `NOT_RUN`. Stale evidence is rejected as `STALE` and never
silently converted to `PASS`. Preserve failed output and classify blockers
honestly.

The release runner is `python run_tests.py --all`. Its deterministic groups
are unit, integration, schema, cli, e2e, concurrency, recovery, and release;
the release alias `end_to_end` maps to `e2e`. Each group reports passed,
failed, skipped, collection errors, elapsed seconds, and timeout state.

Release preflight runs these exact commands, in this order:

```text
python run_tests.py --all
python -m compileall -q skills tests run_tests.py
python skills/agentic-engineering-wiki/scripts/validate_wiki_links.py --root skills/agentic-engineering-wiki
python skills/agentic-state-tools/scripts/validate_state_machine.py --input skills/agentic-state-tools/schemas/state-machine.json
python skills/agentic-state-tools/scripts/validate_examples.py --examples-root skills/agentic-state-tools/examples --deployment skills/agentic-configuration/config/deployment.test.json
python skills/agentic-state-tools/scripts/package_skill.py --root . --output <release.zip>
```

The example gate requires positive examples to
pass their runtime validator and declared negative outcomes to be rejected for
their intended reason. A failed gate is named and does not stop the remaining
preflight checks.

Tests are evidence for runtime policy. A schema alone does not prove command
behavior, identity binding, recovery, authorization, or package inspection.
Unimplemented distributed and remote behavior remains outside the release
test surface.
