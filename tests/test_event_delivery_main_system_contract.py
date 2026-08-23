from __future__ import annotations

import unittest

from app.events.delivery import build_main_system_payload
from app.events.schemas import EvidenceKeyframe, EvidencePackage, TrustedEventResult


class EventDeliveryMainSystemContractTest(unittest.TestCase):
    def test_confirmed_candidate_and_review_payloads_match_documented_contract(self) -> None:
        cases = [
            ("fallen_confirmed", "critical", True, "fall_confirmed", "fallen_confirmed", "confirmed_fall", "L3", "I3"),
            ("fall_candidate", "high", False, "fall_candidate", "fallen_candidate", "fall_candidate", "L2", "I2"),
            ("need_review", "medium", False, "fall_review_required", "need_review", "review_required", "L1", "I1"),
        ]
        required = {
            "incident_id",
            "camera_id",
            "stream_name",
            "source",
            "event_type",
            "state",
            "status",
            "severity",
            "risk",
            "risk_level",
            "fall_detected",
            "fall_prob",
            "fall_score",
            "track_id",
            "bbox",
            "snapshot_url",
            "timestamp",
            "injury",
            "explanation",
            "recommended_action",
            "delivery_mode",
            "dry_run",
            "degradation_used",
            "review_result",
        }
        for final_event_type, risk, support, event_type, state, status, severity, injury_level in cases:
            with self.subTest(final_event_type=final_event_type):
                payload = build_main_system_payload(
                    self._trusted(final_event_type, risk, support),
                    self._evidence(),
                )
                self.assertTrue(required.issubset(payload))
                self.assertEqual(payload["event_type"], event_type)
                self.assertEqual(payload["state"], state)
                self.assertEqual(payload["status"], status)
                self.assertEqual(payload["severity"], severity)
                self.assertEqual(payload["injury"]["level"], injury_level)
                self.assertNotIn("D:\\", str(payload))

    @staticmethod
    def _trusted(final_event_type: str, risk: str, support: bool) -> TrustedEventResult:
        return TrustedEventResult(
            incident_id=f"contract-{final_event_type}",
            support_fall_alarm=support,
            final_event_type=final_event_type,
            final_risk_level=risk,  # type: ignore[arg-type]
            confidence=0.88,
            explanation="contract explanation",
            alarm_title="fall",
            alarm_body="fall",
            recommended_action="contract action",
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="contract",
            camera_id="camera_01",
            track_id=3,
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            fall_probability=0.87,
            fall_evidence_score=0.89,
            keyframes=[
                EvidenceKeyframe(
                    role="trigger",
                    offset_ms=0,
                    bbox=[1.0, 2.0, 3.0, 4.0],
                    snapshot_url="http://testserver/fall-events/snapshots/contract.jpg",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
