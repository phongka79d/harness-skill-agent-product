# State Boundary Policy

Reusable policy and schemas belong in installed skill packages. Project plans and human-facing decisions belong in `docs/agentic/`. Runtime artifacts belong only in `.agent/`. No role may hand-write canonical state, events, checkpoints, handoffs, reviews, locks, leases, recovery files, or checklist projections.

The state machine source is one JSON definition. Consumers must load it or use validated generated artifacts; duplicated lists are drift defects.
