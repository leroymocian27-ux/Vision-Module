from __future__ import annotations

import asyncio
import time
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from tempfile import TemporaryDirectory
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import fall_events_api, integration_api, rest_api, status_api
from app.camera.source_manager import CameraSourceManager
from app.core.config import Settings
from app.core.runtime import Runtime
from app.detection.realtime_result_store import RealtimeResultStore
from app.detection.result_store import ResultStore
from app.schemas.vision_result import DetectedObject
from app.services.alert_simulator_service import AlertSimulatorService
from app.services.behavior_service import BehaviorService
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

    async def close_all(self) -> None:
        return None


class FallAlertPollingApiTest(unittest.TestCase):
    def test_polling_endpoint_returns_popup_for_new_confirmed_alert(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = self._settings(main_system_alert_enabled=False, snapshot_root=Path(temp_dir))
            app = self._build_test_app(settings)

            with TestClient(app) as client:
                self._start_mock_stream(client)
                latest = self._wait_for_result(client)
                person = next(item for item in latest["objects"] if item["label"] == "person")
                incident_id = ((client.get("/integration/fall-alerts/camera_01/poll")).json())["incident_id"]

                self.assertTrue(person["alarm_preview"]["confirmed"])
                self.assertIsInstance(incident_id, str)
                self.assertEqual((person.get("pose") or {}).get("pose_provider"), "disabled_placeholder")
                self.assertEqual((person.get("pose") or {}).get("keypoints"), [])

                poll = client.get("/integration/fall-alerts/camera_01/poll")
                self.assertEqual(poll.status_code, 200, poll.text)
                payload = poll.json()
                self.assertTrue(payload["should_popup"], payload)
                self.assertEqual(payload["status"], "new_alert", payload)
                self.assertEqual(payload["fall_state"], "fallen_confirmed", payload)
                self.assertEqual(payload["incident_id"], incident_id, payload)
                self.assertIsInstance(payload["alert"], dict)

                status = client.get("/status", params={"camera_id": "camera_01"})
                self.assertEqual(status.status_code, 200, status.text)
                status_payload = status.json()
                self.assertTrue(status_payload["polling_alert"]["should_popup"], status_payload)
                self.assertEqual(status_payload["polling_alert"]["incident_id"], incident_id, status_payload)
                self.assertEqual(status_payload["latest_result"]["incident_id"], incident_id, status_payload)
                self.assertIsInstance(status_payload["latest_result"]["snapshot_url"], str, status_payload)
                self.assertGreaterEqual(status_payload["latest_result"]["fall_prob"], 0.3, status_payload)
                self.assertFalse(status_payload["latest_result"]["pose_available"], status_payload)
                self.assertEqual(status_payload["pose"]["pose_provider"], "disabled_placeholder", status_payload)
                self.assertEqual(
                    status_payload["latest_result"]["fall_score"],
                    status_payload["latest_result"]["fall_prob"],
                    status_payload,
                )

    def test_polling_endpoint_suppresses_seen_incident(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = self._settings(main_system_alert_enabled=False, snapshot_root=Path(temp_dir))
            app = self._build_test_app(settings)

            with TestClient(app) as client:
                self._start_mock_stream(client)
                first = client.get("/integration/fall-alerts/camera_01/poll")
                initial_payload = self._wait_for_popup_payload(client, first.json().get("incident_id"))
                seen = client.get(
                    "/integration/fall-alerts/camera_01/poll",
                    params={"last_incident_id": initial_payload["incident_id"]},
                )
                self.assertEqual(seen.status_code, 200, seen.text)
                seen_payload = seen.json()
                self.assertFalse(seen_payload["should_popup"], seen_payload)
                self.assertEqual(seen_payload["status"], "seen_alert", seen_payload)
                self.assertEqual(seen_payload["incident_id"], initial_payload["incident_id"], seen_payload)

    def test_polling_endpoint_returns_no_alert_before_detection(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = self._settings(main_system_alert_enabled=False, snapshot_root=Path(temp_dir))
            app = self._build_test_app(settings)

            with TestClient(app) as client:
                response = client.get("/integration/fall-alerts/camera_01/poll")
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertFalse(payload["should_popup"], payload)
                self.assertEqual(payload["status"], "no_alert", payload)
                self.assertIsNone(payload["incident_id"], payload)

    def test_latest_result_includes_main_system_summary_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = self._settings(main_system_alert_enabled=False, snapshot_root=Path(temp_dir))
            app = self._build_test_app(settings)

            with TestClient(app) as client:
                self._start_mock_stream(client)
                self._wait_for_result(client)
                response = client.get("/integration/results/camera_01/latest")
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertEqual(payload["camera_id"], "camera_01", payload)
                self.assertEqual(payload["stream_name"], "primary", payload)
                self.assertEqual(payload["source"], "vision_service", payload)
                self.assertEqual(payload["service_state"], "running", payload)
                self.assertIsInstance(payload["frame_age_ms"], (int, float), payload)
                self.assertIsInstance(payload["source_fps"], (int, float), payload)
                self.assertIsInstance(payload["analysis_fps"], (int, float), payload)
                self.assertTrue(payload["fall_detected"], payload)
                self.assertEqual(payload["fall_state"], "fallen_confirmed", payload)
                self.assertEqual(payload["risk"], "critical", payload)
                self.assertEqual(payload["risk_level"], "critical", payload)
                self.assertGreaterEqual(payload["fall_prob"], 0.3, payload)
                self.assertEqual(payload["fall_score"], payload["fall_prob"], payload)
                self.assertIsNotNone(payload["track_id"], payload)
                self.assertIsInstance(payload["incident_id"], str, payload)
                self.assertIsInstance(payload["snapshot_url"], str, payload)
                self.assertTrue(payload["alarm_confirmed"], payload)
                self.assertIsInstance(payload["bbox"], list, payload)
                self.assertEqual(len(payload["bbox"]), 4, payload)
                self.assertIsInstance(payload["target"], dict, payload)
                self.assertIsInstance(payload["scores"], dict, payload)
                self.assertIsInstance(payload["metadata"], dict, payload)
                self.assertIsInstance(payload["objects"], list, payload)

                status = client.get("/status", params={"camera_id": "camera_01"})
                self.assertEqual(status.status_code, 200, status.text)
                status_payload = status.json()["latest_result"]
                self.assertEqual(status_payload["camera_id"], "camera_01", status_payload)
                self.assertIsInstance(status_payload["timestamp"], str, status_payload)
                self.assertEqual(status_payload["fall_state"], "fallen_confirmed", status_payload)
                self.assertTrue(status_payload["alarm_confirmed"], status_payload)
                self.assertGreaterEqual(status_payload["fall_prob"], 0.3, status_payload)
                self.assertEqual(status_payload["risk_level"], "critical", status_payload)
                self.assertIsInstance(status_payload["incident_id"], str, status_payload)
                self.assertIsInstance(status_payload["snapshot_url"], str, status_payload)
                self.assertIsInstance(status_payload["snapshot_path"], str, status_payload)

    def test_polling_alert_clears_after_non_fall_result(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = self._settings(main_system_alert_enabled=False, snapshot_root=Path(temp_dir))
            app = self._build_test_app(settings)

            with TestClient(app) as client:
                self._start_mock_stream(client)
                popup_payload = self._wait_for_popup_payload(client, existing_incident_id=None)
                self.assertTrue(popup_payload["should_popup"], popup_payload)

                runtime = client.app.state.runtime
                result = runtime.realtime_store.latest_published("camera_01")
                self.assertIsNotNone(result)
                neutral_result = result.model_copy(
                    update={
                        "objects": [
                            item.model_copy(
                                update={
                                    "fall_decision": None,
                                    "alarm_preview": None,
                                }
                            )
                            for item in result.objects
                        ]
                    }
                )
                runtime.fall_event_reporter.inspect_result(neutral_result)

                cleared = client.get("/integration/fall-alerts/camera_01/poll")
                self.assertEqual(cleared.status_code, 200, cleared.text)
                cleared_payload = cleared.json()
                self.assertFalse(cleared_payload["should_popup"], cleared_payload)
                self.assertEqual(cleared_payload["status"], "no_alert", cleared_payload)
                self.assertIsNone(cleared_payload["incident_id"], cleared_payload)

    def test_confirmed_fall_reuses_incident_id_during_cooldown_reentry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = replace(
                self._settings(main_system_alert_enabled=False, snapshot_root=Path(temp_dir)),
                main_system_alert_cooldown_seconds=90.0,
            )
            app = self._build_test_app(settings)

            with TestClient(app) as client:
                self._start_mock_stream(client)
                self._wait_for_result(client)

                runtime = client.app.state.runtime
                reporter = runtime.fall_event_reporter
                initial_alert = reporter.latest_alert("camera_01")
                self.assertIsNotNone(initial_alert)
                initial_incident_id = initial_alert["incident_id"]

                confirmed_result = runtime.realtime_store.latest_published("camera_01")
                self.assertIsNotNone(confirmed_result)

                neutral_result = confirmed_result.model_copy(
                    update={
                        "objects": [
                            item.model_copy(
                                update={
                                    "fall_decision": None,
                                    "alarm_preview": None,
                                }
                            )
                            for item in confirmed_result.objects
                        ]
                    }
                )
                reporter.inspect_result(neutral_result)

                reconfirmed_objects = []
                for item in confirmed_result.objects:
                    temporal = dict(item.temporal or {})
                    temporal.pop("event_metadata", None)
                    reconfirmed_objects.append(item.model_copy(update={"temporal": temporal}))
                reconfirmed_result = confirmed_result.model_copy(update={"objects": reconfirmed_objects})
                reporter.inspect_result(reconfirmed_result)
                runtime.realtime_store.update_published(reconfirmed_result)

                latest_alert = reporter.latest_alert("camera_01")
                self.assertIsNotNone(latest_alert)
                self.assertEqual(latest_alert["incident_id"], initial_incident_id)

                person = next(item for item in reconfirmed_result.objects if item.label == "person")
                event_metadata = (person.temporal or {}).get("event_metadata") or {}
                self.assertEqual(event_metadata.get("incident_id"), initial_incident_id)

                status = client.get("/status", params={"camera_id": "camera_01"})
                self.assertEqual(status.status_code, 200, status.text)
                status_payload = status.json()["latest_result"]
                self.assertEqual(status_payload["incident_id"], initial_incident_id, status_payload)

                integration = client.get("/integration/results/camera_01/latest")
                self.assertEqual(integration.status_code, 200, integration.text)
                integration_payload = integration.json()
                self.assertEqual(integration_payload["incident_id"], initial_incident_id, integration_payload)
                self.assertEqual(status_payload["incident_id"], integration_payload["incident_id"], integration_payload)
                self.assertTrue(
                    isinstance(integration_payload.get("snapshot_url"), str)
                    or isinstance(integration_payload.get("snapshot_path"), str),
                    integration_payload,
                )

    def test_polling_endpoint_does_not_emit_duplicate_popup_for_reused_track_handoff_incident(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = replace(
                self._settings(main_system_alert_enabled=False, snapshot_root=Path(temp_dir)),
                main_system_alert_cooldown_seconds=90.0,
            )
            app = self._build_test_app(settings)

            with TestClient(app) as client:
                self._start_mock_stream(client)
                first_popup = self._wait_for_popup_payload(client, existing_incident_id=None)
                initial_incident_id = first_popup["incident_id"]

                runtime = client.app.state.runtime
                reporter = runtime.fall_event_reporter
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
                reporter.inspect_result(handoff_result)
                runtime.realtime_store.update_published(handoff_result)

                poll = client.get(
                    "/integration/fall-alerts/camera_01/poll",
                    params={"last_incident_id": initial_incident_id},
                )
                self.assertEqual(poll.status_code, 200, poll.text)
                payload = poll.json()
                self.assertFalse(payload["should_popup"], payload)
                self.assertEqual(payload["status"], "seen_alert", payload)
                self.assertEqual(payload["incident_id"], initial_incident_id, payload)

    @staticmethod
    def _settings(*, main_system_alert_enabled: bool, snapshot_root: Path) -> Settings:
        return replace(
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
            main_system_alert_enabled=main_system_alert_enabled,
            main_system_base_url="http://alert-host/api/v1",
            main_system_fall_event_path="/alerts/fall",
            main_system_alert_timeout_ms=1000,
            main_system_alert_cooldown_seconds=0.0,
            vision_service_public_base_url="http://testserver",
            fall_event_snapshot_dir=str(snapshot_root / "snapshots"),
        )

    def _build_test_app(self, settings: Settings) -> FastAPI:
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
            def detect(self, frame) -> list[DetectedObject]:
                del frame
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
    def _start_mock_stream(client: TestClient) -> None:
        response = client.post(
            "/stream/start",
            json={"camera_id": "camera_01", "rtsp_url": "mock://colorbars"},
        )
        if response.status_code != 200:
            raise AssertionError(response.text)

    @staticmethod
    def _wait_for_result(client: TestClient, timeout: float = 6.0) -> dict:
        deadline = time.monotonic() + timeout
        last_payload = None
        while time.monotonic() < deadline:
            response = client.get("/integration/results/camera_01/latest")
            if response.status_code == 200:
                payload = response.json()
                last_payload = payload
                objects = payload.get("objects") if isinstance(payload.get("objects"), list) else []
                if any((item.get("alarm_preview") or {}).get("confirmed") for item in objects if isinstance(item, dict)):
                    return payload
            time.sleep(0.1)
        raise AssertionError(f"timed out waiting for confirmed result, latest={last_payload}")

    @staticmethod
    def _wait_for_popup_payload(client: TestClient, existing_incident_id: str | None, timeout: float = 6.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = client.get("/integration/fall-alerts/camera_01/poll")
            payload = response.json()
            if payload.get("should_popup") and payload.get("incident_id") != existing_incident_id:
                return payload
            time.sleep(0.1)
        raise AssertionError("timed out waiting for popup alert payload")


if __name__ == "__main__":
    unittest.main()
