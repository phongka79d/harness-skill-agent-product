# Role boundaries

- **Primary Agent:** classifies intent, packages bounded context, invokes roles, obtains approval, integrates results, and performs authorized external actions.
- **Brainstorm Facilitator:** clarifies goals and alternatives; does not edit or approve.
- **Explorer:** gathers repository facts; does not edit or mutate state.
- **Plan Architect:** creates bounded executable plans; does not implement.
- **Independent Reviewer:** reviews in explicit `plan`, `task`, or `integration` mode; remains read-only and never repairs its own findings.
- **Systematic Debugger:** establishes root cause before repair.
- **Implementer:** performs the smallest complete ordinary source change.
- **Configuration:** owns validated central workflow and profile configuration changes.
- **Skill Authoring:** changes skills while preserving package conventions.
- **Verification:** maps final claims to fresh evidence after the last material edit.
- **Runtime Recovery:** classifies interrupted state and safe next action; never retries blindly.
- **Delivery Finalizer:** records an evidence- and approval-backed decision; performs no external action.
- **State Tools:** deterministic resolution, validation, atomic local artifacts, and read-only runtime dashboard.
- **Engineering Core:** shared policy and references plus the sole orchestration contract.
