from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings


class PipelineModeConfigTest(unittest.TestCase):
    def test_legacy_mode_requires_detection_service_fall_hint_writer(self) -> None:
        settings = replace(
            Settings(),
            pipeline_mode="legacy",
            fall_hint_in_detection_service=True,
            fall_hint_worker_enabled=False,
        )

        self.assertEqual(settings.pipeline_mode, "legacy")

        with self.assertRaises(ValueError):
            replace(settings, fall_hint_worker_enabled=True)

    def test_async_v1_mode_requires_worker_fall_hint_writer(self) -> None:
        settings = replace(
            Settings(),
            pipeline_mode="async_v1",
            fall_hint_in_detection_service=False,
            fall_hint_worker_enabled=True,
        )

        self.assertEqual(settings.pipeline_mode, "async_v1")

        with self.assertRaises(ValueError):
            replace(settings, fall_hint_in_detection_service=True)

    def test_fall_disabled_mode_requires_all_fall_hint_paths_off(self) -> None:
        settings = replace(
            Settings(),
            pipeline_mode="fall_disabled",
            fall_hint_in_detection_service=False,
            fall_hint_worker_enabled=False,
            fall_detector_enabled=False,
        )

        self.assertEqual(settings.pipeline_mode, "fall_disabled")

        with self.assertRaises(ValueError):
            replace(settings, fall_hint_worker_enabled=True)

        with self.assertRaises(ValueError):
            replace(settings, fall_detector_enabled=True)

    def test_post_fall_v2_mode_enables_binary_first_runtime_without_legacy_requirements(self) -> None:
        settings = replace(
            Settings(),
            pipeline_mode="post_fall_v2",
            post_fall_v2_enabled=True,
            fall_hint_in_detection_service=True,
            fall_hint_worker_enabled=False,
            fall_detector_enabled=True,
        )

        self.assertEqual(settings.pipeline_mode, "post_fall_v2")
        self.assertTrue(settings.post_fall_v2_enabled)

        with self.assertRaises(ValueError):
            replace(settings, post_fall_v2_enabled=False)

    def test_post_fall_v2_low_latency_vlm_flow_defaults(self) -> None:
        settings = Settings()

        self.assertEqual(settings.post_fall_v2_sample_fps, 10)
        self.assertEqual(settings.post_fall_v2_event_buffer_seconds, 1)
        self.assertEqual(settings.post_fall_v2_min_positive_frames, 1)
        self.assertEqual(settings.post_fall_v2_min_consecutive_frames, 1)
        self.assertEqual(settings.post_fall_v2_candidate_min_ms, 0)
        self.assertEqual(settings.event_keyframe_offsets_ms, (-1000, -500, 0))
        self.assertEqual(settings.post_fall_v2_qwen_max_images, 3)
        self.assertEqual(settings.post_fall_v2_qwen_profile, "qwen4b_stable_v1")
        self.assertEqual(settings.post_fall_v2_qwen_model, "qwen3.5:4b")
        self.assertEqual(settings.post_fall_v2_qwen_prompt_version, "compact_v2")
        self.assertEqual(settings.post_fall_v2_qwen_schema_version, "compact_v1")
        self.assertEqual(settings.post_fall_v2_qwen_fusion_version, "demo_fusion_v2")
        self.assertEqual(settings.post_fall_v2_qwen_image_max_edge, 384)
        self.assertEqual(settings.post_fall_v2_qwen_jpeg_quality, 86)
        self.assertEqual(settings.post_fall_v2_qwen_max_output_tokens, 96)
        self.assertEqual(settings.post_fall_v2_qwen_temperature, 0)
        self.assertFalse(settings.post_fall_v2_keyframe_post_collection_enabled)


if __name__ == "__main__":
    unittest.main()
