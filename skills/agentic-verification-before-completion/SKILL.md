---
name: agentic-verification-before-completion
description: Use when claiming work is complete, fixed, passed, ready, resolved, successful, safe to merge, or safe to release; require fresh task-bound command evidence.
---

# Agentic Verification Before Completion

Use this process at the boundary between implementation and any positive outcome
claim. It is required for claims equivalent to `complete`, `fixed`, `passed`,
`ready`, `resolved`, `successful`, `safe to merge`, or `safe to release`, even
when the change appears small.

Read `agentic-engineering-core`, the active task contract, the resolved project
profile, and the relevant `agentic-state-tools` evidence contract before
evaluating a claim. This skill defines the decision gate; the state tools own
the canonical evidence and completion artifacts.

## Gate workflow

1. State the exact claim and classify the change (`behavior_change`, `bug_fix`,
   `refactor`, `documentation`, `configuration`, or another approved kind).
2. Resolve the active profile and its verification policy. List each required
   check and every explicit exception before running verification.
3. Keep lint, typecheck, tests, build, package, and requirements coverage as
   separate check classes. Do not infer one class from another.
4. Run each required command in the current task, run, and attempt. Capture
   the command, exit code, relevant output digest or location, timestamp, and
   result.
5. Bind every evidence record to `task_id`, `run_id`, `attempt_id`,
   `plan_revision`, `task_revision`, and the current content-aware
   `workspace_hash`.
6. Map every acceptance criterion to one or more evidence IDs. Mark skipped,
   not-applicable, and failed checks explicitly; apply an exception only when
   its machine-readable contract is valid.
7. Recheck freshness after the last material edit. Emit the claim only when
   all required checks pass and no hidden failure or skip remains.

## Immediate rejection

Reject summary-only claims, “it should work”, implementer confidence, reviewer
or subagent success messages, prior-run/stale evidence, an unexecuted command,
a missing command or exit code, an unmapped acceptance criterion, or hidden
skipped/failed checks. A focused check does not prove the broad suite, a lint
pass does not prove a build, and a build does not prove requirements coverage.

Read the detailed rules only as needed:

- [completion-gate.md](references/completion-gate.md)
- [evidence-freshness.md](references/evidence-freshness.md)
- [claim-to-evidence-mapping.md](references/claim-to-evidence-mapping.md)

Legacy artifacts remain readable for migration and inspection, but their
verification status is `LEGACY_UNVERIFIED`; they cannot satisfy a new strict
completion gate without current evidence.
