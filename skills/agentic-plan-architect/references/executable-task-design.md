# Executable Task Design

Use this contract when creating a new atomic task. Older artifacts remain
readable, but a new task should set `contract_mode` to `executable`.

## Required contract

Include the task objective and context, then add:

- `prerequisite_decisions`: accepted decision IDs required before work;
- `exact_paths`: repository-relative files, without globs or directories;
- `relevant_symbols`: symbols or interfaces, using `path/to/file.py::Name`
  when the path is known;
- `allowed_files` and `forbidden_files`: the complete file boundary;
- `dependency_ids`: the exact same set as `depends_on`;
- `implementation_steps`: ordered, concrete actions for one attempt;
- `validation_mode`: `TDD` or `ALTERNATIVE`, plus `validation_steps`;
- `red_required` and `expected_red` when a behavior test must fail first;
- `expected_green`: the observable passing result;
- `verification_commands`: exact runnable commands, including broad checks;
- `acceptance_criteria_ids`: exactly the criterion IDs in the task;
- `rollback_recovery_note` when any risk flag is active;
- `handoff_expectations`: evidence and state expected from the implementer;
- `file_responsibility_map`: one owner and concern for every exact path.

Keep `execution_budget.max_files_changed` at least as large as
`exact_paths`, and keep the task small enough for one implementer attempt.
Do not put a new architecture decision in a step. Reference its accepted
decision ID instead.

## Verification example

```json
{
  "validation_mode": "TDD",
  "validation_steps": [
    "python -m unittest tests/unit/test_contract.py"
  ],
  "red_required": true,
  "expected_red": {
    "result": "exit code 1 with assertion that AC-1 behavior is missing",
    "failure_signature": "expected missing behavior"
  },
  "expected_green": "exit code 0 with AC-1 and the focused suite passing",
  "verification_commands": [
    "python -m unittest tests/unit/test_contract.py",
    "python -m unittest discover -s tests -p 'test_*.py'"
  ]
}
```

Run the placeholder validator before submitting the task. Phrases such as
`TODO`, `add validation`, or `write tests` are rejected unless the same
instruction includes a precise path, command, acceptance ID, expected result,
or other testable detail.
