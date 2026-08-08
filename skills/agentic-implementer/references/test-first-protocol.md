# Test-first protocol

Use this protocol for every behavior change and bug fix. It makes the required evidence explicit without adding a test runner or framework.

## Required sequence

1. State the intended behavior in one sentence and identify the smallest existing test surface.
2. Add or adapt the smallest test that demonstrates the missing behavior, run it, and record the failing result (RED) before changing production code.
3. Make the smallest production change that turns that test green. Avoid unrelated refactors or speculative hardening.
4. Run the focused regression checks required by the task and inspect the final diff (GREEN and focused verification).
5. If a focused defect is found, make one correction at most and rerun the checks invalidated by that correction. Stop and escalate when it still fails or the approved scope would widen.

## Narrow exceptions

The RED step may be skipped only for:

- a throwaway prototype that is explicitly disposable and will not be treated as production behavior;
- a generated/config-only change where no production behavior is authored by hand.

The Primary Agent must record the exception, exact reason, affected files, and substitute evidence in the task handoff. The implementer must not silently classify work as an exception. For a skipped RED step, use an appropriate before/after observation or structural/configuration validation and still run focused verification.

## Stop conditions and evidence

Test-after or untested behavior changes are noncompliant outside those exceptions. Stop before production code and return `REPAIR_REQUIRED` or `BLOCKED` when the RED evidence is missing, the test does not exercise the requested behavior, the GREEN result is absent, or the focused checks cannot be run. Record the test path/name, commands, relevant output, implementation scope, correction count, and any limitation in the universal handoff.
