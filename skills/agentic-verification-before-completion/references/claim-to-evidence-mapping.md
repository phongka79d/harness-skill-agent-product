# Claim-to-Evidence Mapping

## Claim vocabulary

Apply this mapping before emitting any equivalent of:

`complete`, `fixed`, `passed`, `ready`, `resolved`, `successful`, `safe to
merge`, or `safe to release`.

The claim may be short, but the proof must be explicit. “The tests passed” is
not a mapping; it is a summary that must be replaced by evidence IDs and their
recorded command results.

## Claim shape

A completion claim identifies the work and references evidence rather than
embedding an agent report:

```text
claim_id
claim
task_id
plan_revision
run_id
attempt_id
task_revision
workspace_hash
profile_id
change_kind
evidence_ids[]
acceptance_criteria[] -> { criterion_id, evidence_ids[] }
```

The top-level `evidence_ids` set is the allow-list for the criterion mappings.
Every criterion mapping must contain at least one ID from that set. Every ID
must resolve to an evidence record for the same task, run, attempt, revisions,
and workspace. Unknown, duplicated, or cross-task IDs block the claim.

## What each claim must prove

| Claim | Minimum mapping |
| --- | --- |
| `complete` | All applicable acceptance criteria plus the profile-required checks for the change kind |
| `fixed` or `resolved` | A focused regression or reproducible check, the required broader verification, and evidence that the stated defect behavior is covered |
| `passed` or `successful` | The exact named check, its current command result, and every acceptance criterion the claim covers |
| `ready` | Current required verification, requirements mapping, and any delivery-specific checks required by the profile |
| `safe to merge` | Current tests and requirements evidence, plus lint/typecheck/build/package evidence when applicable to the repository and profile |
| `safe to release` | All applicable merge evidence, release/build/package evidence, and explicit treatment of every skipped or not-applicable check |

For a behavior change or bug fix, a strict profile may additionally require
the HSP-201 RED -> GREEN -> broad sequence. The claim must reference the
corresponding evidence records; a GREEN summary without the RED record is not
proof of test-first behavior.

## Keep check classes separate

Map evidence by check class so a criterion cannot inherit an unrelated pass:

- `lint` proves configured lint rules only;
- `typecheck` proves configured type/static analysis only;
- `tests` proves the named focused/unit/integration/e2e command only;
- `build` proves the declared build or compile command only;
- `package` proves the artifact, manifest, install, or package smoke check only;
- `requirements` proves acceptance and requirement traceability only.

One command may produce multiple evidence records or explicitly cover multiple
classes when it genuinely proves each one. Do not use a single generic
`validation` label to hide missing classes.

## Acceptance mapping rules

For every acceptance criterion:

1. Preserve the stable `criterion_id` from the task contract.
2. List one or more concrete evidence IDs that directly exercise or inspect
   that criterion.
3. Ensure each referenced record has a command, exit code, result, timestamp,
   identity, current workspace hash, and relevant output.
4. Include requirement coverage evidence when the criterion traces to a
   requirement; a passing test does not automatically prove traceability.
5. Mark `SKIPPED`, `NOT_APPLICABLE`, or `EXCEPTION` explicitly with the
   machine-readable authority and alternative evidence. Never omit the
   criterion to make the claim appear complete.

The mapping is incomplete when a criterion has no evidence, when evidence is
only a summary or confidence score, or when the referenced evidence is from a
prior run/attempt or stale workspace.

## Profile exceptions

An exception may replace a required check only when the resolved profile allows
its type. Store it as structured data with:

```text
exception_id
type
reason
authority
alternative_verification[]
expires_at or follow_up
```

The profile policy currently uses machine-readable exception types such as
`generated_artifact`, `throwaway_prototype`, `configuration_only`, `data_only`,
and `emergency_authorized`. Allowed types and strictness come from the active
profile policy, not from the claimant's preference. The exception's
`alternative_verification[]` entries must identify current evidence and remain
subject to the same identity and freshness gate. An emergency or prototype
exception is not a passing test result and does not conceal a failure.

## Legacy mapping

Legacy handoffs and evidence without the new identity and result contract may
be linked for context, but their classification is `LEGACY_UNVERIFIED`. They
cannot be used as strict proof for production or high-risk completion, merge,
or release claims. Recollect evidence in the current attempt and map the new
IDs explicitly.
