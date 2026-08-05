# Design Self-Review

Run this review after the direction is written and before handing it to the Plan Architect. The purpose is to catch design defects and scope drift, not to replace the independent plan review or task review.

## Review checklist

### Contradiction

- Do the goal, constraints, decisions, scope, and completion conditions agree?
- Does any proposed approach violate a repository invariant, role boundary, approved policy, or dependency order?
- Does the recommendation contradict a stated non-goal or an unresolved decision?

### Ambiguity

- Could two implementers interpret the behavior, ownership, interface, or error result differently?
- Are terms such as “improve,” “support,” “fast,” or “safe” replaced by observable behavior?
- Are unknowns clearly distinguished from assumptions and assigned to an owner when material?

### Placeholders and missing requirements

- Are there empty sections, TODO markers, invented paths, fake examples, or unresolved template tokens?
- Are compatibility, migration, security/privacy, observability, rollback, and recovery requirements addressed when relevant?
- Does every stated acceptance condition have a test or other concrete evidence path?

### Unnecessary scope

- Does each subsystem support the goal or a required safety/compliance condition?
- Can any optional abstraction, cleanup, migration, or documentation expansion be removed without weakening the outcome?
- Is the ceremony proportional to the active profile and risk flags?

### Handoff readiness

- Is the recommended approach explicit and backed by trade-offs?
- Are in-scope and out-of-scope boundaries precise enough to form write scopes?
- Can the Plan Architect create executable tasks without making a new architecture decision?
- Is approval authority explicit, and are blocked decisions reported instead of guessed?

## Disposition

Record the result as `PASS` only when no material finding remains. Record each finding with severity, evidence, owner, and next action. A material contradiction, missing requirement, unresolved safety decision, or placeholder in a required field produces `BLOCKED` or `NEEDS_DECISION`; it must not be hidden in a recommendation.

For `quick_change` and `personal`, a compact checklist and short decision record are sufficient. `prototype` requires explicit assumptions and a lightweight review. `course_project` and `internal_tool` require the full checklist in compact form. `production` and `high_risk` require the full checklist, documented evidence, and the applicable approval before planning handoff.
