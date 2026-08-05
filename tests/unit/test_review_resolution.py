import unittest
from pathlib import Path
import sys


SCRIPT_ROOT = Path(__file__).resolve().parents[2] / "skills" / "agentic-state-tools" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from create_review_resolution import normalize  # noqa: E402
from review_contract import canonical_artifact_hash  # noqa: E402


ARTIFACT_IDENTITY = {
    "task_id": "TASK-1",
    "task_revision": 4,
    "run_id": "RUN-1",
    "attempt_id": "ATT-1",
    "dispatch_id": "DSP-1",
    "workspace_hash": "a" * 64,
}
ARTIFACT_IDENTITY["artifact_hash"] = canonical_artifact_hash(ARTIFACT_IDENTITY)
TASK = {"task_id": "TASK-1", "run_id": "RUN-1", "attempt_id": "ATT-1", "revision": 4}
FINDING = {"severity": "MAJOR", "evidence": "bad", "required_change": "fix"}
REVIEW = {
    "task_id": "TASK-1",
    "review_id": "REV-TASK-1",
    "artifact_identity": ARTIFACT_IDENTITY,
    "findings": [FINDING],
}


def verification_blocks():
    return {
        "contract_verification": {"status": "VERIFIED", "evidence": ["Contract checked."]},
        "code_verification": {"status": "VERIFIED", "evidence": ["Current code checked."]},
        "conflict_usage_check": {"status": "CLEAR", "evidence": ["Usage checked."]},
        "ambiguity_resolution": {
            "status": "NOT_REQUIRED",
            "decision": "Finding is specific.",
            "evidence": ["No ambiguity remains."],
        },
    }


class ReviewResolutionTests(unittest.TestCase):
    def test_implementer_can_mark_fix_pending_rereview(self):
        result = normalize(
            {
                "task_id": "TASK-1",
                "artifact_identity": ARTIFACT_IDENTITY,
                "finding_id": "finding-1",
                "finding": FINDING,
                "status": "FIXED_PENDING_REREVIEW",
                "rationale": "Fixed the finding in scope.",
                "evidence": {"summary": "Checked the contract and usage."},
                "correction": {
                    "summary": "Applied the focused correction.",
                    "coherent": True,
                    "changed_files": ["skills/example.py"],
                },
                "targeted_verification": {
                    "command": "python -m unittest",
                    "exit_code": 0,
                    "status": "PASS",
                    "evidence_ids": ["VE-1"],
                },
                **verification_blocks(),
            },
            task_id="TASK-1",
            task=TASK,
            review=REVIEW,
            existing=None,
            actor="agentic-implementer",
        )
        self.assertEqual(result["status"], "FIXED_PENDING_REREVIEW")
        self.assertEqual(result["task_revision"], 4)

    def test_implementer_cannot_close_finding(self):
        with self.assertRaisesRegex(ValueError, "only a reviewer"):
            normalize(
                {
                    "task_id": "TASK-1",
                    "artifact_identity": ARTIFACT_IDENTITY,
                    "finding_id": "finding-1",
                    "finding": FINDING,
                    "status": "CLOSED",
                    "rationale": "Closed.",
                    "evidence": {"summary": "Evidence."},
                    **verification_blocks(),
                    "re_review": {"review_id": "REV-2", "evidence_ids": ["VE-2"], "result": "PASS"},
                },
                task_id="TASK-1",
                task=TASK,
                review=REVIEW,
                existing=None,
                actor="agentic-implementer",
            )

    def test_unknown_finding_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "finding does not exist"):
            normalize(
                {
                    "task_id": "TASK-1",
                    "artifact_identity": ARTIFACT_IDENTITY,
                    "finding_id": "finding-9",
                    "status": "ACCEPTED",
                    "rationale": "No.",
                    "evidence": {"summary": "No."},
                },
                task_id="TASK-1",
                task=TASK,
                review=REVIEW,
                existing=None,
                actor="agentic-implementer",
            )

    def test_artifact_identity_mismatch_is_rejected(self):
        wrong_identity = dict(ARTIFACT_IDENTITY)
        wrong_identity["workspace_hash"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "artifact identity"):
            normalize(
                {
                    "task_id": "TASK-1",
                    "artifact_identity": wrong_identity,
                    "finding_id": "finding-1",
                    "finding": FINDING,
                    "status": "ACCEPTED",
                    "rationale": "Checked.",
                    "evidence": {"summary": "Evidence."},
                    **verification_blocks(),
                },
                task_id="TASK-1",
                task=TASK,
                review=REVIEW,
                existing=None,
                actor="agentic-implementer",
            )


if __name__ == "__main__":
    unittest.main()
