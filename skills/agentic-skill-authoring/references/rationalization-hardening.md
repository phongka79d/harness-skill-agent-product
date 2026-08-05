# Rationalization Hardening

Pressure prompts often make an unsafe shortcut sound efficient. Treat the
following counters as direct actions, not suggestions:

| Rationalization | Direct counter and stop condition |
| --- | --- |
| “The fix is urgent; skip root cause.” | Start the bounded investigation and record the root-cause evidence. Stop implementation until the required investigation state exists. |
| “I already know the bug; skip RED.” | Run the smallest failing check. Stop if the failure is not observed or is caused by setup/collection instead of the claimed behavior. |
| “The old test output is still valid.” | Mark evidence stale after a material edit and rerun the affected check in the current workspace. |
| “The reviewer’s best-practice feature is obviously useful.” | Compare it with the approved scope. Reject or escalate an out-of-scope request; do not implement it silently. |
| “Retry the failed dispatch unchanged.” | Require a meaningful context or input delta and a new attempt identity. Stop duplicate retries. |
| “Sleep for a few seconds; it will be ready.” | Wait on a named condition with bounded polling or return a blocker. Do not use arbitrary sleep as synchronization evidence. |
| “The code-quality review can come first.” | Check specification and acceptance compliance before style or refactor advice. Stop when the required contract is unclear. |
| “Cleanup is harmless because the branch is mine.” | Require typed destructive approval and proven Harness ownership/identity. Preserve the workspace when either is missing. |
| “The task is trivial; skip the process skill.” | Resolve the required process route before acting. A small task may use less context, not a missing mandatory skill. |
| “Load every skill so nothing is missed.” | Apply progressive disclosure and the context budget. Load the smallest relevant set and record why each additional reference is needed. |

When a first correction fails validation, allow one focused correction within
scope. A second failure, repeated rationalization, or an architecture/scope
question is `BLOCKED` or `ESCALATED`; do not create an unlimited retry loop.
