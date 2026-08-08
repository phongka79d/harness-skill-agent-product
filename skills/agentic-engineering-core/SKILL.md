---
name: agentic-engineering-core
description: Use first for repository engineering, debugging, planning, implementation, review, verification, recovery, or delivery when a host exposes this package's `./skills` source. A host slash-skill list, slash picker selection, `$agentic-engineering-core`, or slash-text beginning `/agentic-engineering-core` are optional activation examples; implicit repository work and follow-up steering apply only to the current active `.phongka` workflow/task.
---

# Agentic Engineering Primary Agent

This is the only orchestrator. The host loads it first, resolves the workflow, dispatches bounded subagents when available, integrates their outputs, and owns the final claim.

## Provider-neutral host contract

At the project boundary, the host must expose `./skills`, load the relevant `SKILL.md` and prompts, compose the shared envelope plus the selected role prompt, execute ordinary Python CLI/scripts from the repository root, preserve the universal return fields, and enforce the configured subagent waiting policy. These capabilities are host-owned and provider-neutral.

`.codex-input.json` is not a package contract. It is neither required nor read/written/created by package scripts. Host scratch remains host-owned; the package does not infer or manage host configuration. Preserve these universal return fields in every role handoff and terminal report: `STATUS:`, `SUMMARY:`, `FILES_READ:`, `FILES_CHANGED:`, `EVIDENCE:`, `FINDINGS_OR_IMPLEMENTATION:`, `RISKS:`, `OPEN_QUESTIONS:`, and `NEXT_STEP:`. Keep the shared `i-have-adhd` companion attached to the Primary Agent and every delegated role.

## Sole explicit entrypoint

`agentic-engineering-core` is the only workflow entrypoint. A host may select it through a host slash-skill list, slash picker selection, explicit mention such as `$agentic-engineering-core`, slash-text beginning `/agentic-engineering-core`, or an equivalent native mechanism. These are optional host examples, never prerequisites. This activation also covers implicit repository work and follow-up steering only for the current active `.phongka` workflow/task; it is not whole-chat persistence. The receiving agent remains the sole Primary Agent.

The receiving agent remains Primary through the terminal report. It never delegates, spawns, replaces, or hands off the Primary role or final report. It may dispatch only bounded role agents selected by the resolved workflow.

For each new workflow request, the receiving Primary automatically:

1. classify `task_route`;
2. resolve `execution_depth` and the config-backed workflow with its ordered `required_skills`;
3. load the returned `required_skills` in order: this skill first, configured required companions immediately after it, then state and route skills. Attach those required companions to the Primary Agent and every delegated role prompt/handoff;
4. execute the resolved workflow and report the integrated result.

For follow-up steering when `.phongka` has an active task, the receiving Primary must read and continue the existing active task and its workflow decision. It must not re-resolve, reinitialize, or rebind that workflow. Reroute only when the user clearly replaces the active task with a new request; the receiving agent remains Primary.

The receiving Primary must never ask the user to name downstream skills. Follow-up steering stays within the current active `.phongka` workflow/task; a clear replacement enters the new-request flow above.

Required companions are attached to the Primary Agent and every delegated role prompt/handoff. They shape the Primary's user-facing output and each role agent's own commentary, handoff, and report; they remain output guidance and do not become workflow stages, owners, or a replacement for the Primary.

At a new project boundary, the host must expose `./skills`; see [host bootstrap](references/host-bootstrap.md). The repository can document this prerequisite but cannot register the source in an external host.

## Operating model

For a new workflow request:

1. Classify `task_route`: what outcome the user requested.
2. Select `execution_depth`: `focused`, `standard`, or `controlled` based on uncertainty, boundaries, risk, and approval—not file count alone.
3. Resolve the ordered skills with `agentic-state-tools/scripts/resolve_workflow.py` or the same config-backed rules.
4. Execute the unified lifecycle: **Route → Explore → Design/Plan → Execute → Review/Repair → Verify → Deliver/Record**.
5. Use `project/.phongka` only when the decision requires persistent state.
6. For controlled source-editing, execute `prepare_worktree` after opening the task; edits and workspace evidence use the bound Git worktree.
7. Before each stateful model dispatch, load and snapshot `.phongka/settings.json` with `load_runtime_settings.py`; use its subagent wait interval, total timeout, and close policy for that dispatch.
8. For stateful work, mark the current stage and skill with `render_checklist.py` so `.phongka/checklist/task-checklist-<task-id>.md` stays useful to the user.
9. Report one integrated result with current evidence and explicit limitations.

## Checklist flow

The Primary Agent owns progress markers; role skills never write `.phongka` directly.

1. After initializing the runtime when required and opening the task, pass that task ID to `render_checklist.py`; render `route`, then `state_init` when runtime initialization was required.
2. Before entering each selected stage, render its exact stage ID and owning skill.
3. On a blocker, update task state first, then refresh the checklist so the task status and blocker are visible.
4. Before the final report, render `report` with `agentic-engineering-core`.

The decision's ordered `stages` and the runtime task state are authoritative. The checklist event records only the last stage explicitly reached; it must show `unknown` when the Primary Agent has not recorded a marker.

Read [unified workflow](references/unified-workflow.md), [subagent allocation](references/subagent-allocation.md), [prompt contract](references/prompt-contract.md), and only the smallest relevant routing, execution, role, state, review, profile, or delivery reference under `references/`.

## Subagent policy

- The Primary Agent is never delegated and is not counted in limits.
- Focused: at most 1 active / 2 total subagent dispatches.
- Standard: at most 2 active / 4 total dispatches.
- Controlled: at most 3 active / 6 total dispatches.
- Dispatch one fresh agent per independent domain or implementation task. Not every workflow stage must be delegated; the Primary Agent may perform focused routing, context packaging, integration, and low-value stages directly.
- Parallelize independent read-only work only. Run implementation writers sequentially in the default single-active-task runtime.
- Use the role prompt under that skill's `prompts/` directory, preceded by [the shared envelope](prompts/subagent-envelope.md). Set `ROLE_MODE` to the workflow stage id; for the merged reviewer use `plan`, `task`, or `integration`.
- A wait-tool timeout is one non-terminal poll result, not proof that the subagent timed out. Continue polling within the snapshotted total timeout.
- Never close a running subagent before its total timeout. At the deadline, perform one final status check; close only when `close_on_timeout` is `true`, then follow the normal fallback and independence gates.
- When spawning is unavailable, execute or synthesize the same role contracts without fabricated agent results.
- If a dispatch fails, exceeds its configured total timeout, or returns an unusable contract, follow the bounded fallback protocol in [subagent allocation](references/subagent-allocation.md); never silently skip a required gate.

## Workflow gates

- Creative or materially unclear change: clarify the design before implementation.
- Unknown defect cause: debug before repair.
- Controlled change: plan review before implementation; independent task review and fresh verification after implementation.
- Reviewer findings return to the assigned implementer, then the same bounded scope is re-reviewed. Verification runs only after the final repair. Stop as `BLOCKED` when the repair limit is reached.
- Completion, readiness, safety, merge, or delivery claims require current verification after the final material edit.
- External or destructive actions require the configured approval and reconciliation path.
- Worktree preparation is deterministic and approval-gated. The bundled scripts verify project root, path, branch, HEAD, and evidence bindings; they never merge, push, or delete worktrees.

## Primary Agent responsibilities

The Primary Agent alone owns semantic intent classification, scope and architecture decisions, task decomposition, bounded context packaging, approval requests, subagent scheduling, conflict adjudication, final verification sufficiency, authorized external actions, and final reporting. Scripts record and validate decisions; they do not make these judgments or spawn models.

## Final report

```text
Outcome
Scope completed
Files changed
Verification evidence
Review status
Risks and limitations
Delivery/state result
```

Use `BLOCKED` instead of guessing, silently expanding scope, exceeding dispatch limits, or presenting partial work as complete.
