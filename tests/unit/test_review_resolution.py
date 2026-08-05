import unittest
from pathlib import Path
import sys


SCRIPT_ROOT = Path(__file__).resolve().parents[2] / "skills" / "agentic-state-tools" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from create_review_resolution import normalize  # noqa: E402


TASK = {"task_id": "TASK-1", "run_id": "RUN-1", "attempt_id": "ATT-1", "revision": 4}
REVIEW = {
    "review_id": "REV-TASK-1",
    "findings": [{"severity": "MAJOR", "evidence": "bad", "required_change": "fix", "resolved": False}],
}


class ReviewResolutionTests(unittest.TestCase):
    def test_implementer_can_mark_fix_pending_rereview(self):
        result = normalize(
            {
                "finding_id": "finding-1",
                "status": "FIXED_PENDING_REREVIEW",
                "rationale": "Fixed the finding in scope.",
                "evidence": {"summary": "Checked the contract and usage."},
                "correction": {"summary": "Applied the focused correction."},
                "verification": {"command": "python -m unittest", "exit_code": 0, "status": "PASS"},
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
                    "finding_id": "finding-1",
                    "status": "CLOSED",
                    "rationale": "Closed.",
                    "evidence": {"summary": "Evidence."},
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
                {"finding_id": "finding-9", "status": "ACCEPTED", "rationale": "No.", "evidence": {"summary": "No."}},
                task_id="TASK-1",
                task=TASK,
                review=REVIEW,
                existing=None,
                actor="agentic-implementer",
            )


if __name__ == "__main__":
    unittest.main()
