# Finding Severity

- `CRITICAL`: security vulnerability, data loss, destructive operation, fundamental architecture violation, or main requirement missing.
- `MAJOR`: acceptance criterion missed, important logic incorrect, required verification failed, or significant out-of-scope change.
- `MINOR`: maintainability issue, weak naming, missing non-critical test, or incomplete documentation.
- `SUGGESTION`: optional non-blocking improvement; must not create an infinite repair loop.

Every finding needs evidence, a location when applicable, and a required change.

During `SPEC_COMPLIANCE`, a missing or extra requirement is at least `MAJOR` and
must not be offset by a weighted quality score. During `CODE_QUALITY`, a behavior or
scope change requires a fresh specification review against the new artifact identity.
