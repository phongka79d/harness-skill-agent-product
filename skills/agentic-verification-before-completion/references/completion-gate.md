# Completion gate

A completion claim passes only when:

- the task is `COMPLETED` or `ACCEPTED`;
- the claim, verification artifact, and task share the current `work_revision`;
- verification is bound to the same workflow decision;
- all recorded workspace file hashes still match;
- every verification check passes;
- every acceptance criterion maps to non-empty passing evidence;
- remaining risks are disclosed.

For stateful work, a passing validation writes `completion-gate.json` bound to the task work revision and workflow decision. Delivery rechecks that gate together with current verification evidence.

Verification depth is risk-based, not ritual-based.
