import copy
import unittest

from pathlib import Path
import sys


SCRIPT_ROOT = Path(__file__).resolve().parents[2] / "skills" / "agentic-state-tools" / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from review_contract import (  # noqa: E402
    REVIEW_STAGES,
    canonical_artifact_hash,
    required_review_stages,
    validate_artifact_identity,
    validate_final_review_stages,
    validate_stage_chain,
)


def identity(task_revision=4):
    value = {
        "task_id": "TASK-1",
        "task_revision": task_revision,
        "run_id": "RUN-1",
        "attempt_id": "ATT-1",
        "dispatch_id": "DSP-1",
        "workspace_hash": "a" * 64,
    }
    value["artifact_hash"] = canonical_artifact_hash(value)
    return value


class TwoStageReviewContractTests(unittest.TestCase):
    def test_profiles_define_final_stage_requirements(self):
        self.assertEqual(required_review_stages("quick_change"), ("SPEC_COMPLIANCE",))
        self.assertEqual(required_review_stages("production"), REVIEW_STAGES)

    def test_quality_stage_requires_passing_spec_and_same_identity(self):
        spec = {
            "review_id": "REV-SPEC",
            "stage": "SPEC_COMPLIANCE",
            "verdict": "PASS",
            "artifact_identity": identity(),
        }
        quality = {
            "review_id": "REV-QUALITY",
            "stage": "CODE_QUALITY",
            "verdict": "PASS",
            "artifact_identity": identity(),
            "previous_review_id": "REV-SPEC",
            "previous_stage": "SPEC_COMPLIANCE",
            "previous_artifact_identity": identity(),
        }
        validate_stage_chain(quality, spec, profile_id="production")
        changed = copy.deepcopy(quality)
        changed["artifact_identity"] = identity(task_revision=5)
        with self.assertRaisesRegex(ValueError, "artifact identity"):
            validate_stage_chain(changed, spec, profile_id="production")

    def test_quality_stage_cannot_bypass_specification(self):
        quality = {
            "review_id": "REV-QUALITY",
            "stage": "CODE_QUALITY",
            "verdict": "PASS",
            "artifact_identity": identity(),
            "previous_review_id": "REV-SPEC",
            "previous_stage": "SPEC_COMPLIANCE",
            "previous_artifact_identity": identity(),
        }
        with self.assertRaisesRegex(ValueError, "passing SPEC_COMPLIANCE"):
            validate_stage_chain(quality, {"stage": "SPEC_COMPLIANCE", "verdict": "REPAIR_REQUIRED", "review_id": "REV-SPEC", "artifact_identity": identity()}, profile_id="production")

    def test_batch_final_stage_is_profile_aware(self):
        spec = {"stage": "SPEC_COMPLIANCE", "verdict": "PASS", "artifact_identity": identity()}
        quality = {
            "stage": "CODE_QUALITY",
            "verdict": "PASS",
            "artifact_identity": identity(),
            "previous_review_id": "REV-SPEC",
            "previous_stage": "SPEC_COMPLIANCE",
            "previous_artifact_identity": identity(),
        }
        validate_final_review_stages([spec], profile_id="quick_change")
        with self.assertRaisesRegex(ValueError, "final CODE_QUALITY"):
            validate_final_review_stages([spec], profile_id="production")
        validate_final_review_stages([quality], profile_id="production")

    def test_batch_final_stage_can_require_a_persisted_predecessor(self):
        spec = {
            "review_id": "REV-SPEC",
            "stage": "SPEC_COMPLIANCE",
            "verdict": "PASS",
            "artifact_identity": identity(),
        }
        quality = {
            "review_id": "REV-QUALITY",
            "stage": "CODE_QUALITY",
            "verdict": "PASS",
            "artifact_identity": identity(),
            "previous_review_id": "REV-SPEC",
            "previous_stage": "SPEC_COMPLIANCE",
            "previous_artifact_identity": identity(),
        }
        validate_final_review_stages(
            [quality],
            profile_id="production",
            review_index={"REV-SPEC": spec, "REV-QUALITY": quality},
        )
        with self.assertRaisesRegex(ValueError, "predecessor is missing"):
            validate_final_review_stages(
                [quality],
                profile_id="production",
                review_index={"REV-QUALITY": quality},
            )

    def test_artifact_hash_is_self_consistent(self):
        value = identity()
        validate_artifact_identity(value)
        value["workspace_hash"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "artifact_hash"):
            validate_artifact_identity(value)


if __name__ == "__main__":
    unittest.main()
