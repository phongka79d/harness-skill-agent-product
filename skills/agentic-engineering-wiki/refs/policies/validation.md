# Validation Policy

Use test-first validation for behavior changes. Watch the focused test fail for the missing behavior, implement the smallest change, then run the focused and full suites. Before claiming completion, run the exact release gate, inspect the output and exit code, and report skipped or failed validation explicitly.

Evidence is required for `PASS`, `NOT_APPLICABLE`, approvals, terminal cleanup, recovery safety, and release claims.
