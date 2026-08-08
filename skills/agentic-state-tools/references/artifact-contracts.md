# Minimal artifact contracts

State mode is resolved from execution depth, project profile, route override, delivery needs, and explicit persistence needs. The bundled focused, standard, and controlled defaults are required; explicit route or custom-policy `off` and `optional` modes remain supported.

`.phongka/settings.json` is user-editable runtime policy, not task evidence. Initialization creates it from central defaults only when missing, validates it on later initialization, and never overwrites valid user values.

A stateful task may use these task artifacts:

- `context.json`: bounded files, constraints, and notes.
- `handoff.json`: outcome, changed files, verification summary, risks, next step.
- `verification.json`: checks plus generated work revision, workflow-decision binding, and current file hashes.
- `review.json`: independent outcome bound to current work and exact reviewed workspace when review is required.
- `completion-claim.json`: the accepted claim persisted so later delivery can recheck its mapping and hash.
- `completion-gate.json`: generated only after current verification, full-scope evidence, and acceptance mapping pass.

Controlled integrated work may also use `.phongka/batch-review.json`, bound to the current delivery decision, exact task revisions, and integrated workspace hashes.

Task `scope` is a non-empty unique list of normalized repository-relative file paths. Absolute paths, parent traversal, `.phongka`, and `.agent` are rejected. Every review, batch review, and verification snapshot must include every scoped path for the task or task set. Additional relevant files may be included.

`record_verification_evidence.py` adds the current `work_revision`, workflow decision hash, and recording time. Every verification `checks[].name` is a stable acceptance ID and must be unique. Its `workspace.files` entries must come from the current project and contain `path`, `size`, and `sha256`; the recorder rechecks all files before writing.

`verify_completion_claim.py` accepts a claim only when its work revision and verification artifact still match the task, the full scope still matches, verification status is `PASS`, the task is `COMPLETED` or `ACCEPTED`, and the claim acceptance IDs exactly match the verification check IDs. It persists the accepted claim and a claim-hash-bound gate.

`finalize_delivery.py` rechecks all evidence required by the resolved route, including the persisted claim and its gate hash. It never treats artifact presence alone as acceptance.

A status-only transition advances `status_revision` but does not invalidate evidence. Summary, scope, risk metadata, decision binding, or file changes do. Review and batch-review snapshots make post-review file changes fail closed even when task metadata was not updated.

State and task files form one index. Validators reject missing indexed task files and orphan task files. Recovery reports `RECONCILE_TASK_INDEX` and never deletes or retries automatically.

Do not create empty artifacts merely to satisfy a route shape. Each artifact must reduce ambiguity or support recovery.

Batch review accepts implemented tasks in `IN_PROGRESS`, `COMPLETED`, or `ACCEPTED` state because it precedes final verification; delivery still requires all selected tasks to be completed or accepted.
