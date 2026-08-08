# Role boundaries

The **Primary Agent** is the sole orchestrator and public workflow owner. It classifies intent, packages bounded context, invokes roles, obtains approval, integrates results, and performs authorized external actions. It may orchestrate multiple independent tasks, including unrelated subagent tasks; independent read-only work may run in parallel, while writers remain sequential.

Every other role is a delegated leaf. A delegated role must not spawn, delegate, subdelegate, or orchestrate another role or task. Delegated roles may read runtime state when assigned, but never create, update, delete, or otherwise mutate `.phongka` state, task/artifact/checklist files, or invoke state-mutating CLI commands. The Primary Agent or host-owned state tools persist state. No urgency, trivial-change, unrelated-cleanup, or generated/config-only label changes that boundary.

- **Brainstorm Facilitator:** clarifies goals and alternatives; does not edit, dispatch, mutate state, or approve.
- **Explorer:** gathers repository facts; does not edit or mutate state.
- **Plan Architect:** creates bounded executable plans; does not implement, dispatch, or mutate state.
- **Independent Reviewer:** reviews in explicit `plan`, `task`, or `integration` mode; remains read-only, never repairs its own findings, and never writes review state directly.
- **Systematic Debugger:** establishes root cause before repair; uses only the declared host-owned scratch scope and never writes source or state.
- **Implementer:** performs the smallest complete ordinary source change within assigned files; does not dispatch or write state.
- **Configuration:** owns validated central workflow and profile configuration changes within assigned files; does not dispatch or write state outside the approved configuration workflow.
- **Skill Authoring:** changes skills while preserving package conventions; does not dispatch or write state.
- **Verification:** maps final claims to fresh evidence after the last material edit; remains read-only and does not persist completion state.
- **Runtime Recovery:** classifies interrupted state and safe next action; never retries blindly, dispatches, or mutates state.
- **Delivery Finalizer:** records an evidence- and approval-backed decision through the Primary/host; performs no external action or role dispatch.
- **State Tools:** provide deterministic resolution, validation, atomic local artifacts, and a read-only runtime dashboard when invoked by the Primary/host; they are not an autonomous role runtime.
- **Engineering Core:** shared policy and references plus the sole public orchestration contract.

Role skills and prompts are internal dispatch targets, not alternate public entrypoints; direct role invocation without Core's envelope and task contract is blocked.

Every delegated handoff uses the exact universal fields `STATUS:`, `SUMMARY:`, `FILES_READ:`, `FILES_CHANGED:`, `EVIDENCE:`, `FINDINGS_OR_IMPLEMENTATION:`, `RISKS:`, `OPEN_QUESTIONS:`, and `NEXT_STEP:`. Role-specific rubric or implementation details belong inside those fields; alternate labels such as `Status`, `Implementation`, or `Verification` do not replace them.
