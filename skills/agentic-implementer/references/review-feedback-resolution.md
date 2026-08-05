# Review Feedback Resolution

Review feedback is a contract-bound finding, not an instruction to blindly edit.

1. Read the complete finding and its evidence.
2. Check the current code, approved decisions, task scope, compatibility rules, and actual usage.
3. Resolve ambiguity before editing and make one coherent correction.
4. Record targeted verification and persist the resolution through
   `create_review_resolution.py`.

Use `ACCEPTED`, `REJECTED_WITH_EVIDENCE`, `NEEDS_CLARIFICATION`, or `SUPERSEDED`
when the finding does not yet require a code correction. After a correction, use
`FIXED_PENDING_REREVIEW`. Only the reviewer may use `CLOSED`, and closure must link
the new review and its evidence.

Reject a suggestion only with concrete evidence: a contract conflict, existing
behavior or tests that disprove it, a compatibility restriction, out-of-scope work,
or a superseding accepted decision.
