# Project Agent Instructions

## Activation and routing

Before editing, the Primary Agent must:

1. Load [agentic-engineering-core](skills/agentic-engineering-core/SKILL.md) first and treat it as the only orchestrator.
2. Classify the request into `task_route` and `execution_depth`, then resolve both with the bundled resolver and config ([resolver](skills/agentic-state-tools/scripts/resolve_workflow.py), [config](skills/agentic-configuration/config/agentic-config.json)). Load only the returned `required_skills`, in order; the user does not need to name a skill.
3. Show `route`, `depth`, `scope`, `acceptance`, and `verification` before editing.
4. Preserve role boundaries: the Primary Agent owns routing, scope, integration, and final validation; delegated roles edit or review only their approved scope.
5. If a selected role cannot be dispatched but the configured route permits a fallback, label the result `SYNTHESIZED FALLBACK`. If the host cannot expose/register `./skills`, load the core skill, access the bundled resolver/config, or perform a required route or verification gate, stop with `BLOCKED`; do not claim activation or silently substitute.

Read [host bootstrap](skills/agentic-engineering-core/references/host-bootstrap.md) for the one-time host prerequisite and activation check.
