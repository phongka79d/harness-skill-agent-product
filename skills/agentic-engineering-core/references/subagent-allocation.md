# Subagent Allocation Policy

The Primary Agent is the only orchestrator and is not counted as a subagent.

| Depth | Active subagents | Total dispatches | Parallel writers | Default pattern |
|---|---:|---:|---:|---|
| `focused` | 1 | 2 | 1 | one implementer; optional fresh reviewer |
| `standard` | 2 | 4 | 1 | analysis/planning as needed, implementer, reviewer |
| `controlled` | 3 | 6 | 1 | reviewed plan, implementation wave(s), reviewer, verifier |

These are ceilings, not quotas. They include repair and re-review dispatches. Not every eligible stage is delegated; reserve capacity for likely repair/re-review, and use zero subagents when the Primary Agent can safely complete focused work directly.

## Dispatch rules

1. One subagent per independent problem domain or plan task.
2. Parallelize only read-only agents with no mutable-state dependency.
3. Run writers sequentially. A host may raise this limit only after replacing the runtime with isolated workspaces and equivalent state enforcement.
4. Every dispatched agent starts with fresh isolated context and a self-contained prompt.
5. Implementers may edit; explorers, planners, reviewers, and verifiers are read-only unless their role contract explicitly says otherwise. Map reviewer stages explicitly: `plan_review → plan`, `review → task`, and `batch_review → integration`.
6. A reviewer never repairs its own findings. Repairs return to an implementer, then receive scoped re-review.
7. Do not pad the team to reach a tier limit. Prefer delegating independent review and final verification over low-value context packaging.
8. If the dispatch budget is exhausted, the Primary Agent performs the remaining bounded role; it must not skip fresh verification or fabricate a subagent result. Re-route or report `BLOCKED` when independence is mandatory.
9. When subagent tools are unavailable, synthesize the same role outputs without claiming that agents were spawned.

## Wait policy

For a stateful workflow, the Primary Agent loads `.phongka/settings.json` with `load_runtime_settings.py` immediately before each model dispatch and snapshots `subagent_wait` for that dispatch. An explicitly stateless route uses the central `subagent_policy.wait` defaults. Settings changes apply to the next dispatch, not to an in-flight deadline.

1. Record the dispatch start time and compute one total deadline from `timeout_seconds`.
2. Poll for at most `check_interval_seconds` or the remaining total time, whichever is shorter.
3. A poll that returns no terminal status is expected asynchronous state. Keep the agent open and poll again.
4. When the total deadline is reached, perform one final status check.
5. If `close_on_timeout` is `false`, leave the agent running, report the timeout as a blocker, and wait for user direction. Do not synthesize a result.
6. If `close_on_timeout` is `true`, close the still-running agent only after the final check, record the timeout, and apply the bounded fallback rules below. Mandatory independence may still require `BLOCKED`.

The settings loader validates and exposes this policy. The host owns elapsed-time tracking, provider polling, and any actual close operation.

## Dispatch failure fallback

When a subagent is unavailable, exceeds its configured total timeout, returns malformed/incomplete output, or exhausts its dispatch budget:

1. The Primary Agent records the stage/task, failure reason, and whether the result was synthesized.
2. The Primary Agent may perform the same bounded role directly, using the approved files, acceptance criteria, and verification checks. Label it as a synthesized fallback; never claim the subagent ran.
3. If the route requires independent review, fresh verification, approval, or external reconciliation, do not replace that gate with an unqualified same-agent claim. Use an allowed fresh dispatch or stop as `BLOCKED`.
4. Retry only within the configured dispatch and repair limits. After fallback, rerun affected checks and report skipped evidence or remaining risk explicitly.

## Repair limits

- Focused: 1 repair round.
- Standard: 2 repair rounds.
- Controlled: 3 repair rounds.

After the limit, adjudicate remaining findings. Any load-bearing open finding makes the task `BLOCKED`.
