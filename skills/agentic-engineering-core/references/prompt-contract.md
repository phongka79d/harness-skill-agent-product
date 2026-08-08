# Prompt Contract

Every subagent prompt must be self-contained and include:

1. Role, explicit role mode, and authority boundary.
2. Task ID and exact objective.
3. In-scope and out-of-scope work.
4. Allowed files and forbidden files or operations.
5. Acceptance criteria and required verification.
6. Inputs, evidence, dependencies, and known risks.
7. Expected return format.
8. Stop conditions.

Do not pass the entire conversation or ask a subagent to infer the task. Do not include secrets. Reference files by path and quote only the minimum facts needed.

## Universal return format

```text
STATUS: PASS | CHANGES_MADE | REPAIR_REQUIRED | BLOCKED
SUMMARY:
FILES_READ:
FILES_CHANGED:
EVIDENCE:
FINDINGS_OR_IMPLEMENTATION:
RISKS:
OPEN_QUESTIONS:
NEXT_STEP:
```
