---
name: agentic-systematic-debugging
description: Use when a flaky, inconsistent, unexplained failure, regression, failing test, timeout/timing issue, race, or incorrect output requires root-cause investigation before repair.
---

# Agentic Systematic Debugging

Read the shared `agentic-engineering-wiki` package before this workflow.
Read `agentic-configuration/SKILL.md` for routing and `agentic-engineering-core` for role and handoff boundaries. Use `agentic-state-tools` for task-bound evidence and handoffs.

Use this process for product or code defects. Use `agentic-runtime-recovery` for interrupted runs, uncertain side effects, stale leases, corrupt runtime state, or resume decisions.

## Workflow

1. Reproduce the symptom, or record why reproduction is impossible.
2. Capture the trigger, output, environment facts, and relevant recent changes.
3. Trace the failing value or state backward through the data flow.
4. Compare the failure with a working repository reference when one exists.
5. State exactly one falsifiable hypothesis and its predicted observation.
6. Run the smallest experiment that can confirm or reject that hypothesis.
7. Record the experiment result before proposing a repair.
8. Add a regression test or reproducible check.
9. Apply the smallest root-cause repair.
10. Run focused and broad verification.

## Boundaries

- Do not modify implementation before investigation evidence exists, except recorded diagnostic instrumentation.
- Do not combine speculative fixes in one attempt.
- Do not call a symptom the root cause without a backward data-flow trace.
- Do not use arbitrary sleep when a condition-based wait is available.
- Do not repeat an identical failed hypothesis; do not repeat an identical rejected hypothesis.
- After three rejected hypotheses or materially similar failed fixes, use the existing `BLOCKED` or `ESCALATED` state and stop ordinary repair.

Read the detailed protocol only when the debugging trigger is active:

- [debugging-protocol.md](references/debugging-protocol.md)
- [root-cause-tracing.md](references/root-cause-tracing.md)
- [condition-based-waiting.md](references/condition-based-waiting.md)
- [escalation-and-stop-rules.md](references/escalation-and-stop-rules.md)
