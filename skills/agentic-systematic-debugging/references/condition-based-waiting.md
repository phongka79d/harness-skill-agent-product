# Condition-Based Waiting

Use condition-based waiting for asynchronous, timing-sensitive, or race-prone behavior. A waiting record must contain:

- the named condition that must become true;
- the polling interval and why it is appropriate;
- the maximum deadline or timeout;
- the observed state for every poll; and
- the final timeout result, including the last observed state.

The condition must be observable, such as a file state, event, process status, queue entry, or test predicate. A timeout is evidence that the condition was not observed before the deadline; it is not evidence that the operation eventually succeeded.

Reject a bare `sleep` as evidence that a condition became true. A fixed delay may be part of a bounded polling implementation only when the named condition, deadline, and observations are recorded. If the condition is still false at the deadline, stop and report the timeout or investigate the producer; do not extend the delay arbitrarily or hide the race with repeated sleeps.
