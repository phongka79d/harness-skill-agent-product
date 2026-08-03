# Runtime State Boundary

`.agent/` contains generated runtime state and user-visible status only.

Agents may read:

- `.agent/runtime/state.json`
- `.agent/runtime/events.jsonl`
- `.agent/work/<id>/task-state.json`
- `.agent/work/<id>/checkpoint.json`
- `.agent/work/<id>/handoff.json`
- `.agent/work/<id>/context.json`
- `.agent/work/<id>/lease.json`
- `.agent/work/<id>/operations.jsonl`
- `.agent/locks/`
- `.agent/recovery/`
- `.agent/checklist.md`

Agents must submit structured payloads to `agentic-state-tools` instead of editing these files. Scripts own schema validation, timestamps, IDs, revisions, transitions, atomic writes, event appends, recovery rebuilds, rubric scores, and checklist rendering.

Planning documents and task definitions belong outside `.agent/`, normally under `docs/agentic/`.
