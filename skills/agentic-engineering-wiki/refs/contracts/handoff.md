# Handoff Contract

A handoff identifies the task, run, role, status, summary, files read and changed, findings, implementation details, validation commands and results, risks, and next steps. It must state blockers explicitly and must link to canonical artifacts rather than copying mutable runtime state.

The state-tools handoff contract additionally requires attempt ID, task and plan revisions, input/output artifact hashes, structured evidence, and a timestamp. These bindings prevent a handoff from being replayed for another attempt or revision.
