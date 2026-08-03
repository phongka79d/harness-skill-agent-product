# Agentic Engineering Routing Compatibility

The canonical shared Wiki is the installed `agentic-engineering-wiki` package. This file remains as a compatibility pointer for older consumers; do not add new policy here.

Use this table of contents to load only the reference needed for the current role.

| Need | Read |
|---|---|
| Central agent/model/runtime configuration | `agentic-configuration/SKILL.md`, `agentic-configuration/config/agentic-config.yaml` |
| Shared boundaries and fallback | `agentic-engineering-wiki/refs/policies/delegation.md` |
| Architecture and workspace boundary | `agentic-engineering-wiki/refs/architecture/architecture.md`, `agentic-engineering-wiki/refs/policies/state-boundary.md` |
| Planning contracts | `agentic-engineering-wiki/refs/contracts/planning.md`, `agentic-state-tools/schemas/`, `agentic-state-tools/scripts/validate_planning.py` |
| Planning dependency and scope checks | `agentic-state-tools/scripts/validate_dependency_graph.py`, `detect_scope_overlap.py` |
| Task dispatch | `agentic-engineering-wiki/refs/workflows/execution.md`, `agentic-state-tools/scripts/resolve_runnable_tasks.py`, `resolve_execution_mode.py` |
| Project profiles and review rubrics | `agentic-engineering-wiki/refs/profiles/profiles.md`, `agentic-engineering-wiki/refs/contracts/rubric.md`, `agentic-state-tools/profiles/`, `resolve_project_profile.py`, `resolve_rubric.py` |
| Handoffs and approvals | `agentic-engineering-wiki/refs/contracts/handoff.md`, `agentic-state-tools/schemas/approval.schema.json` |
| Runtime state and recovery | `agentic-engineering-wiki/refs/workflows/recovery.md`, `agentic-state-tools/SKILL.md`, `agentic-runtime-recovery/references/recovery-model.md` |

Keep project-specific plans and decisions in the project's documentation area. Keep generated runtime artifacts under `.agent/`; do not copy this routing index into `.agent/`.
