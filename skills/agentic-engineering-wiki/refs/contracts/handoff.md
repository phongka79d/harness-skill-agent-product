# Handoff Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/create_handoff.py`)

A handoff identifies the task, run, role, status, summary, files read and
changed, findings, implementation details, validation commands and results,
risks, and next steps. It must state blockers explicitly and link to canonical
artifacts rather than copying mutable runtime state.

The state-tools handoff contract additionally requires attempt ID, task and plan
revisions, input/output artifact hashes, structured evidence, and a timestamp.
`create_handoff.py --project-root <project> --task-id <id> --input <handoff.json>`
checks the payload schema and binds the handoff to the current task's task ID,
run ID, attempt ID, dispatch ID, task revision, plan revision, and artifact
hashes. A wrong run or attempt is rejected; the script does not accept an
identity supplied only in prose.

The handoff status is `COMPLETE`, `BLOCKED`, `ESCALATED`, or
`NEEDS_RECONCILIATION`. A complete handoff must include validation evidence;
recovery or unresolved side effects must remain explicitly classified rather
than being reported as complete.

Handoffs that predate structured verification are classified
`LEGACY_UNVERIFIED` by the writer. They remain readable for migration but do
not satisfy strict production or high-risk completion gates. New positive
claims must reference current evidence created by
`record_verification_evidence.py` and pass `verify_completion_claim.py`.
