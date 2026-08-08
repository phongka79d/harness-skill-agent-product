# Recovery model

State is a hint; the workspace, workflow decision binding, recorded evidence, and external provider outcome are evidence. Resume only from a known safe point.

When outcome is uncertain, inspect before retrying. If task files and the state index differ, return `RECONCILE_TASK_INDEX`; do not delete, recreate, or retry automatically. Do not rebind runtime while a task is open. Once the runtime is idle, a new validated workflow decision may be bound without deleting historical task files.

Archive or explicitly migrate incompatible runtime schemas rather than merging them into schema version 7 state.
