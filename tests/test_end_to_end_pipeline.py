from __future__ import annotations

import asyncio
import queue
import time
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.api import fall_events_api, integration_api, rest_api, status_api
from app.camera.source_manager import CameraSourceManager
from app.core.config import Settings
from app.core.runtime import Runtime
from app.detection.realtime_result_store import RealtimeResultStore
from app.detection.result_store import ResultStore
from app.schemas.vision_result import DetectedObject
from app.services.behavior_service import BehaviorService
from app.services.alert_simulator_service import AlertSimulatorService
from app.services.detection_service import DetectionService
from app.services.fall_event_reporter_service import FallEventReporterService
from app.services.identity_binding_service import IdentityBindingService
from app.services.identity_binding_worker_service import IdentityBindingWorkerService
from app.services.identity_service import IdentityService
from app.services.pose_service import PoseService
from app.services.pose_worker_service import PoseWorkerService
from app.services.result_publisher_service import ResultPublisherService
from app.services.status_service import StatusService
from app.services.stream_service import StreamService
from app.services.temporal_service import TemporalService
from app.services.tracking_service import TrackingService
from app.services.tracking_worker_service import TrackingWorkerService
from app.streaming.result_channel_manager import ResultChannelManager
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _FakeResponse:
    def __init__(self, status_code: int = 200, body: str = "ok") -> None:
        self.status_code = status_code
        self.text = body


class _ReporterSpy:
    def __init__(self) -> None:
        self.requests: queue.Queue[tuple[str, dict[str, Any], float]] = queue.Queue()

    def post(
        self,
        url: str,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: float = 0.0,
    ) -> _FakeResponse:
        del headers
        self.requests.put((url, json, timeout))
        return _FakeResponse(200, "accepted")


class _StubIdentityClient:
    @staticmethod
    def healthz():
        return type(
            "Health",
            (),
            {
                "available": False,
                "recognizer_loaded": False,
                "registered_count": 0,
                "last_error": None,
            },
        )()

    @staticmethod
    def match(_image_bytes: bytes, threshold: float):
        del threshold
        return type(
            "Match",
            (),
            {
                "available": False,
                "matched": False,
                "person_id": None,
                "person_name": None,
                "score": None,
                "last_error": None,
            },
        )()


class _StubPeerManager:
    def __init__(self) -> None:
        self._client_count = 0

    @property
    def client_count(self) -> int:
        return self._client_count

    async def handle_offer(self, camera_id: str, sdp: str, type_: str) -> tuple[str, str, str]:
        del camera_id, sdp, type_
        raise ValueError("webrtc unavailable in pipeline integration test")

    async def add_ice_candidate(self, peer_id: str, candidate: dict) -> None:
        del peer_id, candidate
        raise ValueError("webrtc unavailable in pipeline integration test")

    async def close(self, peer_id: str) -> None:
        del peer_id

    async def close_all(self) -> None:
        return None


class VisionPipelineE2ETest(unittest.TestCase):
    def test_camera_to_alert_pipeline(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            settings = replace(
                Settings(),
                default_rtsp_url=None,
                mock_camera_enabled=True,
                mock_camera_fps=12,
                detection_interval_ms=80,
                enable_tracking=True,
                enable_identity=False,
                enable_identity_binding=False,
                enable_pose=False,
                enable_behavior=False,
                enable_temporal=False,
                fall_detector_enabled=True,
                fall_detector_promote_unmatched=False,
                field_fall_candidate_enabled=False,
                fall_detector_confirm_enabled=True,
                fall_detector_confirm_min_probability=0.3,
                fall_detector_confirm_min_person_confidence=0.2,
                fall_detector_confirm_frames=2,
                fall_detector_confirm_ms=0,
                result_publish_fps=12.0,
                tracking_worker_fps=12.0,
                main_system_alert_enabled=True,
                main_system_report_dry_run=False,
                main_system_base_url="http://alert-host/api/v1",
                main_system_fall_event_path="/alerts/fall",
                main_system_alert_timeout_ms=1000,
                main_system_alert_cooldown_seconds=0.0,
                vision_service_public_base_url="http://testserver",
                fall_event_snapshot_dir=str(temp_path / "snapshots"),
            )
            reporter_spy = _ReporterSpy()

            original_post = None
            app = self._build_test_app(settings, reporter_spy)
            try:
                import app.services.fall_event_reporter_service as reporter_module

                original_post = reporter_module.requests.post
                reporter_module.requests.post = reporter_spy.post

                with TestClient(app) as client:
                    start = client.post(
                        "/stream/start",
                        json={"camera_id": "camera_01", "rtsp_url": "mock://colorbars"},
                    )
                    self.assertEqual(start.status_code, 200, start.text)
                    self.assertIn(start.json()["status"], {"started", "running", "restarted"})

                    latest = self._wait_for_result(client, camera_id="camera_01")
                    self.assertEqual(latest["camera_id"], "camera_01")
                    self.assertTrue(latest["objects"], latest)

                    person = next(item for item in latest["objects"] if item["label"] == "person")
                    self.assertIsNotNone(person.get("track_id"))
                    self.assertTrue(person.get("is_target"))
                    self.assertEqual((person.get("pose") or {}).get("pose_provider"), "disabled_placeholder")
                    self.assertEqual((person.get("pose") or {}).get("keypoints"), [])

                    alarm = person.get("alarm_preview") or {}
                    decision = person.get("fall_decision") or {}
                    self.assertTrue(alarm.get("confirmed"), latest)
                    self.assertEqual(decision.get("fall_state"), "fallen_confirmed", latest)

                    status = client.get("/status", params={"camera_id": "camera_01"})
                    self.assertEqual(status.status_code, 200, status.text)
                    status_payload = status.json()
                    self.assertTrue(status_payload["cameras"][0]["connected"], status_payload)
                    self.assertGreater(status_payload["cameras"][0]["frame_seq"], 0, status_payload)
                    self.assertGreaterEqual(status_payload["latest_result"]["latest_objects_count"], 1, status_payload)
                    self.assertTrue(status_payload["latest_result"]["alarm_confirmed"], status_payload)
                    self.assertFalse(status_payload["latest_result"]["pose_available"], status_payload)
                    self.assertEqual(status_payload["pose"]["pose_provider"], "disabled_placeholder", status_payload)

                    self.assertFalse(reporter_spy.requests.empty(), "expected fall reporter to post an alert")
                    url, payload, timeout = reporter_spy.requests.get(timeout=2)
                    self.assertEqual(url, "http://alert-host/api/v1/alerts/fall")
                    self.assertGreater(timeout, 0)
                    self.assertEqual(payload["camera_id"], "camera_01")
                    self.assertEqual(payload["event_type"], "fall_confirmed")
                    self.assertTrue(payload["fall_detected"])
                    self.assertEqual(payload["status"], "fallen_confirmed")
                    self.assertIsInstance(payload.get("bbox"), list)
                    self.assertIsInstance(payload.get("metadata"), dict)
                    event_metadata = payload["metadata"].get("event")
                    self.assertIsInstance(event_metadata, dict)
                    self.assertEqual(event_metadata["incident_id"], payload["incident_id"])
                    self.assertEqual(event_metadata["camera_id"], payload["camera_id"])
                    self.assertEqual(event_metadata["state"], payload["state"])
                    self.assertEqual(event_metadata["status"], payload["status"])
                    self.assertEqual(event_metadata["fall_score"], payload["fall_score"])
                    self.assertEqual(event_metadata["snapshot_path"], payload["snapshot_path"])
                    self.assertIsInstance(event_metadata.get("injury"), dict)
                    self.assertIsInstance(event_metadata.get("multimodal_review"), dict)

                    snapshot_url = payload.get("snapshot_url")
                    self.assertIsInstance(snapshot_url, str)
                    self.assertIn("/fall-events/snapshots/", snapshot_url)

                    latest_frame = client.get("/stream/latest-frame.jpg", params={"camera_id": "camera_01"})
                    self.assertEqual(latest_frame.status_code, 200, latest_frame.text)
                    self.assertEqual(latest_frame.headers["content-type"], "image/jpeg")

                    snapshot_path = snapshot_url.replace("http://testserver", "")
                    snapshot = client.get(snapshot_path)
                    self.assertEqual(snapshot.status_code, 200, snapshot.text)
                    self.assertEqual(snapshot.headers["content-type"], "image/jpeg")
                    self.assertGreater(len(snapshot.content), 0)

                    integration = client.get("/integration/results/camera_01/latest")
                    self.assertEqual(integration.status_code, 200, integration.text)
                    integration_payload = integration.json()
                    self.assertEqual(integration_payload["camera_id"], "camera_01")
                    self.assertGreater(integration_payload["analysis_fps"], 0)
            finally:
                if original_post is not None:
                    reporter_module.requests.post = original_post

    def test_same_fallen_hold_track_handoff_does_not_create_duplicate_incident(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            settings = replace(
                Settings(),
                default_rtsp_url=None,
                mock_camera_enabled=True,
                mock_camera_fps=12,
                detection_interval_ms=80,
                enable_tracking=True,
                enable_identity=False,
                enable_identity_binding=False,
                enable_pose=False,
                enable_behavior=False,
                enable_temporal=False,
                fall_detector_enabled=True,
                fall_detector_promote_unmatched=False,
                field_fall_candidate_enabled=False,
                fall_detector_confirm_enabled=True,
                fall_detector_confirm_min_probability=0.3,
                fall_detector_confirm_min_person_confidence=0.2,
                fall_detector_confirm_frames=2,
                fall_detector_confirm_ms=0,
                result_publish_fps=12.0,
                tracking_worker_fps=12.0,
                main_system_alert_enabled=True,
                main_system_report_dry_run=False,
                main_system_base_url="http://alert-host/api/v1",
                main_system_fall_event_path="/alerts/fall",
                main_system_alert_timeout_ms=1000,
                main_system_alert_cooldown_seconds=90.0,
                vision_service_public_base_url="http://testserver",
                fall_event_snapshot_dir=str(temp_path / "snapshots"),
            )
            reporter_spy = _ReporterSpy()

            original_post = None
            app = self._build_test_app(settings, reporter_spy)
            try:
                import app.services.fall_event_reporter_service as reporter_module

                original_post = reporter_module.requests.post
                reporter_module.requests.post = reporter_spy.post

                with TestClient(app) as client:
                    start = client.post(
                        "/stream/start",
                        json={"camera_id": "camera_01", "rtsp_url": "mock://colorbars"},
                    )
                    self.assertEqual(start.status_code, 200, start.text)
                    latest = self._wait_for_result(client, camera_id="camera_01")
                    first_person = next(item for item in latest["objects"] if item["label"] == "person")
                    first_incident_id = ((first_person.get("temporal") or {}).get("event_metadata") or {}).get("incident_id")
                    self.assertIsInstance(first_incident_id, str)

                    first_url, first_payload, _ = reporter_spy.requests.get(timeout=2)
                    self.assertEqual(first_url, "http://alert-host/api/v1/alerts/fall")
                    self.assertEqual(first_payload["incident_id"], first_incident_id)
                    self.assertTrue(reporter_spy.requests.empty())

                    runtime = client.app.state.runtime
                    confirmed_result = runtime.realtime_store.latest_published("camera_01")
                    self.assertIsNotNone(confirmed_result)
                    handoff_objects = []
                    for item in confirmed_result.objects:
                        if item.label != "person":
                            handoff_objects.append(item)
                            continue
                        temporal = dict(item.temporal or {})
                        temporal.pop("event_metadata", None)
                        handoff_objects.append(
                            item.model_copy(
                                update={
                                    "track_id": 99,
                                    "bbox": [108.0, 224.0, 344.0, 354.0],
                                    "temporal": temporal,
                                }
                            )
                        )
                    handoff_result = confirmed_result.model_copy(
                        update={
                            "frame_seq": confirmed_result.frame_seq + 1,
                            "objects": handoff_objects,
                        }
                    )
                    runtime.fall_event_reporter.inspect_result(handoff_result)
                    runtime.realtime_store.update_published(handoff_result)

                    self.assertTrue(reporter_spy.requests.empty(), "track handoff should not post a duplicate incident")
                    latest_alert = runtime.fall_event_reporter.latest_alert("camera_01")
                    self.assertIsNotNone(latest_alert)
                    self.assertEqual(latest_alert["incident_id"], first_incident_id)
                    self.assertEqual(latest_alert["track_id"], "99")
            finally:
                if original_post is not None:
                    reporter_module.requests.post = original_post

    def _build_test_app(self, settings: Settings, reporter_spy: _ReporterSpy) -> FastAPI:
        del reporter_spy

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            source_manager = CameraSourceManager(settings)
            realtime_store = RealtimeResultStore()
            result_store = ResultStore()
            result_channels = ResultChannelManager()
            result_channels.bind_loop(asyncio.get_running_loop())
            tracking_service = TrackingService(settings=settings)
            identity_service = IdentityService(settings=settings)
            identity_client = _StubIdentityClient()
            identity_binding_service = IdentityBindingService(settings=settings, client=identity_client)
            identity_binding_worker_service = IdentityBindingWorkerService(
                settings=settings,
                source_manager=source_manager,
                realtime_store=realtime_store,
                identity_binding_service=identity_binding_service,
            )
            pose_service = PoseService(settings=settings)
            behavior_service = BehaviorService(settings=settings)
            temporal_service = TemporalService(settings=settings)
            fall_event_reporter = FallEventReporterService(settings=settings, source_manager=source_manager)
            alert_simulator_service = AlertSimulatorService(reporter=fall_event_reporter)
            detection_service = DetectionService(
                settings=settings,
                source_manager=source_manager,
                realtime_store=realtime_store,
            )
            tracking_worker_service = TrackingWorkerService(
                settings=settings,
                realtime_store=realtime_store,
                tracking_service=tracking_service,
                identity_binding_service=identity_binding_service,
            )
            pose_worker_service = PoseWorkerService(
                settings=settings,
                source_manager=source_manager,
                realtime_store=realtime_store,
                pose_service=pose_service,
                behavior_service=behavior_service,
            )
            result_publisher_service = ResultPublisherService(
                settings=settings,
                realtime_store=realtime_store,
                result_channels=result_channels,
                temporal_service=temporal_service,
                fall_event_reporter=fall_event_reporter,
            )
            stream_service = StreamService(
                settings=settings,
                source_manager=source_manager,
                detection_service=detection_service,
                realtime_store=realtime_store,
                tracking_service=tracking_service,
                identity_binding_service=identity_binding_service,
                temporal_service=temporal_service,
                tracking_worker_service=tracking_worker_service,
                identity_binding_worker_service=identity_binding_worker_service,
                pose_worker_service=pose_worker_service,
                result_publisher_service=result_publisher_service,
            )
            peer_manager = _StubPeerManager()
            status_service = StatusService(
                settings=settings,
                source_manager=source_manager,
                detection_service=detection_service,
                peer_manager=peer_manager,
                result_channels=result_channels,
                realtime_store=realtime_store,
                tracking_service=tracking_service,
                tracking_worker_service=tracking_worker_service,
                identity_service=identity_service,
                identity_binding_service=identity_binding_service,
                identity_binding_worker_service=identity_binding_worker_service,
                pose_service=pose_service,
                behavior_service=behavior_service,
                temporal_service=temporal_service,
                result_publisher_service=result_publisher_service,
                fall_event_reporter=fall_event_reporter,
            )
            runtime = Runtime(
                settings=settings,
                source_manager=source_manager,
                realtime_store=realtime_store,
                result_store=result_store,
                result_channels=result_channels,
                tracking_service=tracking_service,
                identity_service=identity_service,
                identity_binding_service=identity_binding_service,
                identity_binding_worker_service=identity_binding_worker_service,
                pose_service=pose_service,
                behavior_service=behavior_service,
                temporal_service=temporal_service,
                fall_event_reporter=fall_event_reporter,
                alert_simulator_service=alert_simulator_service,
                detection_service=detection_service,
                tracking_worker_service=tracking_worker_service,
                pose_worker_service=pose_worker_service,
                result_publisher_service=result_publisher_service,
                stream_service=stream_service,
                peer_manager=peer_manager,
                status_service=status_service,
            )
            app.state.runtime = runtime
            self._install_stub_detectors(detection_service)
            fall_event_reporter.start()
            try:
                yield
            finally:
                await runtime.shutdown()

        app = FastAPI(lifespan=lifespan)
        app.include_router(status_api.router)
        app.include_router(rest_api.router)
        app.include_router(integration_api.router)
        app.include_router(fall_events_api.router)
        return app

    @staticmethod
    def _install_stub_detectors(detection_service: DetectionService) -> None:
        class StubPersonDetector:
            def __init__(self) -> None:
                self._calls = 0

            def detect(self, frame) -> list[DetectedObject]:
                del frame
                self._calls += 1
                return [
                    DetectedObject(
                        label="person",
                        confidence=0.95,
                        bbox=[100.0, 220.0, 340.0, 350.0],
                    )
                ]

            @staticmethod
            def status():
                return type(
                    "DetectorStatus",
                    (),
                    {
                        "enabled": True,
                        "loaded": True,
                        "model_name": "stub-person-detector",
                        "last_error": None,
                    },
                )()

        class StubFallDetector:
            def detect(self, frame) -> list[DetectedObject]:
                del frame
                return [
                    DetectedObject(
                        label="fallen",
                        confidence=0.88,
                        bbox=[102.0, 222.0, 342.0, 352.0],
                    )
                ]

            @staticmethod
            def status():
                return type(
                    "FallDetectorStatus",
                    (),
                    {
                        "enabled": True,
                        "loaded": True,
                        "model_name": "stub-fall-detector",
                        "last_error": None,
                    },
                )()

        detection_service.detector = StubPersonDetector()
        detection_service.fall_detector = StubFallDetector()

    @staticmethod
    def _wait_for_result(client: TestClient, camera_id: str, timeout: float = 6.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_payload: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            response = client.get(f"/integration/results/{camera_id}/latest")
            if response.status_code == 200:
                payload = response.json()
                last_payload = payload
                objects = payload.get("objects") if isinstance(payload.get("objects"), list) else []
                if any((item.get("alarm_preview") or {}).get("confirmed") for item in objects if isinstance(item, dict)):
                    return payload
            time.sleep(0.1)
        raise AssertionError(f"timed out waiting for confirmed result, latest={last_payload}")


if __name__ == "__main__":
    unittest.main()
