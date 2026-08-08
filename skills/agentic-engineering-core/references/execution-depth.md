# Execution depth

Execution depth controls rigor, not task meaning.

| Depth | Typical use | Possible additions |
|---|---|---|
| `focused` | Small, bounded, low-risk work | Direct role execution and verification |
| `standard` | Moderate uncertainty or wider scope | Planning and project-local state |
| `controlled` | High risk, approval, oversized scope, or strict profile | Plan review, bounded context, state, independent task review, integration review |

Depth escalation never changes a read-only route into a source-editing route.

The debugging role owns reproduction, tracing, hypothesis testing, and root-cause identification. Standard and controlled debug paths do not call Explorer again after debugging; they proceed to implementation or planning.

The built-in focused, standard, and controlled defaults require project-local state. A route may explicitly resolve `state_mode: off`, and a custom central policy may still select `off` or `optional`.
