# Handoff Contract

Every role handoff must contain these headings:

```text
Status
Summary
Files Read
Files Changed
Findings
Implementation details
Validation results
Risks
Next Steps
```

`Files Changed` must be empty for Explorer, planning-review, and implementation-review roles unless the role is explicitly authorized to update a non-runtime report through a script. `NEEDS_RECONCILIATION` is valid when workspace or side-effect evidence conflicts with the handoff. Validation results must list the command or deterministic check and its outcome. Unknown or unverified claims belong under `Risks` or `Findings`, not under success.
