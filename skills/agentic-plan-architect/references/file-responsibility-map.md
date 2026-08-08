# File responsibility map

Use normalized repository-relative paths only. Reject absolute paths, parent traversal, runtime state paths (`.phongka`, `.agent`), and task files outside the plan-level scope.

Assign a file to one task when multiple tasks exist. When two tasks must touch the same file, one must depend directly or transitively on the other so the single writer has an explicit order. Otherwise merge the edits into one task or add one ordered integration task.

Focused single-task execution does not need a separate map; list bounded files inline.
