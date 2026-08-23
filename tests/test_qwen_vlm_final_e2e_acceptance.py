from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import event_api
from app.core.config import Settings
from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.pipeline import EventPipelineService
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics, FallEventRecord, TrustedEventResult
from app.events.vlm import VLMReviewInput, VLMReviewResult
from app.events.vlm_adapter import EventVLMAdapter, QwenHttpVLMReviewAdapter
from app.schemas.vision_result import DetectedObject, VisionResult


class _StaticVLM:
    def __init__(self, result: VLMReviewResult) -> None:
        self.result = result

    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage) -> VLMReviewResult:
        del semantics, evidence
        return self.result


class QwenVLMFinalE2EAcceptanceTest(unittest.TestCase):
    def test_final_e2e_vlm_disabled_uses_rule_result(self) -> None:
        pipeline = EventPipelineService(
            replace(Settings(), event_pipeline_enabled=True, event_worker_enabled=True, event_semantic_enabled=True, event_vlm_enabled=False)
        )

        pipeline.observe_result(self._vision_result(fall_state="fallen_candidate", adl_suppression_score=0.1))
        processed = pipeline.process_once("final-disabled")

        self.assertIsNone(pipeline.vlm_adapter)
        self.assertIsNotNone(processed.trusted_result)
        self.assertTrue(processed.trusted_result.support_fall_alarm)
        self.assertEqual(processed.trusted_result.review_result, "rule_only")
        self.assertNotIn("vlm_failed", processed.trusted_result.degradation_used)

    def test_final_e2e_dummy_provider_merges_explanation(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=EventVLMAdapter(provider="dummy")).analyze(self._candidate_semantics(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.review_result, "rule_with_vlm_advisory")
        self.assertIn("VLM advisory", result.explanation)
        self.assertEqual(result.vlm_provider, "dummy")
        self.assertEqual(result.adl_likelihood, "low")

    def test_final_e2e_http_provider_mock_success(self) -> None:
        adapter = EventVLMAdapter(provider="http", endpoint_url="http://mock/vlm", transport=self._success_transport("http"))

        result = adapter.analyze(self._candidate_semantics(), self._evidence())
        trusted = IntelligentAnalysisEngine(vlm_analyzer=adapter).analyze(self._candidate_semantics(), self._evidence())

        self.assertEqual(result.provider, "http")
        self.assertIsNotNone(result.latency_ms)
        self.assertEqual(trusted.vlm_provider, "http")
        self.assertTrue(trusted.support_fall_alarm)
        self.assertEqual(trusted.final_event_type, "fall_candidate")

    def test_final_e2e_qwen_http_provider_mock_success(self) -> None:
        adapter = QwenHttpVLMReviewAdapter(endpoint_url="http://mock/qwen", transport=self._success_transport("qwen_http"))

        result = adapter.analyze(self._candidate_semantics(), self._evidence())
        trusted = IntelligentAnalysisEngine(vlm_analyzer=adapter).analyze(self._candidate_semantics(), self._evidence())

        self.assertEqual(result.provider, "qwen_http")
        self.assertEqual(trusted.vlm_provider, "qwen_http")
        self.assertEqual(trusted.observed_process, "standing to low posture across timeline")

    def test_final_e2e_timeout_fallback(self) -> None:
        def transport(request: VLMReviewInput, timeout_seconds: float) -> dict:
            del request, timeout_seconds
            raise TimeoutError("slow")

        result = IntelligentAnalysisEngine(vlm_analyzer=EventVLMAdapter(provider="http_mock", transport=transport)).analyze(self._candidate_semantics(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertIn("vlm_timeout", result.degradation_used)

    def test_final_e2e_invalid_json_fallback(self) -> None:
        adapter = EventVLMAdapter(provider="http_mock", transport=lambda request, timeout: "not json")

        result = IntelligentAnalysisEngine(vlm_analyzer=adapter).analyze(self._candidate_semantics(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertIn("vlm_invalid_json", result.degradation_used)

    def test_final_e2e_confirmed_not_downgraded_by_vlm_disagree(self) -> None:
        vlm = _StaticVLM(
            VLMReviewResult(
                support_fall_alarm=False,
                semantic_event_type="fall_candidate",
                observed_process="unclear posture",
                adl_likelihood="medium",
                risk_interpretation="VLM does not strongly support fall, advisory only.",
                provider="dummy",
            )
        )

        result = IntelligentAnalysisEngine(vlm_analyzer=vlm).analyze(self._confirmed_semantics(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.final_event_type, "fallen_confirmed")
        self.assertEqual(result.final_risk_level, "critical")
        self.assertIn("vlm_disagree", result.uncertainty)
        self.assertIn("vlm_disagree", result.degradation_used)

    def test_final_e2e_candidate_high_adl_goes_review(self) -> None:
        result = IntelligentAnalysisEngine(
            vlm_analyzer=_StaticVLM(
                VLMReviewResult(
                    support_fall_alarm=True,
                    semantic_event_type="fall_candidate",
                    observed_process="person bends or sits low",
                    adl_likelihood="high",
                    risk_interpretation="ADL-like posture is plausible.",
                    provider="dummy",
                )
            )
        ).analyze(self._high_adl_semantics(), self._evidence())

        self.assertFalse(result.support_fall_alarm)
        self.assertEqual(result.final_event_type, "fall_candidate")
        self.assertIn("vlm_high_adl_likelihood", result.uncertainty)

    def test_final_e2e_missing_images_skips_vlm_safely(self) -> None:
        called = False

        def transport(request: VLMReviewInput, timeout_seconds: float) -> dict:
            nonlocal called
            called = True
            return {}

        adapter = QwenHttpVLMReviewAdapter(endpoint_url="http://mock/qwen", transport=transport)
        result = IntelligentAnalysisEngine(vlm_analyzer=adapter).analyze(
            self._candidate_semantics(),
            EvidencePackage(incident_id="final-no-image", camera_id="camera_01", trigger_timestamp="2026-07-18T09:30:00+00:00"),
        )

        self.assertFalse(called)
        self.assertTrue(result.support_fall_alarm)
        self.assertIn("vlm_skipped_no_images", result.degradation_used)

    def test_final_e2e_no_absolute_path_in_public_summary(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = EventPipelineService(
                replace(Settings(), event_pipeline_enabled=True, event_archive_enabled=True, event_archive_dir=directory, event_keyframe_serving_enabled=True)
            )
            pipeline.outbox.add_event(
                FallEventRecord(
                    incident_id="final-public-path",
                    camera_id="camera_01",
                    event_type="fall_candidate",
                    fall_state="fallen_candidate",
                    risk_level="high",
                    trigger_timestamp="2026-07-18T09:30:00+00:00",
                )
            )
            pipeline.outbox.mark_evidence_ready(
                "final-public-path",
                EvidencePackage(
                    incident_id="final-public-path",
                    camera_id="camera_01",
                    trigger_timestamp="2026-07-18T09:30:00+00:00",
                    keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path=str(Path(directory) / "keyframes" / "t0.jpg"))],
                ),
            )
            pipeline.outbox.mark_reviewed(
                "final-public-path",
                TrustedEventResult(
                    incident_id="final-public-path",
                    support_fall_alarm=True,
                    final_event_type="fall_candidate",
                    final_risk_level="high",
                    confidence=0.82,
                    explanation="rule plus advisory",
                    alarm_title="review",
                    alarm_body="body",
                    recommended_action="action",
                    review_result="rule_with_vlm_advisory",
                    vlm_provider="qwen_http",
                    vlm_latency_ms=12.5,
                    observed_process="standing to low posture",
                    risk_interpretation="advisory only",
                    adl_likelihood="low",
                ),
            )
            pipeline.outbox.mark_archive(
                "final-public-path",
                "camera_01/final-public-path",
                {
                    "archive_id": "camera_01/final-public-path",
                    "timeline_image_path": "timeline/timeline.jpg",
                    "local_path": str(Path(directory) / "camera_01" / "final-public-path"),
                },
            )
            app = FastAPI()
            app.state.runtime = SimpleNamespace(event_pipeline=pipeline)
            app.include_router(event_api.router)

            with TestClient(app) as client:
                response = client.get("/events/latest?camera_id=camera_01")

            self.assertEqual(response.status_code, 200)
            payload_text = response.text
            self.assertNotIn(str(Path(directory)), payload_text)
            self.assertNotIn("raw_response", payload_text)
            event = response.json()["event"]
            trusted = event["trusted_result"]
            self.assertEqual(trusted["vlm_provider"], "qwen_http")
            self.assertEqual(trusted["vlm_latency_ms"], 12.5)
            self.assertEqual(trusted["observed_process"], "standing to low posture")
            self.assertEqual(event["archive_summary"]["timeline_image_path"], "timeline/timeline.jpg")
            self.assertIsNone(event["archive_summary"]["local_path"])

    @staticmethod
    def _success_transport(provider: str):
        def transport(request: VLMReviewInput, timeout_seconds: float) -> dict:
            del timeout_seconds
            return {
                "schema_version": request.output_schema_version,
                "support_fall_alarm": True,
                "semantic_event_type": "fall_candidate",
                "observed_process": "standing to low posture across timeline",
                "adl_likelihood": "low",
                "uncertainty": ["mock_timeline_review"],
                "risk_interpretation": f"{provider} mock supports advisory review.",
                "alarm_title": "Advisory review",
                "alarm_body": "Review keyframes and live stream.",
                "recommended_action": "Check live stream and confirm onsite.",
            }

        return transport

    @staticmethod
    def _candidate_semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="final-candidate",
            motion={"main_transition": "standing_to_low_posture"},
            evidence={"adl_suppression_score": 0.1},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.82, "decision": "need_attention"},
        )

    @staticmethod
    def _confirmed_semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="final-confirmed",
            risk={"event_type": "fallen_confirmed", "risk_level": "critical", "confidence": 0.94, "decision": "urgent_attention"},
        )

    @staticmethod
    def _high_adl_semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="final-high-adl",
            evidence={"adl_suppression_score": 0.9},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.8, "decision": "need_review"},
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="final-candidate",
            camera_id="camera_01",
            trigger_timestamp="2026-07-18T09:30:00+00:00",
            keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path="keyframes/t0.jpg")],
            fall_probability=0.82,
            adl_suppression_score=0.1,
        )

    @staticmethod
    def _vision_result(*, fall_state: str, adl_suppression_score: float) -> VisionResult:
        return VisionResult(
            camera_id="camera_01",
            timestamp="2026-07-18T09:30:00+00:00",
            frame_seq=300,
            frame_width=640,
            frame_height=360,
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.93,
                    bbox=[100.0, 120.0, 310.0, 340.0],
                    track_id=21,
                    fall_decision={
                        "fall_state": fall_state,
                        "risk_level": "high",
                        "fall_probability": 0.82,
                        "fall_evidence_score": 0.86,
                        "adl_suppression_score": adl_suppression_score,
                    },
                    features={"motion": {"tracking_stable": True}},
                    temporal={"fall_probability": 0.82},
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
