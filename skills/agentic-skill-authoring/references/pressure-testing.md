# Pressure-testing protocol

Use this protocol when a skill changes agent behavior, workflow discipline, or a boundary that must hold under competing instructions. It is a concise evidence protocol, not an automation framework.

## Applicability

- A discipline-enforcing skill requires pressure testing before it is accepted.
- A pure reference skill may skip pressure scenarios when it has no observable behavioral contract. This does not waive RED/GREEN/REFACTOR evidence: use the absence/presence of the reference content, frontmatter, and links as the observable baseline and record the determination.
- Do not add a runner, dependency, scenario harness, or fake automation merely to execute this protocol.

## RED, GREEN, REFACTOR

1. **RED — without the skill.** Run a discriminating scenario against the baseline package. Record the exact setup or prompt, competing pressures, observed shortcut or failure, and any exact rationalization.
2. **GREEN — with the skill.** Repeat the same scenario with the candidate skill. Require the intended behavior, preserved role boundary, and an evidence-bearing handoff. Record the exact response, changed action, command output, or other direct observation.
3. **REFACTOR — close loopholes.** Vary the pressure, exception wording, or scope boundary. If the skill permits a shortcut, revise only the smallest skill content that closes it and rerun the affected scenarios. Do not claim GREEN from a post-hoc explanation alone.

## Minimum scenario set

Use at least three independent combined-pressure scenarios. Each scenario must combine the skill’s rule with a realistic reason to bypass it, such as:

- urgency or a supposedly trivial change used to justify skipping required evidence;
- scope pressure or an unrelated cleanup request used to cross a role or file boundary;
- exception or loophole wording used to relabel production work as disposable, generated, or otherwise exempt.

Scenarios may be manual prompts, small fixtures, or existing package checks. They must be discriminating: if the baseline already passes without the skill, replace the scenario or explain the observable gap it still measures.

## Evidence and stop conditions

For each scenario capture: identifier, exact setup/prompt, combined pressures, expected boundary, RED observation, exact rationalization quote, GREEN observation, REFACTOR change if any, and final result. A paraphrase such as “the agent understood” is not evidence.

Stop with `REPAIR_REQUIRED` when fewer than three discriminating scenarios exist, RED is missing, GREEN accepts the shortcut, or a loophole remains. Stop with `BLOCKED` when the required observation cannot be obtained within scope. For pure reference skills, stop only after the recorded inapplicability decision and structural validation are complete. Return the current evidence and limitations through the universal handoff.
