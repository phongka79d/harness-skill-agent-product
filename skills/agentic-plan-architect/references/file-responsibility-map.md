# File Responsibility Map

Define ownership before splitting a plan into atomic tasks. Each map entry has
an exact repository-relative `path`, a single `owner`, and the `concern` that
owner controls. Optional `symbols` identify the interfaces owned in that file.

```json
[
  {
    "path": "skills/agentic-state-tools/scripts/validate_planning.py",
    "owner": "planning-validator",
    "concern": "cross-field and cross-task planning invariants",
    "symbols": ["skills/agentic-state-tools/scripts/validate_planning.py::validate_manifest"]
  }
]
```

The map must cover every `exact_paths` entry exactly once in the task. Across
executable tasks, a path cannot be claimed twice, and a qualified symbol cannot
be assigned to different owners. Keep shared concerns in one task or record an
approved dependency and revise the scope explicitly; do not rely on a vague
"similar" or "as appropriate" handoff.
