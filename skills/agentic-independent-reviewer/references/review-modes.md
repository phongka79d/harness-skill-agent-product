# Review modes

| Mode | Input | Primary concern |
|---|---|---|
| `plan` | proposed implementation plan | can the plan be executed safely and completely? |
| `task` | one completed bounded task | does the change satisfy acceptance without correctness gaps? |
| `integration` | multiple accepted tasks or controlled delivery set | do the tasks remain valid when combined? |

Use only the requested mode. Integration review does not replace task review; it checks combined consequences after task-level findings are closed.

Task and integration review artifacts capture the reviewed workspace. Any later file change invalidates that review even when task status metadata is unchanged.

- Integration review may run against implemented `IN_PROGRESS` work before final verification and task completion; its task revision and workspace snapshot must remain current.
