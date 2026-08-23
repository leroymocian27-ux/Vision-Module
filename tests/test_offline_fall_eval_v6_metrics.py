from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_fall_video_offline import VideoSummary, build_event_metrics, load_v6_frame_metrics


class OfflineFallEvalV6MetricsTest(unittest.TestCase):
    def test_v6_frame_metrics_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            frames = output_dir / "offline_eval_case_01_frames.jsonl"
            rows = [
                {
                    "v6_motion_path": "adl_suppressed",
                    "v6_decision_reason": json.dumps(["bending_like_motion", "controlled_descent"]),
                    "v6_suppressed_by_adl": True,
                    "v6_uncertain_review": False,
                    "v6_fall_latched": False,
                },
                {
                    "v6_motion_path": "slow_fall_path",
                    "v6_decision_reason": json.dumps(["floor_contact_likely"]),
                    "v6_suppressed_by_adl": False,
                    "v6_uncertain_review": False,
                    "v6_fall_latched": True,
                },
            ]
            frames.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            summary = self._summary("case_01.mp4", expected_alarm=False, confirmed_frames=0)

            frame_metrics = load_v6_frame_metrics(summary, output_dir)
            event_metrics = build_event_metrics([summary], output_dir)

            self.assertEqual(frame_metrics["motion_paths"]["adl_suppressed"], 1)
            self.assertEqual(frame_metrics["motion_paths"]["slow_fall_path"], 1)
            self.assertEqual(frame_metrics["decision_reasons"]["bending_like_motion"], 1)
            self.assertEqual(frame_metrics["adl_suppressed_frames"], 1)
            self.assertEqual(frame_metrics["fall_latched_frames"], 1)
            self.assertEqual(event_metrics["v6"]["motion_path_distribution"]["slow_fall_path"], 1)
            self.assertEqual(event_metrics["v6"]["adl_suppressed_frames"], 1)

    @staticmethod
    def _summary(video: str, *, expected_alarm: bool, confirmed_frames: int) -> VideoSummary:
        return VideoSummary(
            video=video,
            frame_count=2,
            processed_frames=2,
            fps=25.0,
            duration_ms=80,
            person_detection="OK",
            tracking="OK",
            pose="OK",
            fall_confirm="OK" if confirmed_frames else "FAIL",
            incident_id=None,
            block_point="FallStateMachine",
            fall_state_peak="normal",
            max_person_count=1,
            max_tracked_objects=1,
            pose_success_frames=2,
            alarm_confirmed_frames=0,
            confirmed_frames=confirmed_frames,
            first_confirmed_frame=None,
            first_confirmed_timestamp_ms=None,
            first_incident_id_frame=None,
            snapshot_path=None,
            snapshot_url=None,
            latest_result_consumable=False,
            manifest_label="fall" if expected_alarm else "non_fall",
            expected_alarm=expected_alarm,
        )


if __name__ == "__main__":
    unittest.main()
