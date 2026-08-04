# Authorization Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/authorization.py`)

Protected actions use a persisted approval with `approval_id`, `target_type`,
`target_id`, `decision`, `approver`, `actor_type`, `actor_id`, `action`,
`target_revision`, `target_hash`, `policy_version`, `issued_at`, `expires_at`,
evidence, creation timestamp, and revision. The authorizer binds all of these
fields to the requested target and actor. The decision must be `APPROVED`, the
approval must not be expired, and the target revision and hash must still
match.

Primary-owned plan, profile, rubric, and architecture changes require the
Primary Agent. Batch commit, worktree merge, and advancing to the next batch
require the configured approval actor; the command must pass `--approval`,
`--actor`, and `--actor-type`. Missing, expired, wrong-target, wrong-actor, or
stale approvals are rejected.

Authorization is enforced at command boundaries, not merely by fields present
in a JSON schema. Remote identity providers and external approval services are
NOT_IMPLEMENTED.
