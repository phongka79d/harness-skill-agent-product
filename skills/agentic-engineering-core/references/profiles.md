# Project profiles

Profiles describe project policy, not task intent. They set minimum depth, focused limits, state persistence, review policy, batch review, verification level, and project metadata.

- `personal`: neutral default and adaptive local work.
- `prototype`: speed-oriented exploratory implementation.
- `course_project`: moderate structure and verification.
- `internal_tool`: stronger review for shared internal use.
- `production`: controlled depth, persistent state, independent and batch review.
- `high_risk`: strict controls for sensitive or consequential work.
- `quick_change`: compatibility profile only; it does not replace task routing.

A strict profile may escalate a read-only request, but the route remains read-only.
