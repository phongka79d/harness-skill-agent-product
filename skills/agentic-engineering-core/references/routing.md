# Intent routing

Resolve the user's task intent before choosing execution depth or project policy.

| Route | Use for | Source editing |
|---|---|---|
| `quick_fix` | Known-cause, one-concern bounded correction | Yes |
| `debug` | Unknown or uncertain root cause followed by repair | Yes |
| `feature` | New user-visible or system capability | Yes |
| `refactor` | Internal restructuring with preserved behavior | Yes |
| `research` | Repository inspection and analysis only | No |
| `brainstorm` | Goals, constraints, alternatives, and direction | No |
| `plan` | Implementation plan without edits | No |
| `review` | Evaluation without repair | No |
| `documentation` | Project documentation changes | Yes |
| `configuration` | Central route, profile, approval, runtime, model-reference, or context-budget changes | Yes |
| `skill_authoring` | Skill package changes | Yes |
| `recovery` | Interrupted runtime reconciliation | No |
| `delivery` | Evidence-gated delivery decision | No |
| `general_change` | Source change that fits no narrower route | Yes |

`quick_fix` is valid only when the cause and correction are already known. Unclear scope, cross-module work, multiple concerns, or scope above the focused file limit must use `debug` or `general_change`.

Legacy `bug_fix` maps to `debug`, not `quick_fix`. Legacy `configuration` maps to the dedicated `configuration` route.
