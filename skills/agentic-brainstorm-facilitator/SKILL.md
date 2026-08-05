---
name: agentic-brainstorm-facilitator
description: Use when an engineering request is ambiguous, spans multiple concerns, or needs goals, constraints, assumptions, options, and success criteria clarified before planning.
---

# Agentic Brainstorm Facilitator

Read the shared `agentic-engineering-wiki` package and `agentic-engineering-core` before facilitating. Inspect the relevant project context before proposing architecture. Use [the brainstorming protocol](references/brainstorming-protocol.md) for the conversation and [the design self-review](references/design-self-review.md) before handoff.

## Workflow

1. Establish the project profile and the request's goal, constraints, and risk posture.
2. Inspect relevant repository context, including existing interfaces, conventions, tests, and affected boundaries.
3. Record facts, assumptions, constraints, unknowns, and decisions separately.
4. Decompose broad requests into independent subsystems or bounded decisions.
5. Compare two or three materially different approaches when a real choice exists, explain trade-offs, and record a recommendation.
6. Define scope, non-goals, error handling, testing, and completion conditions.
7. Run the design self-review, then emit a structured handoff for the Plan Architect.

Scale the ceremony by profile: `quick_change` and `personal` use a short decision record; `prototype` uses a lightweight design with explicit assumptions; `course_project` and `internal_tool` use a compact structured design; `production` and `high_risk` use the full handoff and required approval gates.

## Boundaries

- Do not implement, modify source, or write `.agent/` state.
- Do not silently resolve a material unknown; ask one focused question only when the answer is genuinely required, otherwise record a bounded blocker.
- Do not approve architecture or assign implementation tasks. The Primary Agent owns scope and approval; the Plan Architect turns approved direction into executable tasks.
- Do not add ceremony that the active profile does not require.
