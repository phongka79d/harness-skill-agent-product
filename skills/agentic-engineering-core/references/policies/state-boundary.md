# State boundary

- Built-in focused, standard, and controlled execution defaults to required project-local state.
- Only a route or custom policy that explicitly resolves `state_mode: off` is stateless; `optional` remains available to custom policies.
- Agents may read `.phongka/`; canonical runtime writes use state-tools, while users may edit `.phongka/settings.json`.
- Project plans remain under `docs/agentic/`, not `.phongka/`.
- Never persist secrets or full unnecessary repository content.

- Required state initializes from the resolved workflow decision and stores its hash.
- Runtime initialization creates `.phongka/settings.json` from central defaults only when it is missing and never overwrites user values.
- An active task prevents runtime rebinding; an idle runtime may bind the next decision.
- Task content and task status use separate revisions so completion transitions do not invalidate fresh evidence.
