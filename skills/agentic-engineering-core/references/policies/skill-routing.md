# Deterministic skill routing

Routing is intentionally smaller than the original suite but keeps its useful precedence rule:

1. Resolve the user-facing `task_route`.
2. Resolve `execution_depth` from route minimum, profile minimum, scope, and risk.
3. Expand the route's configured token sequence into process and role skills.
4. Add only justified review, integration-review, delivery, or state-tool support.

`task_route` and `execution_depth` are independent. Do not rename every small task to `quick_fix`, and do not convert read-only tasks into implementation merely because their scope is large.

Load every skill in `required_skills` in the returned order. Do not load all available skills “just in case”; unrelated skills are context debt.

The Primary Agent performs semantic classification from the user's request. The deterministic resolver validates and expands that classification; it does not claim to infer intent from arbitrary natural language.


Use the [intent routing rubric](intent-routing-rubric.md) for ambiguous boundaries. `quick_fix` is a narrow known-cause route, not the default for small work.

A resolved decision also contains approval, delivery, evidence-requirement, runtime-action, and decision-hash contracts. The host must preserve those fields when initializing state rather than reconstructing them from memory.
