# Host bootstrap

## Provider-neutral host contract

At the host/project boundary, expose this repository's `./skills` directory as a skill source once. The exact registration is host-specific. The host must then:

1. Load the selected `SKILL.md` and any referenced prompts.
2. Compose `agentic-engineering-core/prompts/subagent-envelope.md` with the selected role prompt.
3. Execute ordinary Python CLI/scripts from the repository root.
4. Preserve the universal return fields in every role handoff and terminal report: `STATUS:`, `SUMMARY:`, `FILES_READ:`, `FILES_CHANGED:`, `EVIDENCE:`, `FINDINGS_OR_IMPLEMENTATION:`, `RISKS:`, `OPEN_QUESTIONS:`, and `NEXT_STEP:`.
5. Enforce the configured subagent waiting policy, including polling, total timeout, and close behavior.

The package is provider-neutral and cannot configure an external host or force it to auto-load files. If `./skills` is not exposed or a required host capability is unavailable, activation is `BLOCKED`.

`.codex-input.json` is not a package contract. It is neither required nor read/written/created by package scripts. Host scratch remains host-owned; the package does not infer or manage host configuration.

## Optional activation examples

Host selection forms vary. A native skill selector, host slash list, slash picker selection, explicit skill mention, prompt text, or eligible implicit repository invocation may activate `agentic-engineering-core`. Codex/OpenAI-style slash syntax, if supported by the host, is optional examples only, never prerequisites: Desktop may show enabled skills in a slash list; Codex CLI or an IDE may accept `$skill-name` or `/skills`; and a host may pass `/agentic-engineering-core` or `/prompts:<name>`. The package cannot register arbitrary host slash commands.

For a new workflow request, the receiving agent remains the sole Primary Agent through the terminal report and automatically resolves the workflow. For follow-up steering, it reads and continues the current active `.phongka` task and workflow decision; it reroutes only when the user clearly replaces that task. This is not whole-chat persistence.

## Activation check

From the repository root:

1. Confirm that the host exposes `./skills` as an active skill source and can load `skills/agentic-engineering-core/SKILL.md`.
2. Run the bundled checks:

   ```text
   python skills/agentic-configuration/scripts/load_config.py --check
   python skills/agentic-state-tools/scripts/resolve_workflow.py --profile personal --task-route documentation --estimated-files 1
   ```

3. Confirm the resolver returns `task_route`, `execution_depth`, and `required_skills` with `agentic-engineering-core` first. If a required host capability or check is unavailable, stop with `BLOCKED`.

For the first task turn, the Primary Agent must show:

```text
Activation: ./skills exposed; agentic-engineering-core loaded
Route: <resolved task_route>
Depth: <resolved execution_depth>
Scope: <approved files or boundaries>
Acceptance: <observable criteria>
Verification: <commands or evidence>
```

The Primary Agent then loads only the resolver-selected `required_skills`; the user does not need to name one.
