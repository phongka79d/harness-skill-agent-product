# Debugging protocol

Separate symptom, evidence, hypothesis, root cause, and repair. Prefer one discriminating observation over many speculative edits. Do not claim a root cause merely because a change appears to help.

## Scratch boundary

Experiments may create ephemeral scratch only in the non-empty host-owned temporary scope declared by the shared prompt (`{{HOST_TEMP_SCOPE}}`). The scope is an input, not an inference: if it is absent or ambiguous, do not create files and use read-only/in-memory observations or report `BLOCKED`. Source paths, the bound worktree, `.phongka`, task artifacts, and checklist files are never debugger scratch locations. Report paths and leave cleanup to the host that owns the scope.

Scratch does not grant authority to spawn/subdelegate, mutate runtime state, or broaden the repair boundary. The Primary Agent receives the evidence and owns any state recording or subsequent implementation dispatch.
