# Schema Index

Policy status: VALIDATED_ONLY

The installed state-tools package owns executable schemas for task state, events, planning, queues, dispatch, reviews, approvals, locks, leases, checkpoints, operations, and recovery. The authoritative state source is `skills/agentic-state-tools/schemas/state-machine.json`; its consumer schemas must match its enum sets.

Validate the Wiki links with `scripts/validate_wiki_links.py`. Validate the
state source with `skills/agentic-state-tools/scripts/validate_state_machine.py`.
Use `validate_payload.py` or the owning runtime command for payload behavior;
the presence of a schema field alone does not establish enforcement.

The release-backed contract set includes task state, planning, handoff,
batch-contract, dispatch, isolation-proof, transaction, change-request,
approval, review, lock, lease, checkpoint, operation, recovery,
verification-evidence, and completion-claim schemas.
Distributed and remote schemas are descriptive until a command and release
test consume them.
