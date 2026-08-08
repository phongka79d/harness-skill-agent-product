# Unified Workflow Contract

Every task follows the same ordered lifecycle. A stage may be compressed or skipped only when its exit condition is already satisfied.

| Stage | Name | Required output | Exit condition |
|---|---|---|---|
| 0 | Route | task route, depth, scope, acceptance, risk and approval | contract is explicit |
| 1 | Explore | relevant facts, unknowns, constraints and affected boundaries | enough evidence exists to choose an approach |
| 2 | Design/Plan | selected approach and executable tasks | plan is implementable and approved when approval is required |
| 3 | Execute | bounded changes or read-only result | each task meets its local acceptance checks |
| 4 | Review/Repair | independent findings and bounded repairs | blocking findings are closed or explicitly blocked |
| 5 | Verify | fresh evidence mapped to every acceptance criterion | all required checks pass after final edits |
| 6 | Deliver/Record | final outcome, limitations, state and authorized side effect result | result is reconciled and reported |

## Compression rules

- `research`, `brainstorm`, `plan`, `review`, `recovery`, and `delivery` do not edit project source files. Recovery inspects existing runtime state without rebinding it; standalone delivery may rebind an idle runtime but does not open a new task.
- Focused work may combine Stages 1-3 in the Primary Agent, but verification remains a distinct final check.
- Debug work never skips root-cause evidence before repair.
- Controlled work never skips plan review, independent task review, fresh verification, or approval gates.
- A later material edit invalidates prior verification. It also invalidates review evidence for the changed scope; repair must be re-reviewed before verification.

## Stop rules

Stop with `BLOCKED` when required inputs, permissions, dependencies, or reproducible evidence are unavailable. Never expand scope, retry an uncertain side effect, or declare completion to hide a blocker.
