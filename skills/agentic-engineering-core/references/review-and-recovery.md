# Review and recovery

Plan review checks feasibility, boundaries, dependencies, acceptance criteria, and material risk before controlled implementation.

Task review checks the current diff and evidence for one task. It returns `PASS`, `REPAIR_REQUIRED`, or `BLOCKED` and must not directly repair findings.

Batch review is used only for integrated multi-task or controlled work. It checks exact task bindings, interactions, shared files, integrated acceptance, delivery risk, and recovery implications.

Recovery begins by reading runtime state and event history, then classifies the interruption as safe to continue, blocked, externally uncertain, or requiring a new workflow decision. Never repeat an uncertain external side effect merely because its local record is missing.
