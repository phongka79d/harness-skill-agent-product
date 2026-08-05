# Brainstorm Handoff Example

The following is a complete documentation handoff for a small internal-tool change. It is illustrative and is not a runtime `.agent/` artifact.

```yaml
status: READY_FOR_PLANNING
profile: internal_tool
goal: "Add an opt-in 60-second cache to the report CLI without changing report contents or the default uncached behavior."
context_inspected:
  - README.md
  - src/report_cli.py
  - src/report_service.py
  - tests/test_report_cli.py
  - docs/agentic/decisions/report-cache.md
facts:
  - "The CLI calls ReportService.generate once per invocation."
  - "Existing tests assert report contents and the default command flags."
  - "No cache dependency is present in the project."
assumptions:
  - statement: "A process-local cache is sufficient for the internal tool."
    verification: "Confirm the command is not run across multiple worker processes in the plan's context check."
constraints:
  - "Default invocations remain uncached and behavior-compatible."
  - "Cache entries must expire after 60 seconds and must not contain secrets in logs."
  - "Only report CLI and its focused tests are in scope."
unknowns: []
decisions:
  - decision: "Use an explicit --cache-seconds option with 0 as the default."
    rationale: "Preserves existing behavior while making opt-in behavior observable and testable."
    authority: "Primary Agent"
subsystems:
  - name: cli-option
    responsibility: "Parse and validate the opt-in cache duration."
    depends_on: []
  - name: report-cache
    responsibility: "Own process-local keyed entries, expiry, and cache misses."
    depends_on: [cli-option]
  - name: regression-tests
    responsibility: "Prove default behavior, hit, miss, expiry, and invalid duration handling."
    depends_on: [cli-option, report-cache]
options:
  - approach: "Process-local cache in ReportService"
    trade_offs: "Smallest change and no dependency; does not share entries across processes."
    recommendation: true
  - approach: "External cache service"
    trade_offs: "Cross-process reuse but adds deployment, failure, and secret-management scope."
    recommendation: false
scope:
  in:
    - "CLI option, process-local cache, expiry behavior, and focused regression tests."
  out:
    - "External cache infrastructure."
    - "Changing report serialization or default command behavior."
error_handling:
  - "Reject negative or non-integer durations with a clear CLI error and no cache write."
  - "Treat an expired entry as a miss and regenerate the report."
  - "Do not retry a malformed cache entry; discard it and regenerate."
testing_strategy:
  - "Run the existing focused CLI tests before implementation as the baseline."
  - "Add behavior tests for default bypass, hit, miss, expiry, and invalid input."
  - "Run the affected test module and the repository-required internal-tool suite."
completion_conditions:
  - "The default command produces the same report and does not read or write the cache."
  - "An enabled cache returns a matching unexpired result and regenerates after expiry."
  - "Focused and profile-required broader tests pass with current workspace evidence."
self_review:
  status: PASS
  findings: []
approval_required: false
next_steps:
  - "Plan Architect creates bounded tasks with the listed file responsibilities and verification cases."
  - "Primary Agent confirms the process-local assumption during planning context inspection."
```
