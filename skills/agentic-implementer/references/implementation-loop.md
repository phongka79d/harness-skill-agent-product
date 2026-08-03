# Implementation Loop

```text
read contract
→ inspect existing pattern
→ checkpoint intent through state tools
→ make scoped change
→ run targeted verification
→ checkpoint result through state tools
→ prepare handoff payload
→ validate and persist handoff
```

Create a checkpoint before a migration, deletion, external side effect, or context exhaustion. If validation fails, make one focused repair attempt; then escalate instead of widening scope.
