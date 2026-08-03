# Architecture

The runtime follows Model A:

- Reusable instructions, references, schemas, scripts, and tests live in installed skill packages under `skills/`.
- Project plans, decisions, risks, and task definitions live in the project documentation area, normally `docs/agentic/`.
- Generated runtime state, event journals, locks, leases, checkpoints, reviews, and projections live under the project `.agent/` directory.

The Primary Agent remains the architecture owner. The Harness records and validates queue, dependency, dispatch, recovery, and approval decisions; it does not become a second architecture owner.

The canonical state machine is `skills/agentic-state-tools/schemas/state-machine.json`. Its validator must pass before consumers or schemas are released.
