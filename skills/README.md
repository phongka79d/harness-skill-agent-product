# Phongka Agentic Engineering Skills — v3.5.1

Portable engineering workflow skills for agent-capable hosts. The package defines one **Primary Agent**, 9 bounded model subagent roles, deterministic workflow scripts, reusable prompts, and a project-local `.phongka` runtime for bundled workflows with explicit stateless route opt-outs.

## Activation

The host must register or expose this repository's `./skills` directory once. Its provider-neutral contract is to load the selected `SKILL.md` and prompts, compose the shared envelope plus the selected role prompt, execute ordinary Python CLI/scripts from the repository root, preserve the universal return fields, and enforce host-side subagent waiting. `agentic-engineering-core` is the sole public workflow entrypoint; role skills are internal dispatch targets and direct role invocation without Core routing is blocked. A host may expose Core through a native selector, host slash list, slash picker selection, explicit skill mention, prompt text, or eligible implicit repository work; these are optional activation examples, never prerequisites. Codex/OpenAI-style syntax such as `$agentic-engineering-core` or prompt text beginning `/agentic-engineering-core` is optional host syntax only, never a prerequisite.

`HOST-0` is an external host attestation that `./skills`, Core-first prompt composition, `open_task`, controlled worktree mapping, and wait/close enforcement are active. Missing or contradictory attestation fails closed before dispatch or source editing. `.codex-input.json` is not a package contract: it is neither required nor read/written/created by package scripts. Host scratch remains host-owned. Every role handoff and terminal report preserves `STATUS:`, `SUMMARY:`, `FILES_READ:`, `FILES_CHANGED:`, `EVIDENCE:`, `FINDINGS_OR_IMPLEMENTATION:`, `RISKS:`, `OPEN_QUESTIONS:`, and `NEXT_STEP:`. [AGENTS.md](../AGENTS.md) defines the project-boundary contract; [host-bootstrap.md](agentic-engineering-core/references/host-bootstrap.md) gives the provider-neutral host contract, optional activation examples, and first-turn check. A repository cannot force an external host to auto-load files or register arbitrary slash commands.

For a new workflow request, the receiving Primary classifies and resolves the workflow, loads `required_skills` in order—core, configured required companions, state when required, then route skills—and runs them without asking the user to name downstream skills. Required companions, including the shared `i-have-adhd` companion, are attached to the Primary and every delegated role prompt/handoff; they shape Primary user-facing output and each role agent's own commentary, handoff, and report. They are output guidance only, not stages, agents, owners, or a replacement for the Primary. For follow-up steering, it reads and continues the current active `.phongka` task and workflow decision; it reroutes only when the user clearly replaces that task. This is not whole-chat persistence.

## Architecture

```text
Primary Agent: agentic-engineering-core
  ├─ resolves route + execution depth
  ├─ schedules bounded subagents
  ├─ integrates findings and changes
  └─ owns approvals, verification sufficiency and final reporting

Subagents: fresh isolated role prompts
Tools: deterministic configuration/state scripts
  Runtime: project/.phongka (default project workflow runtime)
```

## Unified lifecycle

```text
Route → Explore → Design/Plan → Execute → Review/Repair → Verify → Deliver/Record
```

Stages are compressed for focused work, not reordered. Debugging precedes repair. Controlled work includes plan review, independent task review, fresh verification, and approval handling.

## Subagent ceilings

| Depth | Active | Total dispatches | Parallel writers |
|---|---:|---:|---:|
| focused | 1 | 2 | 1 |
| standard | 2 | 4 | 1 |
| controlled | 3 | 6 | 1 |

Limits are ceilings. One delegated role handles one independent domain/task and is a leaf: it cannot spawn, subdelegate, orchestrate, or mutate `.phongka` state. Only the Primary Agent may orchestrate multiple independent tasks, including unrelated subagent tasks. Reviewers and verifiers are read-only. All writers run sequentially in the default package; independent read-only roles may run concurrently. When spawning is unavailable, the Primary Agent follows the same role contracts directly without pretending agents ran.

For stateful work, the Primary Agent snapshots `.phongka/settings.json` before each model dispatch. A wait call that returns no terminal result is only one poll timeout; the agent remains open until the configured total timeout. `close_on_timeout: false` leaves it running and reports a blocker, while `true` permits close only after the total deadline and a final status check.

## Portable file layout

```text
skills/<skill>/
├── SKILL.md
├── agents/openai.yaml        # optional metadata for hosts that support this format
├── prompts/*.md              # model subagent prompt, when dispatchable
├── references/*.md           # progressive disclosure
├── scripts/*.py              # deterministic operations only
├── schemas/*.json            # machine contracts
├── examples/*                # examples
└── exams/*                   # deterministic behavior cases
```

## Resolve a workflow

```bash
python skills/agentic-state-tools/scripts/resolve_workflow.py \
  --profile personal \
  --task-route feature \
  --estimated-files 3 \
  --output /tmp/workflow-decision.json
```

The decision includes ordered skills, approval/evidence requirements, runtime actions, an explicit `subagent_plan`, and a worktree contract. Controlled source-editing adds `prepare_worktree` after task open; focused/standard work remains unbound.

## Project workflow runtime

When the resolved decision says `state_mode` is `required`, initialize the project-local runtime:

```bash
python skills/agentic-state-tools/scripts/init_runtime.py \
  --project-root <project> \
  --decision /tmp/workflow-decision.json

python skills/agentic-state-tools/scripts/load_runtime_settings.py \
  --project-root <project>
```

When the decision was resolved from a non-default config, pass the same `--config` path (or set `AGENTIC_CONFIG_FILE`) during initialization.

```text
.phongka/settings.json
.phongka/state.json
.phongka/events.jsonl
.phongka/tasks/<task-id>.json
.phongka/artifacts/<task-id>/verification.json
.phongka/artifacts/<task-id>/completion-claim.json
.phongka/artifacts/<task-id>/completion-gate.json
.phongka/artifacts/<task-id>/review.json
.phongka/batch-review.json
.phongka/delivery-decision.json
.phongka/checklist/task-checklist-<task-id>.md
```

`settings.json` is created from central `subagent_policy` and `execution` defaults only when missing. Users may edit `subagent_wait.check_interval_seconds`, `timeout_seconds`, and `close_on_timeout`, plus `execution` (`mode`: `sync`/`async`, `dispatch_timeout_seconds`, `max_active_subagents`) and `primary_agent_fallback`; later initialization validates and preserves those values. A schema v1 settings file is upgraded in place by `load_runtime_settings.py --ensure`, keeping the user's `subagent_wait` values. Actual polling, close, and dispatch operations remain host-enforced.

`.phongka` state, task/artifact/checklist files, and evidence indexes are Primary Agent/host-owned. Delegated roles may read them when assigned but never mutate them or invoke state-mutating CLI commands; generated, disposable, urgent, trivial, or cleanup labels do not grant an exception.

The built-in focused, standard, and controlled depth defaults are `required`, so normal project workflows initialize `.phongka`. A route may explicitly resolve `state_mode` to `off` (for example, `brainstorm`); only that explicit `off` decision uses the stateless path. Recovery inspects an existing runtime without rebinding it. A standalone delivery route may rebind an idle runtime, but it does not open or finalize a new task.

For a stateful run, the Primary Agent can mark the visible checkpoint after each stage:

```bash
python skills/agentic-state-tools/scripts/render_checklist.py \
  --project-root <project> \
  --task-id <task-id> \
  --current-stage <stage> \
  --current-skill <skill>
```

The generated `checklist/task-checklist-<task-id>.md` is a task-specific view only. The renderer selects an explicit task, then the active task, then the latest valid task-bound stage event; it fails closed when no task can be selected. It reports `unknown` and leaves all stages unchecked until a valid stage event is recorded. Checked stages mean reached, not completion, and rendering one task preserves the other task files.

Controlled source edits use a linked Git worktree at `../<project-name>-worktrees/<task-id>` (a sibling of the project root) with a deterministic `phongka/task/<task-id>` branch. The host `open_task` action runs after `init_runtime` and binds the task ID and scope; `prepare_worktree` maps that same ID and records path/branch/HEAD identity. Preparation and delivery require approval; the runtime verifies path, branch, HEAD, and evidence bindings. Missing `HOST-0`, task/worktree mapping, or identity evidence fails closed. Git merge, push, and worktree removal remain host-approved external actions and are never performed by these scripts.

## Validate the package

```bash
python skills/agentic-configuration/scripts/load_config.py --check
python skills/agentic-engineering-core/scripts/validate_skill_layout.py --skills-root skills
python skills/agentic-engineering-core/scripts/run_exams.py --skills-root skills
python skills/agentic-engineering-core/scripts/run_workflow_smoke.py --skills-root skills
python skills/agentic-engineering-core/scripts/run_contract_tests.py --skills-root skills
python skills/agentic-engineering-core/scripts/validate_markdown_links.py --skills-root skills
python skills/agentic-engineering-core/scripts/validate_examples.py --skills-root skills
python -B -c "import ast; from pathlib import Path; [ast.parse(path.read_text(encoding='utf-8')) for path in Path('skills').rglob('*.py')]"
```

## Legacy runtime migration

```bash
python skills/agentic-state-tools/scripts/migrate_runtime_root.py --project-root <project>
python skills/agentic-state-tools/scripts/migrate_runtime_root.py --project-root <project> --apply
```

The first command previews; `--apply` renames `.agent` to `.phongka` only when the target does not already exist.
