# Distributed Scheduling and Remote State Design

**Status:** Approved for inline implementation under the P2 continuation approval.

**Goal:** Extend the local runtime contracts with a backend-neutral state-store
interface and remote-style concurrency semantics without changing the Primary
Agent routing boundary.

## Scope

The implementation lives in `agentic-state-tools` and exposes a small
`StateStore` protocol with these operations:

- append an event with expected revision and etag
- read a snapshot and its revision/etag
- acquire, heartbeat, and release a task/file/resource lock

The reference adapter is a file-backed store outside the project `.agent/`
directory. It provides deterministic multi-writer tests without requiring a
network service. An HTTP JSON transport implements the same client contract for
real remote deployments, but the runtime does not silently switch to it.

## Concurrency Contract

Every event append includes a stable event ID. The store compares expected
revision and etag before writing. Repeating the same event ID with the same
payload is an idempotent read-after-write result; reusing it with different
content is an event conflict. A newer revision produces a structured conflict
that the caller must reconcile.

Locks include `owner_id`, `run_id`, `lock_id`, `fencing_token`, and lease
timestamps. Heartbeat and release require matching owner/run/token identity.
Expired locks may be replaced only through an explicit reclaim operation and
the replacement receives a higher fencing token. Stale owners therefore cannot
successfully heartbeat or release the new lease.

## Network Uncertainty

The HTTP client assigns an operation ID and idempotency key to each mutation.
Transport timeouts, connection resets, and invalid response framing become
`NETWORK_UNCERTAIN` with the operation ID and a reconcile endpoint. The client
does not retry mutations automatically. The file adapter uses the same error
classification for malformed or unavailable store files where the outcome of a
write cannot be established.

## Verification

Tests cover revision/etag conflicts, idempotent and conflicting event IDs,
owner-bound heartbeat/release, fencing-token replacement, malformed store
state, network uncertainty classification, and parity between file-store
replay and the local runtime event model. All contracts are JSON-schema
validated and the existing release suite remains required.
