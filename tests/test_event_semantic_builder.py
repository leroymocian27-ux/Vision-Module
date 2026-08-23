from __future__ import annotations

import unittest

from app.events.semantic_builder import EventSemanticBuilder
from app.events.schemas import EvidencePackage, FallEventRecord


class EventSemanticBuilderTest(unittest.TestCase):
    def _event(self, state: str, adl: float = 0.1) -> FallEventRecord:
        return FallEventRecord(
            incident_id="incident-1",
            camera_id="camera_01",
            track_id=3,
            event_type="fallen_confirmed" if state == "fallen_confirmed" else "fall_candidate",
            fall_state=state,
            risk_level="critical" if state == "fallen_confirmed" else "high",
            risk_score=0.82,
            fall_probability=0.76,
            fall_evidence_score=0.84,
            adl_suppression_score=adl,
            trigger_timestamp="2026-07-17T09:30:00+00:00",
        )

    def test_candidate_with_strong_evidence_needs_attention(self) -> None:
        event = self._event("fallen_candidate")
        evidence = EvidencePackage(incident_id=event.incident_id, camera_id=event.camera_id, trigger_timestamp=event.trigger_timestamp)
        result = EventSemanticBuilder({"camera_01": {"scene_type": "living_room", "location_hint": "floor_area"}}).build(
            event,
            evidence,
            features={"motion": {"tracking_stable": True, "rapid_descent": True}},
            temporal={"post_event_stillness_ms": 3200},
        )

        self.assertEqual(result.scene["scene_type"], "living_room")
        self.assertEqual(result.risk["decision"], "need_attention")

    def test_confirmed_event_is_urgent(self) -> None:
        event = self._event("fallen_confirmed")
        evidence = EvidencePackage(incident_id=event.incident_id, camera_id=event.camera_id, trigger_timestamp=event.trigger_timestamp)

        result = EventSemanticBuilder().build(event, evidence, features={"motion": {"tracking_stable": True}})

        self.assertEqual(result.risk["decision"], "urgent_attention")

    def test_high_adl_suppression_requires_review(self) -> None:
        event = self._event("fallen_candidate", adl=0.9)
        evidence = EvidencePackage(incident_id=event.incident_id, camera_id=event.camera_id, trigger_timestamp=event.trigger_timestamp)

        result = EventSemanticBuilder().build(event, evidence, features={"motion": {"tracking_stable": True}})

        self.assertEqual(result.risk["decision"], "need_review")
