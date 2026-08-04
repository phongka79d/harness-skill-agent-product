# Testing Contract

Policy status: VALIDATED_ONLY

The release runner is `python run_tests.py --all`. Its deterministic groups
are unit, integration, schema, cli, e2e, concurrency, recovery, and release;
the release alias `end_to_end` maps to `e2e`. Each group reports passed,
failed, skipped, collection errors, elapsed seconds, and timeout state.

Release preflight runs these exact commands, in this order:

```text
python run_tests.py --all
python -m compileall -q skills tests run_tests.py
python skills/agentic-engineering-wiki/scripts/validate_wiki_links.py --root skills/agentic-engineering-wiki
python skills/agentic-state-tools/scripts/validate_state_machine.py --input skills/agentic-state-tools/schemas/state-machine.json
python skills/agentic-state-tools/scripts/validate_examples.py --examples-root skills/agentic-state-tools/examples --deployment skills/agentic-configuration/config/deployment.test.json
python skills/agentic-state-tools/scripts/package_skill.py --root . --output <release.zip>
```

The example gate requires positive examples to
pass their runtime validator and declared negative outcomes to be rejected for
their intended reason. A failed gate is named and does not stop the remaining
preflight checks.

Tests are evidence for runtime policy. A schema alone does not prove command
behavior, identity binding, recovery, authorization, or package inspection.
Unimplemented distributed and remote behavior remains outside the release
test surface.
