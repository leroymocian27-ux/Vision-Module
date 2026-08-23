from __future__ import annotations

import unittest

from app.events.schemas import (
    DeliveryRecord,
    EventOutboxRecord,
    EventSemantics,
    EvidenceKeyframe,
    EvidencePackage,
    FallEventRecord,
    TrustedEventResult,
)


class EventSchemasTest(unittest.TestCase):
    def test_event_models_serialize_to_json(self) -> None:
        event = FallEventRecord(
            incident_id="vision-fall-camera_01-track-3-20260717093000-0001",
            camera_id="camera_01",
            track_id=3,
            event_type="fall_candidate",
            fall_state="fallen_candidate",
            risk_level="high",
            risk_score=0.82,
            trigger_frame_seq=42,
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            bbox=[10.0, 20.0, 30.0, 40.0],
        )
        evidence = EvidencePackage(
            incident_id=event.incident_id,
            camera_id=event.camera_id,
            track_id=event.track_id,
            trigger_timestamp=event.trigger_timestamp,
            keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, frame_seq=42)],
        )
        semantics = EventSemantics(
            incident_id=event.incident_id,
            actor={"track_id": 3},
            risk={"event_type": "fall_candidate", "risk_level": "high"},
        )
        trusted = TrustedEventResult(
            incident_id=event.incident_id,
            support_fall_alarm=True,
            final_event_type="fall_candidate",
            final_risk_level="high",
            confidence=0.82,
            explanation="Multiple fall indicators are present.",
            alarm_title="Possible fall",
            alarm_body="A possible fall needs attention.",
            recommended_action="Review the live camera.",
        )
        delivery = DeliveryRecord(
            incident_id=event.incident_id,
            target_url="http://main.example/events",
            payload_json={"incident_id": event.incident_id},
        )
        outbox = EventOutboxRecord(event=event, evidence_package=evidence, event_semantics=semantics, trusted_result=trusted)

        self.assertEqual(outbox.model_dump_json()[:1], "{")
        self.assertEqual(delivery.model_dump(mode="json")["delivery_status"], "pending")
        self.assertEqual(outbox.incident_id, event.incident_id)
