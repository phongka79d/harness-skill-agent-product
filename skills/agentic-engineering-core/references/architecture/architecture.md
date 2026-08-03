# Shared Architecture

The system separates reusable skill instructions from project runtime data.

Planning entry points are provided by `agentic-brainstorm-facilitator`, `agentic-plan-architect`, and `agentic-plan-reviewer`. Execution routing remains owned by the Primary Agent; a separate Orchestrator skill is not required.

```text
Workspace-installed skills
  ├── agentic-engineering-core
  ├── agentic-explorer
  ├── agentic-implementer
  ├── agentic-context-builder
  ├── agentic-task-reviewer
  ├── agentic-batch-reviewer
  ├── agentic-runtime-recovery
  └── agentic-state-tools

Project
  ├── docs/agentic/       human-authored plans, tasks, decisions, reviews
  └── .agent/             generated runtime state and status only
```

The Primary Agent coordinates role selection and approvals. State scripts validate payloads, assign IDs and revisions, write canonical files atomically, append events, calculate deterministic verdicts, and render `.agent/checklist.md`.

The event journal is historical truth. `state.json`, task state, context packages, checkpoints, leases, locks, reviews, and the checklist are derived or operational views with explicit contracts.
