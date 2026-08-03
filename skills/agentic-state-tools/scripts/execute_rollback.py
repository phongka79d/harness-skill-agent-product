"""Record provider-confirmed compensation outcomes after exact approval."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from append_event import append_event_for_root
from distributed_store import FileStateStore, OwnershipConflict
from render_checklist import render_checklist_for_root
from rollback import FencingConflict, execute_rollback, rollback_evidence
from runtime_utils import RuntimeLockedError, RuntimeNotInitializedError, read_object, read_payload, runtime_lock
from write_artifact import write_validated


SKILL_ROOT = Path(__file__).resolve().parents[1]
PLAN_SCHEMA = SKILL_ROOT / "schemas/rollback-plan.schema.json"
LEDGER_SCHEMA = SKILL_ROOT / "schemas/rollback-ledger.schema.json"
EVIDENCE_SCHEMA = SKILL_ROOT / "schemas/rollback-evidence.schema.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--outcomes", required=True)
    parser.add_argument("--remote-store")
    parser.add_argument("--actor", default="primary-agent")
    args = parser.parse_args()
    try:
        with runtime_lock(args.project_root) as root:
            plan = read_object(root / "recovery" / f"rollback-plan-{args.plan_id}.json")
            approval = read_payload(args.approval)
            outcomes = read_payload(args.outcomes)
            fencing_store = FileStateStore(args.remote_store) if args.remote_store else None

            def fencing_validator(action: dict[str, object]) -> None:
                fencing = action.get("fencing")
                if not isinstance(fencing, dict) or fencing_store is None:
                    return
                try:
                    fencing_store.validate_fencing_token(
                        str(fencing["kind"]),
                        str(fencing["key"]),
                        str(fencing["owner_id"]),
                        str(fencing["run_id"]),
                        int(fencing["fencing_token"]),
                    )
                except (KeyError, TypeError, ValueError, OwnershipConflict) as exc:
                    raise FencingConflict(str(exc)) from exc

            ledger = execute_rollback(plan, approval, outcomes, fencing_validator=fencing_validator)
            evidence = rollback_evidence(ledger)
            ledger_relative = f"recovery/rollback-ledger-{ledger['ledger_id']}.json"
            evidence_relative = f"recovery/rollback-evidence-{evidence['evidence_id']}.json"
            if (root / ledger_relative).exists() or (root / evidence_relative).exists():
                raise ValueError(f"rollback ledger already exists: {ledger['ledger_id']}")
            ledger_output = write_validated(args.project_root, ledger_relative, ledger, LEDGER_SCHEMA)
            evidence_output = write_validated(args.project_root, evidence_relative, evidence, EVIDENCE_SCHEMA)
            append_event_for_root(
                root,
                {
                    "type": "COMPENSATION_RECORDED",
                    "actor": args.actor,
                    "task_id": plan["task_id"],
                    "data": {"plan_id": plan["plan_id"], "ledger_id": ledger["ledger_id"], "classification": ledger["classification"], "evidence_id": evidence["evidence_id"]},
                },
            )
            if ledger["status"] == "ESCALATED":
                append_event_for_root(
                    root,
                    {
                        "type": "ROLLBACK_ESCALATED",
                        "actor": args.actor,
                        "task_id": plan["task_id"],
                        "data": {"plan_id": plan["plan_id"], "ledger_id": ledger["ledger_id"], "classification": ledger["classification"], "next_action": ledger["next_action"]},
                    },
                )
            render_checklist_for_root(root)
    except RuntimeNotInitializedError as exc:
        print(f"ROLLBACK_BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (RuntimeLockedError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"ROLLBACK_REJECTED: {exc}", file=sys.stderr)
        return 1
    print(f"ROLLBACK_LEDGER_WRITTEN: {ledger_output}")
    print(f"ROLLBACK_EVIDENCE_WRITTEN: {evidence_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
