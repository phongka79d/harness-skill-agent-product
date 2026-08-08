# Policy enforcement boundary

Central configuration is active policy, but enforcement is split deliberately to keep the package lean.

## Resolver-enforced

- route and token validity;
- source-editing invariants;
- debug-before-edit and verify-after-edit ordering;
- controlled source-change review;
- quick-fix boundedness;
- depth escalation and repair/context limits;
- approval-key resolution;
- delivery-action mapping;
- evidence-requirement resolution;
- state-mode and runtime-action resolution.

## Runtime-enforced

- workflow-decision, profile, and risk-contract binding;
- one open task;
- approval reference before approval-gated `IN_PROGRESS` work;
- work-revision and file-hash freshness;
- persisted completion gates;
- revision-bound task reviews and decision-bound batch reviews;
- runtime-settings schema validation, atomic creation, and preservation of existing user settings;
- idle/completed task requirements before delivery;
- delivery action, outcome, cleanup, evidence, and approval consistency.

## Host-enforced

- semantic classification of raw user language;
- respecting context-byte and unbounded-scan policy while reading files;
- actual redaction and secret handling outside persisted artifacts;
- role invocation, subagent polling, total-timeout tracking, close behavior, and repair-cycle stopping;
- obtaining user approval and passing its reference;
- executing authorized Git, provider, deployment, or cleanup actions.

A policy described as host-enforced must not be presented as an action performed automatically by the scripts. `load_runtime_settings.py` validates the wait policy, but it does not wait for, close, or cancel provider agents.
