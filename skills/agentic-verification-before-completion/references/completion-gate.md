# Completion Gate

## Purpose

This gate evaluates proof, not confidence. It runs immediately before an agent,
review, handoff, or delivery process emits a positive claim such as:

- `complete`, `fixed`, `passed`, `ready`, `resolved`, or `successful`;
- `safe to merge` or `safe to release`;
- an equivalent phrase such as “done”, “green”, “verified”, or “no further
  action is needed”.

The wording of the claim does not weaken the gate. A status field, handoff
summary, checklist tick, or model statement is an assertion until it points to
fresh evidence that can be inspected.

## Required input

The evaluator must have the active task state and profile policy, plus a claim
with these identity fields:

```text
claim_id
claim
task_id
plan_revision
run_id
attempt_id
task_revision
workspace_hash
profile_id
change_kind
evidence_ids[]
acceptance_criteria[] -> { criterion_id, evidence_ids[] }
```

`evidence_ids` are references to canonical evidence records. The claim must not
embed a prose test report as a substitute for those records.

## Ordered evaluation

Perform these steps in order and stop at the first blocking defect:

1. **Normalize the claim.** Preserve the exact user-facing claim, identify the
   change kind, and determine whether it is a behavior change, bug fix,
   merge-readiness, or release-readiness claim.
2. **Resolve policy.** Resolve `profile_id` and its pinned policy from the
   active task/review contract. Do not let the claimant lower the resolved
   strictness. Enumerate required check classes and any proposed exception.
3. **Enumerate checks.** Create one check entry for each applicable class:
   lint, typecheck, tests, build, package, and requirements coverage. Split
   focused and broad tests when both are required. A single command may cover
   more than one class only when its output genuinely proves each class and
   the evidence maps the result to every class explicitly.
4. **Execute now.** Run the full command for each required check in the
   current attempt. Do not reuse output from an earlier run, terminal, agent,
   or branch. Capture command, working directory or scope, exit code, relevant
   output digest/location, and `recorded_at`.
5. **Inspect honestly.** A zero exit code is necessary for a successful check,
   not always sufficient. Inspect output for failed, skipped, quarantined,
   xfailed, not-run, or conditionally omitted checks. Record those states;
   never turn them into an implicit pass.
6. **Bind identity and freshness.** For every referenced evidence record,
   require the same `task_id`, `run_id`, `attempt_id`, `plan_revision`, and
   `task_revision` as the claim, and require the recorded `workspace_hash` to
   equal the current content-aware hash. Apply all rules in
   [evidence-freshness.md](evidence-freshness.md).
7. **Map acceptance.** Every acceptance criterion in the task and claim must
   have at least one applicable evidence ID. Evidence IDs must refer to the
   claim's top-level set; an unmapped criterion blocks the claim.
8. **Evaluate exceptions.** A skipped or replaced check is acceptable only
   through the machine-readable exception contract below. A narrative such as
   “not needed” is not an exception.
9. **Emit the outcome.** Emit a positive claim only when every required check
   is passing, every criterion is mapped, identity and freshness match, and no
   hidden failure or skip exists. Otherwise return a bounded rejection with
   the failing field or evidence ID.

## Independent check classes

| Check class | Proves | Does not prove |
| --- | --- | --- |
| `lint` | lint/style/static-rule command completed successfully | type correctness, tests, build, or requirements coverage |
| `typecheck` | configured type/static analysis completed successfully | runtime behavior, packaging, or full compilation unless explicitly documented |
| `tests` | the named focused, unit, integration, or broader test command passed | lint, build, package installation, or untested requirements |
| `build` | the declared source build/compile command passed | package contents, installation, or product requirements not exercised by the build |
| `package` | artifact creation, manifest, install, or package smoke check passed | source tests or requirements coverage outside that check |
| `requirements` | acceptance criteria and requirement traceability were checked against concrete evidence | implementation quality or command success by itself |

Do not collapse these into “validation passed”. If a project profile marks a
class not applicable, record that decision explicitly and link it to the
profile rule or approved exception.

## Machine-readable exception

An exception must be an object, not a sentence. Its canonical fields are:

```json
{
  "exception_id": "EX-...",
  "type": "generated_artifact|throwaway_prototype|configuration_only|data_only|emergency_authorized",
  "reason": "Why the normal check cannot run",
  "authority": "profile:prototype:1.1 or approval identifier",
  "alternative_verification": ["requirements:E-..."],
  "expires_at": "2099-01-01T00:00:00Z",
  "follow_up": "Optional bounded follow-up when expiry is not sufficient"
}
```

The exception `type` must be allowed by the resolved profile. `reason` must
explain the concrete limitation, `authority` must identify the profile rule or
approval, and `alternative_verification` must identify current evidence. An
`expires_at` or bounded `follow_up` is required when the policy requires one.
An exception never turns a failing check into a passing one; it records why a
required check was replaced or marked not applicable.

## Rejection conditions

Reject with actionable evidence when any of the following is true:

- the only proof is “it should work”, implementer confidence, or a
  summary-only claim;
- the claim says “tests passed” but provides no command, exit code, and current
  result;
- a result is prior-run or stale because it belongs to another task, plan
  revision, run, attempt, task revision, workspace, branch, dependency
  lockfile, or build configuration;
- any required check is missing, failed, skipped, quarantined, or not run and
  is not covered by a valid exception;
- hidden skipped/failed checks are present in output or a summarized result;
- only a summary, confidence score, checklist, reviewer opinion, or subagent
  message is available;
- a later material edit occurred after the evidence was collected;
- the acceptance mapping is absent, empty, duplicates an unknown criterion, or
  leaves a criterion without evidence;
- a focused test is being used to claim the broad suite, or lint/typecheck is
  being used to claim build/package/requirements coverage;
- a legacy artifact is being used as strict proof.

Return a rejection or `UNVERIFIED` result; do not emit a partial `PASS`.

## Legacy handling

Old handoffs or evidence that do not carry the new identity, command, result,
and freshness fields may be parsed for compatibility and migration. Their
verification classification is `LEGACY_UNVERIFIED`. They are not `VERIFIED`
and cannot satisfy strict production or high-risk completion, merge, or release
gates. A new current evidence record must be collected before promotion.
