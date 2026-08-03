# Agentic Engineering Remediation Design

**Status:** Approved by the user on 2026-08-03

**Scope:** Correct the declared-versus-enforced gaps found in the agentic engineering skill package. Preserve the existing command-line interfaces where possible, but make security and quality gates fail closed.

## Goals

- Keep one canonical deployment configuration for role routing, execution limits, approvals, security, and feature gates.
- Make canonical plan, batch, task, rubric, review, handoff, and approval artifacts authoritative by revision and hash.
- Prevent review payloads, alternate config files, forged actors, and direct event writes from weakening policy.
- Persist orchestration state durably and make restart, retry, repair, and recovery deterministic.
- Keep asynchronous execution disabled until isolated worktree and merge safety are enforced.
- Make secret handling, examples, tests, and package output enforce the documented contract.

## Non-goals

- Rewriting the package in a new language or replacing the filesystem backend.
- Choosing a provider-specific model name in a portable skill. Deployment config owns concrete model IDs.
- Adding a dashboard write path or allowing agents to mutate canonical artifacts directly.

## Architecture

The `agentic-configuration` skill owns the portable configuration contract. Its checked-in config contains role keys and model references, while a deployment overlay resolves references to provider model IDs. `load_config.py` validates both layers, merges only approved fields, and enforces an immutable policy floor. Consumers resolve configuration through the loader instead of reading role prompts or embedding model IDs.

The state-tools skill owns a small policy and persistence boundary. Canonical loaders validate artifact identity and hashes. Review creation derives policy from the pinned rubric; payloads can add evidence but cannot replace policy fields. State mutations use the transition registry and an operation ledger. Multi-file operations write a prepared operation record, perform atomic file replacements, append a commit marker, and reconcile incomplete operations on restart.

## Trust boundaries

1. User identity, primary-agent identity, and tool actor values are distinct. A string in an input payload is not proof of identity.
2. Canonical artifacts are read from the project state root and are pinned by ID, revision, and SHA-256 hash.
3. Reviewer input is untrusted evidence. It cannot define thresholds, criteria, hard-fail rules, expected task IDs, or verdicts.
4. Runtime state is authoritative only after event replay and operation-ledger reconciliation agree.
5. Context input is untrusted repository data. Secrets, binaries, denied paths, and over-budget content are rejected or redacted before persistence.

## Workstream boundaries

1. Portable configuration and model routing: schemas, resolver, deployment overlay, and consumer migration.
2. Review integrity: rubric pinning, exact criterion sets, score validation, task verdict derivation, and batch completeness.
3. Authorization and approval fencing: typed approvals, identity checks, target binding, expiry, and destructive gates.
4. Planning and risk: reverse membership, requirement references, dependency cycles, scope semantics, and boolean risk flags.
5. Durable orchestration: queue, graph, lease, run/attempt IDs, idempotency, task revision checks, and parallel limits.
6. Async worktrees: isolated branch/worktree mapping, workspace locks, merge/conflict handling, and stale cleanup.
7. Recovery and crash safety: transition registry consumers, checkpoint contracts, operation reconciliation, and restart tests.
8. Context security: secret scanner, path denylist, binary guard, redaction, and budget enforcement.
9. Test, example, and package hardening: runtime example validation, adversarial coverage, release timeout, and allowlisted packaging.

## Invariants

- Effective model selection must resolve through one validated config and may never select a forbidden or undeclared model.
- A review's rubric identity must match the task or batch contract: profile, task type, risk flags, rubric ID/version/hash, and policy version.
- The submitted criterion ID set must equal the canonical criterion ID set exactly once.
- A task review cannot pass below threshold, below a mandatory minimum, with an unresolved hard fail, or with a severe unresolved finding.
- A batch review must contain exactly the canonical expected task IDs and accepted task reviews, plus passing integration, regression, and scope checks.
- Every state change must be an allowed transition for the actor and an idempotent operation for the same revision/attempt.
- A lease cannot be renewed after expiry without an explicit reclaim operation.
- Async mode is invalid unless isolated worktree support is present and enabled.
- Context artifacts and logs cannot contain detected secrets or sensitive files.
- Any artifact revision or hash change invalidates approvals and review decisions tied to the old artifact.

## Failure and recovery model

Each multi-file mutation has an operation ID and idempotency key. A prepared ledger record lists intended writes and prior hashes. Each file is written through a temporary file, flushed, and atomically renamed. A commit marker is written only after all intended files match their target hashes. On restart, reconciliation completes a fully written operation, rolls back a prepared-but-incomplete operation when safe, and reports `RECOVERY_PENDING` when external side effects cannot be inferred.

Queue, graph, lease, task state, event journal, and Git/worktree state are reconciled before resume. A stale lease is never extended by heartbeat. Checkpoints are resumable only when their schema, task revision, attempt ID, and input hashes match the active contract.

## Validation strategy

Implementation follows RED-GREEN-REFACTOR. Every enforcement change starts with a failing unit or integration test. Negative cases are first-class: forged actors, missing batch tasks, duplicate criteria, altered hashes, stale revisions, crash points, concurrent dispatch, secret inputs, and invalid transitions. The release runner reports test groups independently and validates examples with runtime entry points, not only schemas.

## Rollout gates

1. Configuration and review integrity must be green before accepting any new review.
2. Authorization and planning gates must be green before enabling commit or next-batch actions.
3. Durable orchestration and recovery must be green before enabling restart/resume automation.
4. Worktree isolation must be green before setting async execution to enabled.
5. Context security and packaging checks must be green before distributing the skill package.

