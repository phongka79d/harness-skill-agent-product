# Deterministic skill routing

Routing is a persisted, deterministic input to dispatch. The routing artifact is
resolved from intent, current state, task type, repair status, risk flags, project
profile, requested role, and configured skills.

Resolution order is fixed:

1. Process skills are selected first for debugging, planning, clarification, or
   verification requirements.
2. The requested role selects its role skill.
3. A configured domain skill is appended when the task type has one.

The process chain cannot be bypassed by selecting a role skill. Every skill in
`required_skills` must be present in `loaded_skills`; state-tools rejects a
dispatch with an omitted mandatory process skill. Legacy dispatch payloads are
normalized into this artifact before persistence.

The routing policy explicitly disables the probabilistic “1% chance” rule.
Routing is reproducible for identical inputs and does not contain provider model
IDs. Model selection remains the responsibility of the central configuration and
deployment overlay.
