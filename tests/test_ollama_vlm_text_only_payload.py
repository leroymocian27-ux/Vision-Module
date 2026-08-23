from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics
from app.events.vlm import build_vlm_input
from app.events.vlm_adapter import VLMAdapterError, build_text_only_ollama_review_payload
from app.events.vlm_prompt import OLLAMA_QWEN_ADVISORY_PROMPT


class OllamaVLMTextOnlyPayloadTest(unittest.TestCase):
    def test_payload_excludes_media_paths_and_base64(self) -> None:
        evidence = EvidencePackage(
            incident_id="ollama-text-only",
            camera_id="camera_01",
            trigger_timestamp="2026-07-18T09:30:00+00:00",
            keyframes=[
                EvidenceKeyframe(
                    role="trigger",
                    offset_ms=0,
                    frame_seq=42,
                    fall_state="fallen_candidate",
                    image_path=r"D:\\Program\\camera-service\\logs\\event_archive\\secret.jpg",
                    snapshot_url=r"D:\\Program\\camera-service\\logs\\event_archive\\secret.jpg",
                )
            ],
            fall_probability=0.82,
            adl_suppression_score=0.1,
        )
        semantics = EventSemantics(
            incident_id="ollama-text-only",
            evidence={"adl_suppression_score": 0.1, "image_path": r"D:\\secret\\frame.jpg"},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.82, "decision": "need_attention"},
        )
        request = build_vlm_input(semantics, evidence, timeline_image_path="timeline/timeline.jpg")

        payload = build_text_only_ollama_review_payload(semantics, evidence, request, model="qwen-vision-cn:latest")
        payload_text = json.dumps(payload, ensure_ascii=False)

        self.assertIn("structured JSON only", OLLAMA_QWEN_ADVISORY_PROMPT)
        self.assertIn("not images", OLLAMA_QWEN_ADVISORY_PROMPT)
        self.assertNotIn("keyframe_image_paths", payload_text)
        self.assertNotIn("timeline_image_path", payload_text)
        self.assertNotIn("image_path", payload_text)
        self.assertNotIn("snapshot_url", payload_text)
        self.assertNotIn("D:\\", payload_text)
        self.assertNotIn("/workspace", payload_text)
        self.assertNotIn("logs/event_archive", payload_text)
        self.assertNotIn("base64", payload_text.lower())
        self.assertEqual(payload["model"], "qwen-vision-cn:latest")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["format"], "json")

    def test_payload_rejects_forbidden_path_like_semantics(self) -> None:
        semantics = EventSemantics(
            incident_id="ollama-bad-path",
            scene={"note": str(Path("D:/Program/camera-service/logs/event_archive/frame.jpg"))},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.82},
        )
        evidence = EvidencePackage(incident_id="ollama-bad-path", camera_id="camera_01", trigger_timestamp="2026-07-18T09:30:00+00:00")
        request = build_vlm_input(semantics, evidence)

        with self.assertRaises(VLMAdapterError):
            build_text_only_ollama_review_payload(semantics, evidence, request, model="qwen-vision-cn:latest")


if __name__ == "__main__":
    unittest.main()
