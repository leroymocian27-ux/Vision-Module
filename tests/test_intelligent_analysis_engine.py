from __future__ import annotations

import unittest

from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.schemas import EvidencePackage, EventSemantics


class IntelligentAnalysisEngineTest(unittest.TestCase):
    def _evidence(self) -> EvidencePackage:
        return EvidencePackage(
            incident_id="incident-1",
            camera_id="camera_01",
            trigger_timestamp="2026-07-17T09:30:00+00:00",
        )

    def test_confirmed_event_remains_supported(self) -> None:
        semantics = EventSemantics(
            incident_id="incident-1",
            risk={"event_type": "fallen_confirmed", "risk_level": "critical", "confidence": 0.9, "decision": "urgent_attention"},
        )

        result = IntelligentAnalysisEngine().analyze(semantics, self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.final_risk_level, "critical")

    def test_candidate_with_strong_evidence_is_supported(self) -> None:
        semantics = EventSemantics(
            incident_id="incident-1",
            evidence={"adl_suppression_score": 0.1},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.82, "decision": "need_attention"},
        )

        result = IntelligentAnalysisEngine().analyze(semantics, self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.final_risk_level, "high")

    def test_adl_suppressed_candidate_requires_review(self) -> None:
        semantics = EventSemantics(
            incident_id="incident-1",
            evidence={"adl_suppression_score": 0.9},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.82, "decision": "need_review"},
        )

        result = IntelligentAnalysisEngine().analyze(semantics, self._evidence())

        self.assertFalse(result.support_fall_alarm)
        self.assertIn("复核", result.alarm_title)
