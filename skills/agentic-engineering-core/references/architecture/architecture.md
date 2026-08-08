# Architecture

The suite is a role and workflow package, not a provider runtime. The host Primary Agent invokes role skills. `agentic-configuration` owns routing policy; `agentic-state-tools` resolves workflows and optionally persists compact state; the remaining skills define bounded responsibilities.

The central optimization is a stateless quick path with risk-based escalation.
