from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.camera.source_models import CameraSourceConfig
from app.core.config import Settings
from app.services.stream_service import StreamService


class StreamServiceSingleSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings()
        self.source_manager = Mock()
        self.source_manager.get_runtime.return_value = None
        self.source_manager.start_source.side_effect = self._start_source
        self.current_runtime = None

        self.detection_service = Mock()
        self.realtime_store = Mock()
        self.tracking_service = Mock()
        self.identity_binding_service = Mock()
        self.temporal_service = Mock()
        self.tracking_worker_service = Mock()
        self.identity_binding_worker_service = Mock()
        self.pose_worker_service = Mock()
        self.result_publisher_service = Mock()

        self.service = StreamService(
            settings=self.settings,
            source_manager=self.source_manager,
            detection_service=self.detection_service,
            realtime_store=self.realtime_store,
            tracking_service=self.tracking_service,
            identity_binding_service=self.identity_binding_service,
            temporal_service=self.temporal_service,
            tracking_worker_service=self.tracking_worker_service,
            identity_binding_worker_service=self.identity_binding_worker_service,
            pose_worker_service=self.pose_worker_service,
            result_publisher_service=self.result_publisher_service,
        )

    def test_rtsp_url_is_authoritative_when_multiple_urls_are_provided(self) -> None:
        source_url = "rtsp://admin:***@192.168.8.252:10554/tcp/av0_1"
        main_source_url = "rtsp://admin:***@192.168.8.252:10554/tcp/av0_0"
        analysis_source_url = "rtsp://admin:***@192.168.8.253:10554/tcp/av0_1"

        created, message = self.service.start(
            "camera_01",
            source_url,
            main_source_url=main_source_url,
            analysis_source_url=analysis_source_url,
        )

        self.assertTrue(created)
        self.assertEqual(message, "stream started")
        self.assertIsNotNone(self.current_runtime)
        self.assertEqual(self.current_runtime.config.source_url, source_url)

    def test_analysis_url_is_used_when_rtsp_url_is_missing(self) -> None:
        analysis_source_url = "rtsp://admin:***@192.168.8.252:10554/tcp/av0_1"

        created, message = self.service.start(
            "camera_01",
            None,
            main_source_url=None,
            analysis_source_url=analysis_source_url,
        )

        self.assertTrue(created)
        self.assertEqual(message, "stream started")
        self.assertIsNotNone(self.current_runtime)
        self.assertEqual(self.current_runtime.config.source_url, analysis_source_url)

    def _start_source(self, config: CameraSourceConfig):
        self.current_runtime = SimpleNamespace(config=config)
        self.source_manager.get_runtime.return_value = self.current_runtime
        return self.current_runtime, True


if __name__ == "__main__":
    unittest.main()
