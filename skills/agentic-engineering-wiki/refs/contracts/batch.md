# Batch Contract

Policy status: ENFORCED (enforced by `skills/agentic-state-tools/scripts/create_batch_contract.py`)

The Primary Agent creates the canonical batch pin with:

```text
python scripts/create_batch_contract.py --project-root <project> --plan <approved-plan.json> --plan-id <id> --plan-revision <n> --batch-id <id> --expected-revision <n> --actor primary-agent
```

The writer resolves the approved plan, exact task membership, task revisions,
review-contract pins, rubric ID/version/hash, plan hash, and plan approval. It
writes `.agent/work/<batch-id>/batch-contract.json` atomically and records the
operation. Direct normal writes are not a supported creation path.

`create_batch_review.py` and `commit_batch.py` require the current contract
revision and hash. A stale contract, changed plan, missing task, or mismatched
review contract blocks the batch. Every expected task review appears exactly
once, and every task must already be accepted before a batch can pass.

Distributed batch coordination and remote writers are NOT_IMPLEMENTED; the
release surface is the local script-owned contract and its release tests.
