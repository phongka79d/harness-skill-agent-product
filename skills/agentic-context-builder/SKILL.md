---
name: agentic-context-builder
description: Use when an approved task needs a bounded context package of contracts, constraints, relevant files, symbols, patterns, and review history without a full repository scan.
---

# Agentic Context Builder

Read the shared `agentic-engineering-wiki` package before this role's workflow.
Read [agentic-configuration](../agentic-configuration/SKILL.md) before applying context-budget or redaction defaults.

Assemble context; do not make architecture decisions and do not modify implementation or `.agent/` state directly.

## Workflow

1. Read `agentic-engineering-core` and the task contract.
2. Resolve inherited constraints and required decisions.
3. Select relevant project documentation, files, symbols, patterns, and prior findings.
4. Enforce the configured budget before adding optional context.
5. Redact secrets and unrelated user data.
6. Emit a structured context payload and submit it to `agentic-state-tools/scripts/create_context.py` for validation and persistence.

## Priority order

1. Active task and acceptance criteria.
2. Contracts and inherited constraints.
3. Directly relevant files and symbols.
4. Existing repository patterns and tests.
5. Relevant decisions, assumptions, risks, and review history.
6. Limited examples.

If context is insufficient, report the exact gap. Do not silently scan the entire repository or invent a missing decision.

Read [context-contract.md](references/context-contract.md).
