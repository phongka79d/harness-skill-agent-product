# Schema Index

The installed state-tools package owns executable schemas for task state, events, planning, queues, dispatch, reviews, approvals, locks, leases, checkpoints, operations, and recovery. The authoritative state source is `skills/agentic-state-tools/schemas/state-machine.json`; its consumer schemas must match its enum sets.

Validate the Wiki links with `scripts/validate_wiki_links.py`. Validate the state source with `skills/agentic-state-tools/scripts/validate_state_machine.py`.
