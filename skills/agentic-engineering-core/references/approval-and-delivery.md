# Approval and delivery

Risk flags and explicit delivery actions map through central configuration to approval keys. Approval-gated work uses controlled depth and requires an approval reference before implementation begins.

For delivery appended to source-editing work, state finalization runs before the delivery stage. A standalone delivery route operates on already completed tasks and therefore does not open or finalize a new task. Before `finalize_delivery.py` writes a decision, it requires:

- runtime is idle;
- every selected task is `COMPLETED` or `ACCEPTED`;
- current passing verification and completion gate when verification is required;
- current passing task review whose reviewed workspace still matches when review is required;
- a passing batch review with exact task bindings and a still-current integrated workspace when batch review is required;
- the configured approval reference when user approval is required.

For delivery appended to a source-editing route, tasks must belong to that workflow decision. Standalone `review` or `delivery` routes may select previously completed tasks explicitly with `task_ids`.

The finalizer only records the decision. The authorized host performs merge, push, review-request, production, or cleanup actions and then inspects the result.
