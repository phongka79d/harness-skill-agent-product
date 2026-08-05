# Planning Workflow

Planning begins with an approved direction, not an implementation guess. The Brainstorm Facilitator first inspects relevant project context and records facts, assumptions, constraints, unknowns, decisions, alternatives, scope, error handling, testing, and completion conditions. It runs the design self-review and hands the result to the Plan Architect.

1. Clarify the request and record the approved architecture and constraints.
2. Resolve the project profile and scale the brainstorming ceremony to its risk: short decision record for `quick_change`/`personal`, lightweight design for `prototype`, compact structured design for `course_project`/`internal_tool`, and full handoff plus approval gates for `production`/`high_risk`.
3. Inspect affected repository context and identify independent subsystems, dependencies, ownership, and write boundaries.
4. Compare two or three materially different approaches when a real choice exists; record trade-offs and the authorized recommendation.
5. Run the design self-review for contradiction, ambiguity, placeholders, missing requirements, and unnecessary scope. Material unresolved findings are blockers, not silent assumptions.
6. Create versioned plans and atomic task contracts in the project documentation area.
7. For each new executable task, define the file responsibility map before
   assigning atomic work, keep dependency IDs identical to `depends_on`, and
   separate approved architecture decisions from implementation steps.
8. Validate schemas, dependencies, scope overlap, approvals, handoffs,
   placeholders, symbols/interfaces, and bounded task size.
9. Obtain the required approval before execution.

The detailed brainstorm protocol and self-review remain in `agentic-brainstorm-facilitator`; this Wiki entry is routing guidance. Plan changes create a new version and an immutable supersede link. Historical plan evidence is never edited in place.
