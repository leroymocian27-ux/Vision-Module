from __future__ import annotations

import json
import unittest
from dataclasses import replace

from app.core.config import Settings
from app.schemas.vision_result import DetectedObject, VisionResult
import app.services.fall_event_reporter_service as reporter_module
from app.services.fall_event_reporter_service import FallEventReporterService


class _StubSourceManager:
    @staticmethod
    def get_buffer(camera_id: str):
        del camera_id
        return None


class FallEventReporterServiceTest(unittest.TestCase):
    def test_dry_run_skips_http_post_and_records_status_without_token(self) -> None:
        settings = replace(
            Settings(),
            main_system_alert_enabled=True,
            main_system_report_dry_run=True,
            main_system_alert_token="unit-test-token",
            main_system_alert_token_header="X-Vision-Service-Token",
            main_system_base_url="http://192.168.8.254:8000/api/v1",
            main_system_fall_event_path="/video-bridge/fall-events",
        )
        reporter = FallEventReporterService(settings=settings, source_manager=_StubSourceManager())
        calls: list[dict] = []

        def fake_post(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            raise AssertionError("dry-run must not call HTTP POST")

        previous_post = reporter_module.requests.post
        reporter_module.requests.post = fake_post
        try:
            reporter._post_payload(  # type: ignore[attr-defined]
                {
                    "event_type": "fall_confirmed",
                    "camera_id": "camera_01",
                    "track_id": "dry-run-track",
                    "incident_id": "dry-run-incident",
                }
            )
        finally:
            reporter_module.requests.post = previous_post

        status = reporter.status()
        self.assertEqual(calls, [])
        self.assertTrue(status["dry_run"])
        self.assertEqual(status["last_post_status"], "dry_run_skipped")
        self.assertEqual(status["token_header"], "X-Vision-Service-Token")
        self.assertNotIn("unit-test-token", json.dumps(status, default=str))

    def test_post_payload_keeps_existing_http_post_when_dry_run_disabled(self) -> None:
        settings = replace(
            Settings(),
            main_system_alert_enabled=True,
            main_system_report_dry_run=False,
            main_system_alert_token="unit-test-token",
            main_system_alert_token_header="X-Vision-Service-Token",
            main_system_base_url="http://192.168.8.254:8000/api/v1",
            main_system_fall_event_path="/video-bridge/fall-events",
        )
        reporter = FallEventReporterService(settings=settings, source_manager=_StubSourceManager())
        calls: list[dict] = []

        class FakeResponse:
            status_code = 200
            text = '{"ok":true}'

        def fake_post(url: str, json: dict, headers: dict, timeout: float) -> FakeResponse:
            calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return FakeResponse()

        previous_post = reporter_module.requests.post
        reporter_module.requests.post = fake_post
        try:
            reporter._post_payload(  # type: ignore[attr-defined]
                {
                    "event_type": "fall_confirmed",
                    "camera_id": "camera_01",
                    "track_id": "post-track",
                    "incident_id": "post-incident",
                }
            )
        finally:
            reporter_module.requests.post = previous_post

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["url"], "http://192.168.8.254:8000/api/v1/video-bridge/fall-events")
        self.assertEqual(calls[0]["headers"], {"X-Vision-Service-Token": "unit-test-token"})
        self.assertEqual(reporter.status()["last_post_status"], "http_200")

    def test_active_confirmed_fall_backfills_snapshot_after_initial_miss(self) -> None:
        settings = replace(
            Settings(),
            main_system_alert_enabled=False,
            main_system_alert_cooldown_seconds=90.0,
            vision_service_public_base_url="http://testserver",
        )
        reporter = FallEventReporterService(settings=settings, source_manager=_StubSourceManager())

        snapshots = iter(
            [
                (None, None),
                ("http://testserver/fall-events/snapshots/camera_01_1_retry.jpg", "C:\\snapshots\\camera_01_1_retry.jpg"),
            ]
        )
        reporter._save_snapshot = lambda camera_id, track_id, timestamp_slug: next(snapshots)  # type: ignore[method-assign]

        first = self._confirmed_result()
        reporter.inspect_result(first)
        first_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(first_alert)
        self.assertIsNone(first_alert["snapshot_url"])
        self.assertIsNone(first_alert["snapshot_path"])

        second = self._confirmed_result()
        reporter.inspect_result(second)
        second_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(second_alert)
        self.assertIsInstance(second_alert["snapshot_url"], str)
        self.assertIsInstance(second_alert["snapshot_path"], str)

        person = next(item for item in second.objects if item.label == "person")
        event_metadata = (person.temporal or {}).get("event_metadata") or {}
        self.assertEqual(event_metadata.get("incident_id"), second_alert["incident_id"])
        self.assertEqual(event_metadata.get("snapshot_url"), second_alert["snapshot_url"])
        self.assertEqual(event_metadata.get("snapshot_path"), second_alert["snapshot_path"])

    def test_old_incident_is_not_reused_without_person_evidence(self) -> None:
        settings = replace(
            Settings(),
            main_system_alert_enabled=False,
            main_system_alert_cooldown_seconds=90.0,
            vision_service_public_base_url="http://testserver",
        )
        reporter = FallEventReporterService(settings=settings, source_manager=_StubSourceManager())
        reporter._save_snapshot = lambda camera_id, track_id, timestamp_slug: (  # type: ignore[method-assign]
            f"http://testserver/fall-events/snapshots/{camera_id}_{track_id}_{timestamp_slug}.jpg",
            f"C:\\snapshots\\{camera_id}_{track_id}_{timestamp_slug}.jpg",
        )

        confirmed = self._confirmed_result()
        reporter.inspect_result(confirmed)
        self.assertIsNotNone(reporter.latest_alert("camera_01"))

        invalid = self._confirmed_result().model_copy(
            update={
                "objects": [
                    item.model_copy(
                        update={
                            "fall_decision": {
                                **(item.fall_decision or {}),
                                "person_evidence": False,
                            },
                            "alarm_preview": {
                                **(item.alarm_preview or {}),
                                "person_evidence": False,
                            },
                        }
                    )
                    for item in self._confirmed_result().objects
                ]
            }
        )
        reporter.inspect_result(invalid)

        self.assertIsNone(reporter.latest_alert("camera_01"))
        person = next(item for item in invalid.objects if item.label == "person")
        event_metadata = (person.temporal or {}).get("event_metadata") or {}
        self.assertEqual(event_metadata, {})

    def test_same_track_reuses_incident_id_when_spatial_key_drifts(self) -> None:
        settings = replace(
            Settings(),
            main_system_alert_enabled=False,
            main_system_alert_cooldown_seconds=90.0,
            vision_service_public_base_url="http://testserver",
        )
        reporter = FallEventReporterService(settings=settings, source_manager=_StubSourceManager())
        reporter._save_snapshot = lambda camera_id, track_id, timestamp_slug: (  # type: ignore[method-assign]
            f"http://testserver/fall-events/snapshots/{camera_id}_{track_id}_{timestamp_slug}.jpg",
            f"C:\\snapshots\\{camera_id}_{track_id}_{timestamp_slug}.jpg",
        )

        first = self._confirmed_result()
        reporter.inspect_result(first)
        first_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(first_alert)

        second = self._confirmed_result().model_copy(
            update={
                "frame_seq": 2,
                "objects": [
                    item.model_copy(update={"bbox": [310.0, 160.0, 560.0, 320.0]})
                    for item in self._confirmed_result().objects
                ],
            }
        )
        reporter.inspect_result(second)
        second_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(second_alert)
        self.assertEqual(second_alert["incident_id"], first_alert["incident_id"])

        person = next(item for item in second.objects if item.label == "person")
        event_metadata = (person.temporal or {}).get("event_metadata") or {}
        self.assertEqual(event_metadata.get("incident_id"), first_alert["incident_id"])

    def test_track_handoff_nearby_bbox_reuses_same_incident_id(self) -> None:
        reporter = self._reporter()

        first = self._confirmed_result(track_id=2, bbox=[120.0, 180.0, 360.0, 350.0])
        reporter.inspect_result(first)
        first_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(first_alert)

        second = self._confirmed_result(
            track_id=1,
            bbox=[126.0, 184.0, 364.0, 352.0],
            frame_seq=2,
        )
        reporter.inspect_result(second)
        second_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(second_alert)
        self.assertEqual(second_alert["incident_id"], first_alert["incident_id"])
        self.assertEqual(second_alert["track_id"], "1")

        person = next(item for item in second.objects if item.label == "person")
        event_metadata = (person.temporal or {}).get("event_metadata") or {}
        debug = event_metadata.get("incident_reuse_debug") or {}
        self.assertEqual(event_metadata.get("incident_id"), first_alert["incident_id"])
        self.assertTrue(debug.get("incident_reused"))
        self.assertTrue(debug.get("track_handoff_detected"))
        self.assertTrue(debug.get("duplicate_incident_suppressed"))

    def test_track_handoff_reuses_same_incident_id_from_recent_bbox_history(self) -> None:
        reporter = self._reporter()

        first = self._confirmed_result(track_id=2, bbox=[120.0, 180.0, 360.0, 350.0])
        reporter.inspect_result(first)
        first_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(first_alert)

        with reporter._lock:
            incident = reporter._incident_cache_by_id[first_alert["incident_id"]]
            incident["last_bbox"] = [420.0, 120.0, 520.0, 220.0]
            incident["recent_bboxes"] = [
                [120.0, 180.0, 360.0, 350.0],
                [420.0, 120.0, 520.0, 220.0],
            ]

        second = self._confirmed_result(
            track_id=9,
            bbox=[126.0, 184.0, 364.0, 352.0],
            frame_seq=2,
        )
        reporter.inspect_result(second)
        second_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(second_alert)
        self.assertEqual(second_alert["incident_id"], first_alert["incident_id"])

        person = next(item for item in second.objects if item.label == "person")
        event_metadata = (person.temporal or {}).get("event_metadata") or {}
        debug = event_metadata.get("incident_reuse_debug") or {}
        self.assertTrue(debug.get("incident_reused"))
        self.assertTrue(debug.get("track_handoff_detected"))

    def test_upright_recovery_field_confirm_is_blocked_by_reporter_guard(self) -> None:
        reporter = self._reporter()

        upright = self._confirmed_result(
            track_id=4,
            bbox=[260.0, 50.0, 380.0, 320.0],
            confirm_source="field_low_posture_recent_fall_hint",
            behavior={"behavior_state": "standing"},
            temporal={
                "window_size": 16,
                "low_posture": False,
                "bbox_aspect_ratio": 0.4444,
                "field_rule_debug": {
                    "behavior_state": "standing",
                    "low_posture": False,
                    "bbox_aspect_ratio": 0.4444,
                    "has_current_fall_object": False,
                    "has_temporal_confirm_evidence": False,
                },
            },
        )

        reporter.inspect_result(upright)

        self.assertIsNone(reporter.latest_alert("camera_01"))
        person = next(item for item in upright.objects if item.label == "person")
        event_metadata = (person.temporal or {}).get("event_metadata") or {}
        self.assertEqual(event_metadata.get("reporter_guard_reason"), "reporter_upright_recovery_guard")

    def test_field_then_temporal_confirm_with_different_track_reuses_incident_id(self) -> None:
        reporter = self._reporter()

        first = self._confirmed_result(track_id=2, confirm_source="field_low_posture_recent_fall_hint")
        reporter.inspect_result(first)
        first_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(first_alert)

        second = self._confirmed_result(
            track_id=1,
            frame_seq=2,
            bbox=[108.0, 124.0, 304.0, 422.0],
            confirm_source="temporal_state_machine",
        )
        reporter.inspect_result(second)
        second_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(second_alert)
        self.assertEqual(second_alert["incident_id"], first_alert["incident_id"])

    def test_far_bbox_creates_new_incident_id(self) -> None:
        reporter = self._reporter()

        first = self._confirmed_result(track_id=2, bbox=[100.0, 120.0, 300.0, 420.0])
        reporter.inspect_result(first)
        first_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(first_alert)

        second = self._confirmed_result(
            track_id=1,
            frame_seq=2,
            bbox=[820.0, 180.0, 1100.0, 520.0],
        )
        reporter.inspect_result(second)
        second_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(second_alert)
        self.assertNotEqual(second_alert["incident_id"], first_alert["incident_id"])

    def test_outside_reuse_window_creates_new_incident_id(self) -> None:
        reporter = self._reporter()

        first = self._confirmed_result(track_id=2)
        reporter.inspect_result(first)
        first_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(first_alert)

        with reporter._lock:
            incident = reporter._incident_cache_by_id[first_alert["incident_id"]]
            incident["last_seen_monotonic"] = float(incident["last_seen_monotonic"]) - 30.0

        second = self._confirmed_result(track_id=1, frame_seq=2, bbox=[108.0, 124.0, 304.0, 422.0])
        reporter.inspect_result(second)
        second_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(second_alert)
        self.assertNotEqual(second_alert["incident_id"], first_alert["incident_id"])

    def test_different_camera_creates_new_incident_id(self) -> None:
        reporter = self._reporter()

        first = self._confirmed_result(camera_id="camera_01", track_id=2)
        reporter.inspect_result(first)
        first_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(first_alert)

        second = self._confirmed_result(camera_id="camera_02", track_id=1)
        reporter.inspect_result(second)
        second_alert = reporter.latest_alert("camera_02")
        self.assertIsNotNone(second_alert)
        self.assertNotEqual(second_alert["incident_id"], first_alert["incident_id"])

    def test_multi_person_scene_does_not_merge_cross_track_incident(self) -> None:
        reporter = self._reporter()

        first = self._confirmed_result(track_id=2)
        reporter.inspect_result(first)
        first_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(first_alert)

        extra_person = DetectedObject(
            label="person",
            confidence=0.93,
            bbox=[780.0, 140.0, 1040.0, 430.0],
            track_id=7,
        )
        second = self._confirmed_result(
            track_id=1,
            frame_seq=2,
            bbox=[108.0, 124.0, 304.0, 422.0],
            extra_objects=[extra_person],
        )
        reporter.inspect_result(second)
        second_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(second_alert)
        self.assertNotEqual(second_alert["incident_id"], first_alert["incident_id"])

    def test_same_track_confirmed_twice_reuses_same_incident_id(self) -> None:
        reporter = self._reporter()

        first = self._confirmed_result(track_id=4)
        reporter.inspect_result(first)
        first_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(first_alert)

        second = self._confirmed_result(track_id=4, frame_seq=2, bbox=[106.0, 124.0, 302.0, 421.0])
        reporter.inspect_result(second)
        second_alert = reporter.latest_alert("camera_01")
        self.assertIsNotNone(second_alert)
        self.assertEqual(second_alert["incident_id"], first_alert["incident_id"])

    def _reporter(self) -> FallEventReporterService:
        settings = replace(
            Settings(),
            main_system_alert_enabled=False,
            main_system_alert_cooldown_seconds=90.0,
            vision_service_public_base_url="http://testserver",
        )
        reporter = FallEventReporterService(settings=settings, source_manager=_StubSourceManager())
        reporter._save_snapshot = lambda camera_id, track_id, timestamp_slug: (  # type: ignore[method-assign]
            f"http://testserver/fall-events/snapshots/{camera_id}_{track_id}_{timestamp_slug}.jpg",
            f"C:\\snapshots\\{camera_id}_{track_id}_{timestamp_slug}.jpg",
        )
        return reporter

    @staticmethod
    def _confirmed_result(
        *,
        camera_id: str = "camera_01",
        track_id: int = 1,
        bbox: list[float] | None = None,
        frame_seq: int = 1,
        timestamp: str = "2026-06-16T12:00:00Z",
        confirm_source: str | None = None,
        extra_objects: list[DetectedObject] | None = None,
        temporal: dict | None = None,
        behavior: dict | None = None,
    ) -> VisionResult:
        person_bbox = bbox or [100.0, 120.0, 300.0, 420.0]
        fall_decision = {
            "fall_state": "fallen_confirmed",
            "risk_level": "critical",
            "fall_probability": 0.94,
        }
        if confirm_source is not None:
            fall_decision["confirm_source"] = confirm_source
        return VisionResult(
            camera_id=camera_id,
            timestamp=timestamp,
            frame_seq=frame_seq,
            frame_width=1280,
            frame_height=720,
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.95,
                    bbox=person_bbox,
                    track_id=track_id,
                    temporal=temporal or {"window_size": 16},
                    behavior=behavior,
                    fall_decision=fall_decision,
                    alarm_preview={
                        "confirmed": True,
                        "risk_level": "critical",
                        "fall_probability": 0.94,
                    },
                ),
                *(extra_objects or []),
            ],
        )


if __name__ == "__main__":
    unittest.main()
