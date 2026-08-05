# Skill Design Guidelines

Design one bounded skill for one recognizable class of work. The description
must say when to use it using concrete triggers, symptoms, task types, or file
types; avoid descriptions such as “use for engineering tasks.”

## Entrypoint rules

- Keep `SKILL.md` short enough to load on every matching task.
- Write instructions as imperative actions: inspect, confirm, record, stop,
  validate, and report.
- Put the smallest safe workflow in the entrypoint and progressively disclose
  detail through local references.
- Name the owner role and state the read/write boundary explicitly.
- Define stop conditions for missing context, failed validation, unsafe side
  effects, scope conflict, and unresolved ambiguity.

## Rigid versus flexible guidance

Treat authorization, identity binding, secret handling, evidence freshness,
state-tool boundaries, destructive approvals, and stop conditions as rigid.
Profile-aware flexibility may change depth, breadth, timeout, or whether a
focused characterization check substitutes for broad verification when the
resolved profile permits it. Flexibility never removes a required safety gate
or converts missing evidence into a pass.

## Scope and reuse

Prefer process-oriented names and existing contracts. Do not duplicate central
policy, model/provider identifiers, schemas, or runtime behavior in prose.
Link to the canonical local contract and state-tool command instead. Keep
examples representative and bounded; do not turn an example into a second
policy source.

## Authoring checklist

Before handing off a skill, confirm:

- the trigger is concrete and the non-trigger boundary is clear;
- the workflow has observable actions and a safe stop path;
- required context, approvals, and evidence are named;
- rigid rules are separated from profile-dependent guidance;
- references are reachable and do not repeat the entrypoint unnecessarily;
- pressure scenarios cover the intended loopholes and expected evidence;
- the scenario schema and runner validate the examples without a provider
  literal.
