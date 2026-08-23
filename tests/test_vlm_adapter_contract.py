from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.pipeline import EventPipelineService
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics
from app.events.vlm import VLMInput, VLMOutput, build_vlm_input
from app.events.vlm_adapter import EventVLMAdapter, InvalidVLMOutput, VLMAdapterTimeout


class _FailingVLM:
    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage):
        del semantics, evidence
        raise TimeoutError("vlm timed out")


class VLMAdapterContractTest(unittest.TestCase):
    def test_build_vlm_input_contains_stable_contract_fields(self) -> None:
        request = build_vlm_input(self._semantics(), self._evidence(), prompt_version="fall_event_vlm_prompt.v2")

        self.assertIsInstance(request, VLMInput)
        self.assertEqual(request.incident_id, "incident-1")
        self.assertEqual(request.camera_id, "camera_01")
        self.assertEqual(request.keyframe_image_paths, ["C:/events/incident-1/trigger.jpg"])
        self.assertIsNone(request.timeline_image_path)
        self.assertEqual(request.event_semantics["risk"]["event_type"], "fall_candidate")
        self.assertIn("fall_probability", request.feature_json)
        self.assertIn("keyframes", request.evidence_summary)
        self.assertEqual(request.output_schema_version, "vlm_review_result_v1")
        self.assertEqual(request.prompt_version, "fall_event_vlm_prompt.v2")

    def test_disabled_provider_returns_none(self) -> None:
        adapter = EventVLMAdapter(provider="disabled")

        self.assertIsNone(adapter.analyze(self._semantics(), self._evidence()))

    def test_dummy_provider_returns_output_protocol(self) -> None:
        adapter = EventVLMAdapter(provider="dummy")

        result = adapter.analyze(self._semantics(), self._evidence())

        self.assertIsInstance(result, VLMOutput)
        self.assertEqual(result.semantic_event_type, "fall_candidate")
        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.adl_likelihood, "low")
        self.assertEqual(result.provider, "dummy")
        self.assertIn("dummy", result.observed_process)

    def test_http_mock_provider_uses_transport_and_validates_output(self) -> None:
        calls: list[dict] = []

        def transport(request: VLMInput, timeout_seconds: float) -> dict:
            calls.append({"request": request, "timeout_seconds": timeout_seconds})
            return {
                "support_fall_alarm": True,
                "semantic_event_type": "fall_candidate",
                "observed_process": "standing_to_floor",
                "adl_likelihood": "low",
                "uncertainty": ["one_keyframe_missing"],
                "risk_interpretation": "fall-like motion with low ADL likelihood",
                "alarm_title": "Possible fall",
                "alarm_body": "Review keyframes and live video.",
                "recommended_action": "Check the live stream.",
                "provider": "http_mock",
            }

        adapter = EventVLMAdapter(provider="http_mock", timeout_seconds=1.25, transport=transport)

        result = adapter.analyze(self._semantics(), self._evidence())

        self.assertEqual(calls[0]["request"].incident_id, "incident-1")
        self.assertEqual(calls[0]["timeout_seconds"], 1.25)
        self.assertEqual(result.observed_process, "standing_to_floor")
        self.assertEqual(result.provider, "http_mock")

    def test_http_mock_invalid_output_is_rejected(self) -> None:
        adapter = EventVLMAdapter(provider="http_mock", transport=lambda request, timeout: {"adl_likelihood": "impossible"})

        with self.assertRaises(InvalidVLMOutput):
            adapter.analyze(self._semantics(), self._evidence())

    def test_http_mock_timeout_is_reported_as_adapter_timeout(self) -> None:
        def transport(request: VLMInput, timeout_seconds: float) -> dict:
            del request, timeout_seconds
            raise TimeoutError("slow mock")

        adapter = EventVLMAdapter(provider="http_mock", transport=transport)

        with self.assertRaises(VLMAdapterTimeout):
            adapter.analyze(self._semantics(), self._evidence())

    def test_engine_falls_back_to_rule_analyzer_when_vlm_fails(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_FailingVLM()).analyze(self._semantics(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.review_result, "rule_only")
        self.assertIn("vlm_failed", result.degradation_used)

    def test_event_vlm_disabled_in_settings_does_not_create_adapter(self) -> None:
        pipeline = EventPipelineService(
            replace(Settings(), event_pipeline_enabled=True, event_semantic_enabled=True, event_vlm_enabled=False)
        )

        self.assertIsNone(pipeline.vlm_adapter)

    @staticmethod
    def _semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="incident-1",
            motion={"main_transition": "standing_to_low_posture"},
            evidence={"adl_suppression_score": 0.1},
            risk={
                "event_type": "fall_candidate",
                "risk_level": "high",
                "confidence": 0.82,
                "decision": "need_attention",
                "advice": "Review live stream.",
            },
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="incident-1",
            camera_id="camera_01",
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            keyframes=[
                EvidenceKeyframe(
                    role="trigger",
                    offset_ms=0,
                    frame_seq=42,
                    timestamp="2026-07-17T09:30:00+00:00",
                    image_path="C:/events/incident-1/trigger.jpg",
                )
            ],
            fall_probability=0.82,
            fall_evidence_score=0.86,
            adl_suppression_score=0.1,
            fusion_debug={"source": "unit_test"},
        )
