---
name: agentic-delivery-finalizer
description: Use when accepted work needs an explicit keep, merge, push, review-request, production, release, or destructive-cleanup decision.
---

# Agentic Delivery Finalizer

1. Finalize runtime task state and completion gates before entering delivery.
2. Select the exact completed or accepted tasks.
3. Confirm required verification, completion gates, task review, and batch review are current.
4. Use the configured delivery action, outcome, cleanup policy, and approval requirement.
5. Record the decision before an external action.
6. Let an authorized host tool perform the action once.
7. Reconcile the actual result before reporting success or retrying.

The state script records a decision only. It never performs the side effect. Read [delivery outcomes](references/delivery-outcomes.md) and [merge and cleanup safety](references/merge-and-cleanup-safety.md).
