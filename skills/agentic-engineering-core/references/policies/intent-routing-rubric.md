# Intent routing rubric

Classify the user's requested outcome before sizing execution.

| User intent or evidence | Route |
|---|---|
| Cause and bounded correction are already known | `quick_fix` |
| Cause is unknown, uncertain, intermittent, or requires reproduction | `debug` |
| Add a new user-visible or system capability | `feature` |
| Change internal structure while preserving intended behavior | `refactor` |
| Inspect, compare, explain, or gather repository facts without edits | `research` |
| Clarify goals, constraints, alternatives, or direction | `brainstorm` |
| Produce an executable plan without implementing it | `plan` |
| Evaluate an existing diff, plan, artifact, or result without repairing it | `review` |
| Create or update documentation as the requested deliverable | `documentation` |
| Change central routing, profiles, approval, runtime, model-reference, or context-budget configuration | `configuration` |
| Create or modify a skill package or skill instructions | `skill_authoring` |
| Reconcile interrupted runtime or uncertain side effects | `recovery` |
| Decide an explicit local, push, review-request, production, or cleanup outcome | `delivery` |
| Source change is requested but does not fit a narrower route confidently | `general_change` |

## Hard distinctions

- “Fix this error” is `debug` unless the request already supplies a credible cause and bounded correction.
- “Analyze why this happens” without a repair request is `research`; with repair requested it is `debug`.
- “Suggest implementation steps” is `plan`; “implement this capability” is `feature`.
- “Clean up structure without changing behavior” is `refactor`; architecture or public-contract changes add risk flags and controlled depth.
- Documentation accompanying a code change does not replace the primary code route. Use `documentation` only when documentation itself is the main deliverable.
- Ordinary application configuration remains the route matching that application change. Use `configuration` for this suite's central workflow and profile policy.
- Changes to skill runtime code use the route matching the code task. Use `skill_authoring` when the requested artifact is the skill package or its instructions.

## Quick-fix guard

Do not classify as `quick_fix` when any of these apply:

- root cause is unknown;
- scope is unclear;
- more than one concern is involved;
- work crosses modules materially;
- expected files exceed the configured bounded limit.

Use `debug` when investigation is required. Otherwise use `general_change`.
