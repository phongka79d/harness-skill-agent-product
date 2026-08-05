# Escalation and Stop Rules

Count each rejected hypothesis and each materially similar failed fix against the same investigation. After three such rejections, stop ordinary repair and use the existing `BLOCKED` or `ESCALATED` state. Record the three experiments or fixes, their observations, and why the new context or decision needed to continue is not available.

Another attempt requires new context or a decision from the Primary Agent/user, such as a changed reproduction, newly available evidence, an approved scope change, or a different owner. Do not reset the count by restating an identical hypothesis or applying a cosmetic variation of the same failed fix. Never add a fourth repair-attempt state.

This skill owns product/code defects whose behavior can be investigated through repository evidence. `agentic-runtime-recovery` owns interrupted runs, stale leases, corrupt runtime state, uncertain external side effects, and decisions about whether a run is safe to resume. Escalate to runtime recovery when execution evidence or side-effect outcome is uncertain; do not use systematic debugging as a silent retry mechanism.

A `BLOCKED` or `ESCALATED` investigation may preserve failed evidence, but it must not claim `FIXED` or `PASS` without a confirmed root cause and passing verification.
