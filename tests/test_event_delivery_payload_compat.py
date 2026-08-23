from __future__ import annotations

import unittest

from app.events.delivery import build_main_system_payload
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics, QwenKeyframeAdvisory, TrustedEventResult


class EventDeliveryPayloadCompatTest(unittest.TestCase):
    def test_payload_contains_main_system_fall_alert_contract_fields(self) -> None:
        payload = build_main_system_payload(
            self._trusted("critical", final_event_type="fallen_confirmed"),
            self._evidence(),
            EventSemantics(incident_id="incident-compat", uncertainty=["low_light"]),
        )

        self.assertEqual(payload["incident_id"], "incident-compat")
        self.assertEqual(payload["camera_id"], "camera_01")
        self.assertEqual(payload["event_type"], "fall_confirmed")
        self.assertEqual(payload["state"], "fallen_confirmed")
        self.assertEqual(payload["status"], "confirmed_fall")
        self.assertEqual(payload["severity"], "L3")
        self.assertEqual(payload["risk"], "critical")
        self.assertEqual(payload["risk_level"], "critical")
        self.assertTrue(payload["fall_detected"])
        self.assertEqual(payload["fall_prob"], 0.91)
        self.assertEqual(payload["fall_score"], 0.94)
        self.assertEqual(payload["track_id"], "42")
        self.assertEqual(payload["bbox"], [10.0, 20.0, 110.0, 220.0])
        self.assertEqual(payload["snapshot_url"], "http://testserver/fall-events/snapshots/incident-compat.jpg")
        self.assertEqual(payload["timestamp"], "2026-07-17T09:30:00+00:00")
        self.assertEqual(payload["injury"]["level"], "I3")
        self.assertEqual(payload["injury"]["reason"], "vision_service_fallen_confirmed")
        self.assertEqual(payload["injury"]["advice"], "Check the live camera immediately.")
        self.assertEqual(payload["explanation"], "confirmed by event semantics")
        self.assertEqual(payload["recommended_action"], "Check the live camera immediately.")
        self.assertEqual(payload["delivery_mode"], "dry_run")
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["review_result"], "rule_only")
        self.assertEqual(payload["degradation_used"], [])

    def test_risk_level_maps_to_main_system_severity_and_injury_level(self) -> None:
        expected = {
            "critical": ("L3", "I3"),
            "high": ("L2", "I2"),
            "medium": ("L1", "I1"),
            "low": ("L0", "I0"),
        }
        for risk, (severity, injury_level) in expected.items():
            with self.subTest(risk=risk):
                payload = build_main_system_payload(self._trusted(risk), self._evidence())
                self.assertEqual(payload["severity"], severity)
                self.assertEqual(payload["injury"]["level"], injury_level)

    def test_candidate_payload_keeps_candidate_status_but_uses_same_field_names(self) -> None:
        payload = build_main_system_payload(
            self._trusted("high", final_event_type="fall_candidate", support=False),
            self._evidence(),
        )

        self.assertEqual(payload["event_type"], "fall_candidate")
        self.assertEqual(payload["state"], "fallen_candidate")
        self.assertEqual(payload["status"], "fall_candidate")
        self.assertFalse(payload["fall_detected"])
        self.assertEqual(payload["severity"], "L2")
        self.assertEqual(payload["injury"]["level"], "I2")

    def test_review_payload_does_not_pretend_to_be_confirmed(self) -> None:
        payload = build_main_system_payload(
            self._trusted("medium", final_event_type="need_review", support=False),
            self._evidence(),
        )

        self.assertEqual(payload["event_type"], "fall_review_required")
        self.assertEqual(payload["state"], "need_review")
        self.assertEqual(payload["status"], "review_required")
        self.assertFalse(payload["fall_detected"])
        self.assertEqual(payload["severity"], "L1")
        self.assertEqual(payload["injury"]["level"], "I1")

    def test_snapshot_url_does_not_expose_local_absolute_path(self) -> None:
        evidence = EvidencePackage(
            incident_id="incident-compat",
            camera_id="camera_01",
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            keyframes=[
                EvidenceKeyframe(
                    role="trigger",
                    offset_ms=0,
                    snapshot_url="D:\\Program\\camera-service\\camera_79\\logs\\event.jpg",
                )
            ],
        )

        payload = build_main_system_payload(self._trusted("medium"), evidence)

        self.assertIsNone(payload["snapshot_url"])
        self.assertNotIn("D:\\", str(payload))

    def test_completed_qwen_keyframe_advisory_is_additive_and_path_free(self) -> None:
        advisory = QwenKeyframeAdvisory(
            analysis_status="completed",
            model_name="qwen-vision-cn:latest",
            image_count=3,
            scene_summary="人员处于低姿态。",
            posture_description="疑似侧卧。",
            movement_description="低运动。",
            care_advice=["人工复核。"],
            advisory_confidence="medium",
        )
        payload = build_main_system_payload(self._trusted("critical"), self._evidence(), qwen_advisory=advisory)
        summary = payload["metadata"]["semantic_analysis"]["qwen_keyframe_advisory"]
        self.assertTrue(summary["advisory_only"])
        self.assertEqual(summary["analysis_status"], "completed")
        self.assertEqual(summary["image_count"], 3)
        self.assertNotIn("image_path", str(summary))
        self.assertNotIn("archive_path", str(summary))

    @staticmethod
    def _trusted(risk: str, *, final_event_type: str = "fallen_confirmed", support: bool = True) -> TrustedEventResult:
        return TrustedEventResult(
            incident_id="incident-compat",
            support_fall_alarm=support,
            final_event_type=final_event_type,
            final_risk_level=risk,  # type: ignore[arg-type]
            confidence=0.9,
            explanation="confirmed by event semantics",
            alarm_title="Fall alert",
            alarm_body="A fall was detected.",
            recommended_action="Check the live camera immediately.",
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="incident-compat",
            camera_id="camera_01",
            track_id=42,
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            fall_probability=0.91,
            fall_evidence_score=0.94,
            keyframes=[
                EvidenceKeyframe(
                    role="trigger",
                    offset_ms=0,
                    bbox=[10.0, 20.0, 110.0, 220.0],
                    snapshot_url="http://testserver/fall-events/snapshots/incident-compat.jpg",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
