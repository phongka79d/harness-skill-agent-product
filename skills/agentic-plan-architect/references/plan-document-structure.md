# Plan Document Structure

The Plan Architect writes one plan document tree per workflow into its declared staging scope, under `<date>-<feature>/`, where `<date>` is `YYYY-MM-DD` and `<feature>` is a short kebab-case slug of the goal. The Primary Agent installs the tree into `.phongka/plan/<date>-<feature>/` and records the path in the runtime plan binding.

Hierarchy: **Master Plan -> Plan N -> Batches -> Tasks -> Steps**.

## MasterPlan.md

```markdown
# <Feature> Implementation Plan

**Plan path:** `.phongka/plan/<date>-<feature>/`
**Bundle task IDs:** <plan_task_ids, comma separated>

**Goal:** <one sentence describing what this builds>

**Architecture:** <2-3 sentences about the approach>

**Tech Stack:** <key technologies/libraries>

## Global Constraints

<project-wide requirements - version floors, dependency limits, naming and
copy rules, platform requirements - one line each, copied from the spec>

## File map

| Path | Responsibility |
|---|---|
| <repo-relative path> | <what it owns> |

## Plans

| Plan | Batch count | Goal |
|---|---|---|
| Plan 1 | 2 | <one line> |
| Plan 2 | 1 | <one line> |

## Dependency and parallelism

<how plans and batches order; which lanes may run in parallel; which tasks are
strictly sequential because they share files>
```

## Plan-N.md

One file per plan section. `## Batch <N>` sections group tasks; each task is one `### Task <ID>` block with checkbox steps. Task IDs and acceptance IDs MUST exactly match the v5 bundle's `plan_task_id` and `acceptance` IDs.

```markdown
# Plan N: <Section Name>

**Goal:** <what this plan section delivers>

## Batch N: <Batch Name>

**Goal:** <what this batch delivers>

### Task <ID>: <Component Name>

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

**Interfaces:**
- Consumes: <what this task uses from earlier tasks - exact signatures>
- Produces: <what later tasks rely on - exact names, parameters, return types>

**Acceptance:** <acceptance ID>: <criterion the implementer and reviewer gate on>

- [ ] **Step 1: Write the failing test**

<actual test code>

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with <exact failure>

- [ ] **Step 3: Write the minimal implementation**

<actual implementation code>

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Run the focused verification**

Run: <verification command from the bundle task>
Expected: <exact observation>
```

## Rules

- Each step is one bounded action (2-5 minutes): write the failing test, run it to see it fail, implement the minimal change, run it to see it pass, run the focused verification.
- Every code step contains the actual code. No `TBD`, `implement later`, `add error handling` without content, or `similar to Task N`.
- A task belongs to exactly one batch; batches do not split a task across files.
- Later tasks reference earlier tasks only through the exact names and signatures declared in `Produces`/`Consumes`.
- Do not copy external plan templates verbatim; this structure is the house style and the Harness task contract fields (objective, files, dependencies, acceptance, verification, rollback) stay authoritative.
