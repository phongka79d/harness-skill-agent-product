# Brainstorm handoff

Status: READY

Summary: Keep the change local to the existing module and avoid a new dependency.

Constraints: Preserve the public interface and current storage format.

Recommended direction: Add one internal adapter using the repository's existing pattern.

Risks: One legacy call site needs confirmation during implementation.
