---
name: agentic-configuration
description: Use to inspect or change central routing, subagent budgets, project profiles, approvals, runtime policy, provider-neutral model references, or context budgets.
---

# Agentic Configuration

This skill owns `config/agentic-config.json` and its schemas.

## Rules

1. Keep one Primary Agent: `agentic-engineering-core`.
2. Keep task intent separate from execution depth.
3. Keep route sequences aligned to the unified stage order.
4. Configure subagent ceilings as limits, never quotas.
5. Every model subagent must have a valid `prompt_path`, fresh context, explicit boundaries, and a universal return contract. One reviewer may serve plan, task, and integration modes when the stage is explicit.
6. Preserve read-only/source-editing route boundaries and approval derivation.
7. Keep provider IDs outside the package.
8. Execution remains synchronous; only independent read-only work may run concurrently. The default runtime permits one writer at a time.
9. Runtime state lives at `project/.phongka`.
10. Do not add queues, distributed locks, automatic merge, or implicit external actions.

## Validate

```bash
python scripts/load_config.py --check
python ../agentic-engineering-core/scripts/validate_skill_layout.py --skills-root ..
python ../agentic-engineering-core/scripts/run_exams.py --skills-root ..
python ../agentic-engineering-core/scripts/validate_examples.py --skills-root ..
```

Read [policy enforcement](references/policy-enforcement.md) before claiming a field is script-enforced.
