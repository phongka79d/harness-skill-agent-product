# Delivery outcomes

The workflow decision maps each explicit action to one outcome:

| Action | Outcome |
|---|---|
| `keep_local` | `KEEP_LOCAL` |
| `merge_local` | `MERGE_LOCAL` |
| `push_branch` | `PUSH_BRANCH` |
| `create_review_request` | `CREATE_REVIEW_REQUEST` |
| `production_action` | `PRODUCTION_ACTION` |
| `destructive_cleanup` | `DESTRUCTIVE_CLEANUP` |

Do not substitute another outcome at finalization time. Active or incomplete work, missing target identity, stale verification, a missing completion gate, failed required review, mismatched batch review, missing approval, or unavailable action capability blocks execution and must be reported without writing a contradictory successful decision.
