from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_temporal_v6_residual_audit import build_residual_audit, render_markdown


class TemporalV6ResidualAuditTest(unittest.TestCase):
    def test_builds_residual_fn_categories_from_frame_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison_path = root / "comparison.json"
            manifest_path = root / "manifest.json"
            frames_dir = root / "frames"
            frames_dir.mkdir()
            comparison_path.write_text(
                json.dumps(
                    {
                        "v6_event_metrics": {
                            "fall_event_recall": 0.7,
                            "confirmed_false_positive_count": 0,
                        },
                        "duplicate_alarm_videos": [],
                        "per_video": [
                            {
                                "video": "fall-05.mp4",
                                "expected_alarm": True,
                                "v6_confirmed": False,
                                "scene_type": "floor_risk_zone",
                                "v6_block_point": "FallStateMachine",
                            },
                            {
                                "video": "fall-01.mp4",
                                "expected_alarm": True,
                                "v6_confirmed": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "videos": [
                            {
                                "path": "../../datasets/ur_fall/videos/fall-05.mp4",
                                "video_id": "ur_fall/fall-05.mp4",
                                "support_surface": "none",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (frames_dir / "offline_eval_fall-05_frames.csv").write_text(
                "\n".join(
                    [
                        "video_name,frame_index,timestamp_ms,pose_success,fall_state,v6_motion_path,v6_fall_evidence_score,v6_adl_suppression_score,v6_vertical_drop_score,v6_low_posture_score,v6_post_fall_stillness_score,v6_floor_contact_score,v6_impact_proxy_score,v6_low_posture_duration_ms,v6_track_quality_score,v6_recovery_score,v6_support_surface_score,v6_decision_reason",
                        'fall-05.mp4,16,640,True,normal,normal,0.32,0.34,0.00,0.89,0.65,0.28,0.30,0,1.0,0.0,0.02,"[""low_posture""]"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = build_residual_audit(
                comparison_path=comparison_path,
                manifest_path=manifest_path,
                frames_dir=frames_dir,
            )
            markdown = render_markdown(result)

        self.assertEqual(result["summary"]["residual_fn_count"], 1)
        self.assertEqual(result["items"][0]["video"], "fall-05.mp4")
        self.assertEqual(result["items"][0]["residual_category"], "slow_or_normal_lying_ambiguous")
        self.assertIn("fall-05.mp4", markdown)
        self.assertIn("slow_or_normal_lying_ambiguous", markdown)


if __name__ == "__main__":
    unittest.main()
