# Root-Cause Tracing

Trace backward from the failing observation. The record must name:

- the failing value or state;
- the consumer that observed it;
- its producer;
- every relevant transformation between producer and consumer;
- the first incorrect transition; and
- the owning boundary responsible for that transition.

For each link, label what was directly observed separately from what is inferred. Include the command, fixture, log, test assertion, or instrumentation that supports an observed fact. Mark an inference as a hypothesis until an experiment confirms it.

Compare the trace with a working repository reference whenever one exists: a passing test, known-good fixture, neighboring implementation, or earlier working revision. Record the reference path and the specific behavior it establishes. Follow the existing pattern before inventing a new one; a difference from the working reference is evidence to investigate, not permission to redesign.

The trace is complete only when the first incorrect transition is supported by an observation and assigned to an owning boundary. If the trace cannot reach that point, document the missing evidence and stop ordinary repair. Do not label the last visible symptom as the root cause merely because it is closest to the failure.
