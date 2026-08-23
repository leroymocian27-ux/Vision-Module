from __future__ import annotations

import unittest

import numpy as np

from app.events.evidence import EvidencePackageBuilder
from app.events.ring_frame_buffer import KeyframeSelection, RingFrame
from app.events.schemas import FallEventRecord


class EvidencePackageBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.event = FallEventRecord(
            incident_id="incident-1",
            camera_id="camera_01",
            track_id=3,
            event_type="fall_candidate",
            fall_state="fallen_candidate",
            risk_level="high",
            trigger_frame_seq=10,
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            bbox=[1.0, 2.0, 3.0, 4.0],
        )

    def test_builds_complete_serializable_package(self) -> None:
        frame = RingFrame("camera_01", 10, self.event.trigger_timestamp, np.zeros((2, 2, 3), dtype=np.uint8))
        evidence = EvidencePackageBuilder().build(
            self.event,
            [KeyframeSelection("trigger", 0, frame)],
            feature_json={"fall_state_sequence": ["falling", "fallen_candidate"]},
            fusion_debug={"evidence_sources": ["fall_hint", "temporal"]},
        )

        self.assertEqual(evidence.keyframes[0].frame_seq, 10)
        self.assertEqual(evidence.fall_state_sequence[-1], "fallen_candidate")
        self.assertEqual(evidence.degradation_used, [])
        self.assertTrue(evidence.model_dump_json())

    def test_missing_frame_creates_degraded_package(self) -> None:
        evidence = EvidencePackageBuilder().build(
            self.event,
            [KeyframeSelection("pre_context", -3000, None, "no_frame_near_target")],
        )

        self.assertEqual(evidence.keyframes[0].missing_reason, "no_frame_near_target")
        self.assertIn("missing_pre_context_-3000ms", evidence.degradation_used)
