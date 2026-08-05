# Debugging Protocol

Record an investigation in this order:

`symptom -> reproduction -> environment/recent changes -> data-flow trace -> working reference -> one hypothesis -> smallest experiment -> result -> regression check -> minimal fix -> focused verification -> broad verification`

Each stage has a required evidence record and a stop condition:

1. **Symptom.** Record the user-visible or test-visible failure, trigger, expected output, and actual output. Stop if the symptom is not specific enough to distinguish success from failure; ask for a concrete observation or mark the investigation blocked.
2. **Reproduction.** Record the command or steps, fixture or input, and whether the failure was reproduced. If reproduction is impossible, record the attempts, available evidence, and the reason it cannot currently be reproduced; stop speculative repair until that limitation is documented.
3. **Environment and recent changes.** Record relevant versions, configuration, platform, timing facts, and recent commits or edits. Stop if a required environment fact is unknown and could change the result; capture it or state the uncertainty explicitly.
4. **Data-flow trace.** Record the failing value or state from its consumer backward through producers and transformations, including the first incorrect transition and owning boundary. Stop if the trace ends at an unobserved assumption; add diagnostic instrumentation or collect the missing evidence.
5. **Working reference.** Record the working test, implementation path, fixture, or prior revision used for comparison when one exists. Stop inventing a new pattern while an applicable repository reference has not been checked.
6. **One hypothesis.** Record exactly one falsifiable statement and its predicted observation. Stop if the statement cannot be confirmed or rejected by an observation, or if it combines multiple causes.
7. **Smallest experiment.** Record the minimal command or diagnostic observation that distinguishes the hypothesis from its negation. Stop before implementation changes; diagnostic instrumentation is allowed only when recorded and scoped to the experiment.
8. **Result.** Record the observed output, timestamp, exit status, and `CONFIRMED` or `REJECTED` outcome before proposing a fix. Stop and form a new non-duplicate hypothesis after rejection.
9. **Regression check.** Record the new or restored regression test/reproducible check and its pre-fix failure. Stop a repair handoff if no check can detect recurrence.
10. **Minimal fix.** Record the smallest change that addresses the confirmed first incorrect transition. Stop if the proposed change depends on an unconfirmed cause, combines speculative fixes, or expands scope.
11. **Focused verification.** Record the regression check after the fix, including command, exit code, and result. Stop a success claim unless it passes.
12. **Broad verification.** Record the relevant broader tests, lint, build, or integration checks and their results. A repair handoff cannot claim `FIXED` or `PASS` without a confirmed root cause and verification evidence.

The investigation record is evidence first: a symptom, passing test, or plausible explanation is not by itself a root cause.
