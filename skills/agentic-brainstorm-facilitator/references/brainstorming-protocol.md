# Brainstorming Protocol

This protocol turns an unclear engineering request into an approved-direction handoff. It is a design clarification process, not an implementation plan and not an architecture approval.

## 1. Establish context before proposing a design

Read the smallest relevant set of project material before suggesting architecture:

- project instructions and the active profile;
- the request, acceptance language, and known user constraints;
- the affected modules, interfaces, data flows, and configuration;
- existing tests, examples, and repository conventions;
- related plans, decisions, risks, and compatibility requirements.

Record what was inspected and the boundary of the inspection. If a required source is unavailable, state that limitation rather than presenting a guess as a repository fact.

## 2. Separate the evidence

Use distinct sections in the working record:

- **Facts:** observed in the request, repository, tests, or approved policy; include a source when practical.
- **Assumptions:** provisional beliefs needed to make progress; state how each will be verified.
- **Constraints:** non-negotiable technical, product, security, compatibility, schedule, or scope limits.
- **Unknowns:** unresolved questions that could change the direction, with an owner or decision deadline.
- **Decisions:** accepted direction, rationale, authority, and the alternatives it supersedes.

Do not promote an assumption or inference to a fact. A material unknown must become one focused question, an explicit bounded blocker, or a documented decision by the authorized owner.

## 3. Decompose the request

Identify independent subsystems, concerns, or decisions before discussing implementation. For each proposed slice, record:

- responsibility and public boundary;
- inputs, outputs, and relevant existing symbols or interfaces;
- dependencies and ordering;
- likely write scope and ownership;
- failure and recovery boundary;
- how the slice can be tested independently.

Split a request when it combines unrelated behavior, has different owners or risk levels, requires separate approvals, or would create overlapping write scopes. Keep tightly coupled changes together when splitting would hide an invariant or create an unverifiable intermediate state.

## 4. Compare real alternatives

Present two or three materially different viable approaches only when a genuine design choice exists. For each approach, state:

- the central shape and how it fits existing project conventions;
- benefits and costs;
- compatibility, migration, performance, security, and operability implications;
- testing and rollback implications;
- conditions under which it should be rejected.

Recommend one approach with a concise rationale tied to the stated constraints and evidence. If there is no meaningful choice, record the existing-pattern extension and why alternatives would add unnecessary scope.

## 5. Define the approved direction

Before handoff, make these explicit:

- **In scope:** behavior and artifacts to change.
- **Out of scope:** tempting adjacent work deliberately excluded.
- **Error handling:** invalid input, unavailable dependency, partial failure, timeout, conflict, and recovery behavior.
- **Testing strategy:** focused behavior checks, regression coverage, profile-required broader checks, and any permitted exception with its authority and expiry/follow-up.
- **Completion conditions:** observable evidence required before the Plan Architect can treat the direction as ready.
- **Open decisions:** unresolved items and exactly who must decide them.

The brainstorm facilitator can recommend a direction, but the Primary Agent or explicitly authorized owner must approve it before executable planning begins.

## 6. Ask focused questions

Ask at most one question at a time when user input is genuinely required to choose scope, compatibility, safety, or acceptance behavior. Make the question answerable and explain what decision it unblocks. Do not ask for information that can be discovered from project context or safely recorded as an assumption.

## 7. Handoff shape

The handoff should give the Plan Architect enough direction to create bounded tasks without redesigning the work. Include:

```text
status: READY_FOR_PLANNING | BLOCKED | NEEDS_DECISION
profile: <resolved profile>
goal: <measurable outcome>
context_inspected: [<paths or sources>]
facts: [<observations>]
assumptions: [<assumption and verification>]
constraints: [<non-negotiable limits>]
unknowns: [<question, owner, deadline or blocker>]
decisions: [<decision, rationale, authority>]
subsystems: [<bounded responsibility and dependency>]
options: [<approach, trade-offs, recommendation>]
scope: {in: [...], out: [...]}
error_handling: [<failure and recovery behavior>]
testing_strategy: [<checks and evidence>]
completion_conditions: [<observable conditions>]
self_review: {status: PASS | BLOCKED, findings: [...]}
approval_required: true | false
next_steps: [<planning actions>]
```

Use the [example handoff](../examples/brainstorm-handoff.example.md) as a concrete reference. This is a documentation shape, not a canonical `.agent/` artifact; runtime state must still be created by `agentic-state-tools`.
