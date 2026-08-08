# Finding severity

- `CRITICAL`: unsafe, destructive, security-compromising, or invalidates delivery.
- `HIGH`: violates acceptance or causes likely functional failure.
- `MEDIUM`: material defect or maintainability risk that should be fixed in scope.
- `LOW`: non-blocking improvement; never use it to force unrelated cleanup.

Only `CRITICAL`, `HIGH`, and in-scope `MEDIUM` findings may require repair.
