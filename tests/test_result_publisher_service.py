from __future__ import annotations

import unittest
from dataclasses import replace
from tempfile import TemporaryDirectory
from threading import Event
import time

import app.services.fall_event_reporter_service as reporter_module
from app.core.config import Settings
from app.detection.realtime_result_store import DetectionSnapshot, ObjectSnapshot, RealtimeResultStore
from app.schemas.vision_result import DetectedObject, VisionResult
from app.services.fall_event_reporter_service import FallEventReporterService
from app.services.result_publisher_service import ResultPublisherService


class _StubSourceManager:
    @staticmethod
    def get_buffer(camera_id: str):
        del camera_id
        return None


class _ResultChannelSpy:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def publish(self, result: VisionResult) -> None:
        self.payloads.append(result.model_dump(mode="json"))


class ResultPublisherServiceTest(unittest.TestCase):
    def test_upright_recovery_guard_clears_unconfirmed_high_risk_candidate(self) -> None:
        publisher = ResultPublisherService(
            settings=Settings(),
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        obj = DetectedObject(
            label="person",
            confidence=0.9,
            bbox=[260.0, 50.0, 380.0, 320.0],
            track_id=5,
            fall_decision={
                "fall_state": "fallen_candidate",
                "risk_level": "high",
                "fall_probability": 0.72,
                "source": "fusion_state_machine",
            },
            alarm_preview={
                "confirmed": False,
                "risk_level": "high",
                "fall_probability": 0.72,
                "source": "fusion_state_machine",
            },
            features={
                "motion": {"aspect_ratio": 0.44, "tracking_stable": True},
                "pose": {"pose_available": True, "low_posture": False},
                "fall_hint": {"strong_hint": False, "transition_hint": False, "weak_hint": False},
            },
            temporal={"low_posture": False, "bbox_aspect_ratio": 0.44},
        )

        guarded = publisher._apply_upright_recovery_guard([obj])  # type: ignore[attr-defined]

        self.assertEqual(guarded[0].fall_decision["fall_state"], "normal")
        self.assertEqual(guarded[0].alarm_preview["risk_level"], "low")
        self.assertFalse(guarded[0].alarm_preview["confirmed"])
        self.assertTrue(guarded[0].fusion_debug["upright_recovery_guard"])

    def test_upright_recovery_guard_does_not_clear_confirmed_fall(self) -> None:
        publisher = ResultPublisherService(
            settings=Settings(),
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        obj = DetectedObject(
            label="person",
            confidence=0.9,
            bbox=[260.0, 50.0, 380.0, 320.0],
            track_id=5,
            fall_decision={"fall_state": "fallen_confirmed", "risk_level": "critical", "fall_probability": 0.9},
            alarm_preview={"confirmed": True, "risk_level": "critical", "fall_probability": 0.9},
            features={
                "motion": {"aspect_ratio": 0.44, "tracking_stable": True},
                "pose": {"pose_available": True, "low_posture": False},
                "fall_hint": {"strong_hint": False},
            },
        )

        guarded = publisher._apply_upright_recovery_guard([obj])  # type: ignore[attr-defined]

        self.assertEqual(guarded[0].fall_decision["fall_state"], "fallen_confirmed")
        self.assertTrue(guarded[0].alarm_preview["confirmed"])

    def test_disabled_pose_runtime_injects_placeholder_pose_payload(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=False,
            pose_provider="disabled_placeholder",
        )
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        objects = [
            DetectedObject(
                label="person",
                confidence=0.91,
                bbox=[100.0, 120.0, 300.0, 420.0],
                track_id=1,
                is_target=True,
            )
        ]

        normalized = publisher._ensure_pose_payloads(  # type: ignore[attr-defined]
            objects,
            frame_seq=18,
            frame_timestamp="2026-06-21T08:10:00Z",
        )

        pose = normalized[0].pose
        self.assertIsInstance(pose, dict)
        self.assertEqual(pose["pose_provider"], "disabled_placeholder")
        self.assertEqual(pose["keypoints"], [])
        self.assertTrue((pose.get("debug") or {}).get("placeholder"))

    def test_merge_objects_rejects_mismatched_pose_track(self) -> None:
        base_objects = [
            DetectedObject(
                label="person",
                confidence=0.95,
                bbox=[100.0, 120.0, 300.0, 420.0],
                track_id=7,
            )
        ]
        snapshot = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=1280,
            frame_height=720,
            timestamp="2026-06-17T01:00:00Z",
            monotonic_at=0.0,
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.95,
                    bbox=[100.0, 120.0, 300.0, 420.0],
                    track_id=7,
                    pose={
                        "track_id": 9,
                        "source_track_id": 9,
                        "source_bbox": [500.0, 100.0, 720.0, 420.0],
                        "pose_bbox": [520.0, 130.0, 700.0, 410.0],
                        "pose_frame_seq": 9,
                        "pose_timestamp": "2026-06-17T01:00:00Z",
                        "keypoints": [{"name": "nose", "x": 600.0, "y": 180.0, "confidence": 0.91}],
                        "skeleton_confidence": 0.88,
                    },
                )
            ],
        )

        merged = ResultPublisherService._merge_objects(base_objects, snapshot)

        self.assertEqual(len(merged), 1)
        pose = merged[0].pose
        self.assertIsNotNone(pose)
        self.assertEqual(pose["debug"]["rejected_reason"], "pose_track_mismatch")
        self.assertEqual(pose["track_id"], 9)
        self.assertEqual(pose["source_track_id"], 9)
        self.assertEqual(pose["keypoints"], [])

    def test_merge_objects_keeps_matching_pose_track(self) -> None:
        base_objects = [
            DetectedObject(
                label="person",
                confidence=0.95,
                bbox=[100.0, 120.0, 300.0, 420.0],
                track_id=7,
            )
        ]
        snapshot = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=1280,
            frame_height=720,
            timestamp="2026-06-17T01:00:00Z",
            monotonic_at=0.0,
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.95,
                    bbox=[100.0, 120.0, 300.0, 420.0],
                    track_id=7,
                    pose={
                        "track_id": 7,
                        "source_track_id": 7,
                        "source_bbox": [100.0, 120.0, 300.0, 420.0],
                        "pose_bbox": [118.0, 132.0, 282.0, 402.0],
                        "pose_frame_seq": 10,
                        "pose_timestamp": "2026-06-17T01:00:00Z",
                        "keypoints": [{"name": "nose", "x": 160.0, "y": 180.0, "confidence": 0.91}],
                        "skeleton_confidence": 0.88,
                    },
                )
            ],
        )

        merged = ResultPublisherService._merge_objects(base_objects, snapshot)

        self.assertEqual(len(merged), 1)
        pose = merged[0].pose
        self.assertIsNotNone(pose)
        self.assertEqual(pose["track_id"], 7)
        self.assertEqual(pose["source_track_id"], 7)
        self.assertEqual(len(pose["keypoints"]), 1)

    def test_build_result_reuses_fresh_pose_with_publish_delta_window(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=True,
            pose_provider="mock",
            pose_result_ttl_ms=1000,
            pose_max_tracking_frame_delta=2,
            pose_publish_max_frame_delta=8,
            enable_temporal=False,
        )
        realtime_store = RealtimeResultStore()
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=realtime_store,
            result_channels=_ResultChannelSpy(),
        )
        now = time.monotonic()
        tracking_object = DetectedObject(
            label="person",
            confidence=0.95,
            bbox=[100.0, 120.0, 300.0, 420.0],
            track_id=7,
            is_target=True,
        )
        realtime_store.update_tracking(
            ObjectSnapshot(
                camera_id="camera_01",
                frame_seq=18,
                frame_width=1280,
                frame_height=720,
                timestamp="2026-06-17T01:00:01Z",
                monotonic_at=now,
                objects=[tracking_object],
            )
        )
        realtime_store.update_pose(
            ObjectSnapshot(
                camera_id="camera_01",
                frame_seq=10,
                frame_width=1280,
                frame_height=720,
                timestamp="2026-06-17T01:00:00Z",
                monotonic_at=now,
                objects=[
                    tracking_object.model_copy(
                        update={
                            "pose": {
                                "track_id": 7,
                                "source_track_id": 7,
                                "source_bbox": [100.0, 120.0, 300.0, 420.0],
                                "pose_bbox": [118.0, 132.0, 282.0, 402.0],
                                "pose_frame_seq": 10,
                                "pose_timestamp": "2026-06-17T01:00:00Z",
                                "pose_quality_level": "valid",
                                "keypoints": [
                                    {"name": "nose", "x": 160.0, "y": 180.0, "confidence": 0.91}
                                ],
                                "skeleton_confidence": 0.88,
                            }
                        }
                    )
                ],
            )
        )

        result = publisher._build_result("camera_01")

        self.assertIsNotNone(result)
        pose = result.objects[0].pose
        self.assertIsNotNone(pose)
        self.assertEqual(pose["track_id"], 7)
        self.assertEqual(pose["pose_frame_seq"], 10)

    def test_confirmed_fall_is_persisted_before_publication(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = replace(
                Settings(),
                result_publish_fps=12.0,
                main_system_alert_enabled=False,
                vision_service_public_base_url="http://testserver",
                fall_event_snapshot_dir=temp_dir,
            )
            realtime_store = RealtimeResultStore()
            channel_spy = _ResultChannelSpy()
            reporter = FallEventReporterService(settings=settings, source_manager=_StubSourceManager())
            reporter._save_snapshot = lambda camera_id, track_id, timestamp_slug: (  # type: ignore[method-assign]
                f"http://testserver/fall-events/snapshots/{camera_id}_{track_id}_{timestamp_slug}.jpg",
                f"{temp_dir}\\{camera_id}_{track_id}_{timestamp_slug}.jpg",
            )
            publisher = ResultPublisherService(
                settings=settings,
                realtime_store=realtime_store,
                result_channels=channel_spy,
                fall_event_reporter=reporter,
            )

            stop_event = Event()
            confirmed_result = self._confirmed_result()

            def build_result(camera_id: str) -> VisionResult:
                self.assertEqual(camera_id, "camera_01")
                stop_event.set()
                return confirmed_result

            publisher._build_result = build_result  # type: ignore[method-assign]
            publisher._run_loop("camera_01", stop_event)

            stored = realtime_store.latest_published("camera_01")
            self.assertIsNotNone(stored)
            stored_person = next(item for item in stored.objects if item.label == "person")
            stored_metadata = (stored_person.temporal or {}).get("event_metadata") or {}
            self.assertIsInstance(stored_metadata.get("incident_id"), str)
            self.assertIsInstance(stored_metadata.get("snapshot_url"), str)
            self.assertIsInstance(stored_metadata.get("snapshot_path"), str)

            self.assertEqual(len(channel_spy.payloads), 1)
            published_person = next(item for item in channel_spy.payloads[0]["objects"] if item["label"] == "person")
            published_metadata = ((published_person.get("temporal") or {}).get("event_metadata")) or {}
            self.assertEqual(published_metadata.get("incident_id"), stored_metadata.get("incident_id"))
            self.assertEqual(published_metadata.get("snapshot_url"), stored_metadata.get("snapshot_url"))
            self.assertEqual(published_metadata.get("snapshot_path"), stored_metadata.get("snapshot_path"))

            latest_alert = reporter.latest_alert("camera_01")
            self.assertIsNotNone(latest_alert)
            self.assertEqual(latest_alert["incident_id"], stored_metadata.get("incident_id"))

    def test_confirmed_fall_dry_run_does_not_http_post(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = replace(
                Settings(),
                result_publish_fps=12.0,
                main_system_alert_enabled=True,
                main_system_report_dry_run=True,
                vision_service_public_base_url="http://testserver",
                fall_event_snapshot_dir=temp_dir,
            )
            realtime_store = RealtimeResultStore()
            channel_spy = _ResultChannelSpy()
            reporter = FallEventReporterService(settings=settings, source_manager=_StubSourceManager())
            reporter._save_snapshot = lambda camera_id, track_id, timestamp_slug: (  # type: ignore[method-assign]
                f"http://testserver/fall-events/snapshots/{camera_id}_{track_id}_{timestamp_slug}.jpg",
                f"{temp_dir}\\{camera_id}_{track_id}_{timestamp_slug}.jpg",
            )
            publisher = ResultPublisherService(
                settings=settings,
                realtime_store=realtime_store,
                result_channels=channel_spy,
                fall_event_reporter=reporter,
            )
            calls: list[dict] = []

            def fake_post(*args, **kwargs):
                calls.append({"args": args, "kwargs": kwargs})
                raise AssertionError("dry-run must not call HTTP POST")

            stop_event = Event()
            confirmed_result = self._confirmed_result()

            def build_result(camera_id: str) -> VisionResult:
                self.assertEqual(camera_id, "camera_01")
                stop_event.set()
                return confirmed_result

            previous_post = reporter_module.requests.post
            reporter_module.requests.post = fake_post
            try:
                publisher._build_result = build_result  # type: ignore[method-assign]
                publisher._run_loop("camera_01", stop_event)
                queued = reporter._queue.get_nowait()  # type: ignore[attr-defined]
                reporter._post_payload(queued)  # type: ignore[attr-defined]
            finally:
                reporter_module.requests.post = previous_post

            self.assertEqual(calls, [])
            self.assertEqual(reporter.status()["last_post_status"], "dry_run_skipped")
            stored = realtime_store.latest_published("camera_01")
            self.assertIsNotNone(stored)
            latest_alert = reporter.latest_alert("camera_01")
            self.assertIsNotNone(latest_alert)
            self.assertEqual(len(channel_spy.payloads), 1)

    def test_detector_only_confirm_requires_person_evidence(self) -> None:
        settings = replace(
            Settings(),
            fall_detector_confirm_enabled=True,
            fall_detector_confirm_frames=1,
            fall_detector_confirm_ms=0,
            fall_detector_confirm_min_probability=0.32,
            fall_detector_confirm_min_person_confidence=0.2,
        )
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        base_objects = [
            DetectedObject(
                label="person",
                confidence=0.91,
                bbox=[100.0, 120.0, 300.0, 420.0],
                track_id=1,
            )
        ]
        fall_objects = [
            DetectedObject(
                label="fall",
                confidence=0.88,
                bbox=[102.0, 122.0, 302.0, 422.0],
            )
        ]

        merged = publisher._merge_fall_detection(  # type: ignore[attr-defined]
            "camera_01",
            base_objects,
            fall_objects,
            [],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].fall_decision["fall_state"], "fallen_candidate")
        self.assertFalse(merged[0].alarm_preview["confirmed"])
        self.assertEqual(merged[0].fall_decision["rejected_reason"], "detector_only_no_person_evidence")
        self.assertFalse(merged[0].fall_decision["person_evidence"])

    def test_detector_only_confirm_does_not_treat_pose_placeholder_as_person_evidence(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=False,
            pose_provider="disabled_placeholder",
            fall_detector_confirm_enabled=True,
            fall_detector_confirm_frames=1,
            fall_detector_confirm_ms=0,
            fall_detector_confirm_min_probability=0.32,
            fall_detector_confirm_min_person_confidence=0.2,
        )
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        base_objects = [
            DetectedObject(
                label="person",
                confidence=0.91,
                bbox=[100.0, 120.0, 300.0, 420.0],
                track_id=1,
                pose={
                    "pose_provider": "disabled_placeholder",
                    "keypoints": [],
                    "debug": {"pose_disabled": True, "placeholder": True},
                },
            )
        ]
        fall_objects = [
            DetectedObject(
                label="fall",
                confidence=0.88,
                bbox=[102.0, 122.0, 302.0, 422.0],
            )
        ]

        merged = publisher._merge_fall_detection(  # type: ignore[attr-defined]
            "camera_01",
            base_objects,
            fall_objects,
            [],
        )

        self.assertEqual(merged[0].fall_decision["rejected_reason"], "detector_only_no_person_evidence")

    def test_detector_only_confirm_blocks_upright_fall_label(self) -> None:
        settings = replace(
            Settings(),
            fall_detector_confirm_enabled=True,
            fall_detector_confirm_frames=1,
            fall_detector_confirm_ms=0,
            fall_detector_confirm_min_probability=0.32,
            fall_detector_confirm_min_person_confidence=0.2,
        )
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        base_objects = [
            DetectedObject(
                label="person",
                confidence=0.91,
                bbox=[260.0, 50.0, 380.0, 320.0],
                track_id=5,
            )
        ]
        person_objects = [
            DetectedObject(
                label="person",
                confidence=0.94,
                bbox=[262.0, 52.0, 382.0, 322.0],
            )
        ]
        fall_objects = [
            DetectedObject(
                label="fall",
                confidence=0.88,
                bbox=[262.0, 52.0, 382.0, 322.0],
            )
        ]

        merged = publisher._merge_fall_detection(  # type: ignore[attr-defined]
            "camera_01",
            base_objects,
            fall_objects,
            person_objects,
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].fall_decision["fall_state"], "fallen_candidate")
        self.assertFalse(merged[0].alarm_preview["confirmed"])
        self.assertEqual(merged[0].fall_decision["rejected_reason"], "detector_only_upright_guard")
        debug = merged[0].fall_decision["detector_only_debug"]
        self.assertTrue(debug["upright_guard_required"])
        self.assertFalse(debug["upright_guard_pass"])
        self.assertFalse(debug["low_posture_evidence"])

    def test_detector_only_confirm_blocks_upright_fallen_label(self) -> None:
        settings = replace(
            Settings(),
            fall_detector_confirm_enabled=True,
            fall_detector_confirm_frames=1,
            fall_detector_confirm_ms=0,
            fall_detector_confirm_min_probability=0.32,
            fall_detector_confirm_min_person_confidence=0.2,
        )
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        base_objects = [
            DetectedObject(
                label="person",
                confidence=0.91,
                bbox=[260.0, 50.0, 380.0, 320.0],
                track_id=5,
            )
        ]
        person_objects = [
            DetectedObject(
                label="person",
                confidence=0.94,
                bbox=[262.0, 52.0, 382.0, 322.0],
            )
        ]
        fall_objects = [
            DetectedObject(
                label="fallen",
                confidence=0.88,
                bbox=[262.0, 52.0, 382.0, 322.0],
            )
        ]

        merged = publisher._merge_fall_detection(  # type: ignore[attr-defined]
            "camera_01",
            base_objects,
            fall_objects,
            person_objects,
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].fall_decision["fall_state"], "fallen_candidate")
        self.assertFalse(merged[0].alarm_preview["confirmed"])
        self.assertEqual(merged[0].fall_decision["rejected_reason"], "detector_only_upright_guard")
        debug = merged[0].fall_decision["detector_only_debug"]
        self.assertTrue(debug["upright_guard_required"])
        self.assertFalse(debug["upright_guard_pass"])
        self.assertFalse(debug["low_posture_evidence"])

    def test_detector_only_confirm_allows_fall_label_with_low_posture_evidence(self) -> None:
        settings = replace(
            Settings(),
            fall_detector_confirm_enabled=True,
            fall_detector_confirm_frames=1,
            fall_detector_confirm_ms=0,
            fall_detector_confirm_min_probability=0.32,
            fall_detector_confirm_min_person_confidence=0.2,
        )
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        base_objects = [
            DetectedObject(
                label="person",
                confidence=0.91,
                bbox=[100.0, 210.0, 340.0, 340.0],
                track_id=6,
                temporal={"low_posture": True},
            )
        ]
        person_objects = [
            DetectedObject(
                label="person",
                confidence=0.94,
                bbox=[102.0, 212.0, 342.0, 342.0],
            )
        ]
        fall_objects = [
            DetectedObject(
                label="fall",
                confidence=0.88,
                bbox=[102.0, 212.0, 342.0, 342.0],
            )
        ]

        merged = publisher._merge_fall_detection(  # type: ignore[attr-defined]
            "camera_01",
            base_objects,
            fall_objects,
            person_objects,
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].fall_decision["fall_state"], "fallen_confirmed")
        self.assertTrue(merged[0].alarm_preview["confirmed"])

    def test_detector_only_confirm_blocks_sitting_like_fallen_label(self) -> None:
        settings = replace(
            Settings(),
            fall_detector_confirm_enabled=True,
            fall_detector_confirm_frames=1,
            fall_detector_confirm_ms=0,
            fall_detector_confirm_min_probability=0.32,
            fall_detector_confirm_min_person_confidence=0.2,
        )
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        base_objects = [
            DetectedObject(
                label="person",
                confidence=0.91,
                bbox=[100.0, 180.0, 330.0, 350.0],
                track_id=9,
                behavior={"behavior_state": "sitting"},
            )
        ]
        person_objects = [
            DetectedObject(
                label="person",
                confidence=0.94,
                bbox=[102.0, 182.0, 332.0, 352.0],
            )
        ]
        fall_objects = [
            DetectedObject(
                label="fallen",
                confidence=0.88,
                bbox=[102.0, 182.0, 332.0, 352.0],
            )
        ]

        merged = publisher._merge_fall_detection(  # type: ignore[attr-defined]
            "camera_01",
            base_objects,
            fall_objects,
            person_objects,
        )

        self.assertEqual(merged[0].fall_decision["fall_state"], "fallen_candidate")
        self.assertFalse(merged[0].alarm_preview["confirmed"])
        self.assertEqual(merged[0].fall_decision["rejected_reason"], "detector_only_adl_like_guard")
        self.assertTrue(merged[0].fall_decision["detector_only_debug"]["adl_like_guard_active"])
        debug = merged[0].fall_decision["detector_only_debug"]
        self.assertTrue(debug["upright_guard_required"])
        self.assertTrue(debug["upright_guard_pass"])
        self.assertFalse(debug["detector_only_guard_pass"])

    def test_build_result_ignores_frame_misaligned_fall_detection(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=False,
            pose_provider="disabled_placeholder",
            enable_temporal=False,
            field_fall_candidate_enabled=False,
            fall_detector_confirm_enabled=True,
            fall_detector_confirm_frames=1,
            fall_detector_confirm_ms=0,
            fall_detector_confirm_min_probability=0.32,
            fall_detector_confirm_min_person_confidence=0.2,
        )
        realtime_store = RealtimeResultStore()
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=realtime_store,
            result_channels=_ResultChannelSpy(),
        )
        now = time.monotonic()
        person = DetectedObject(
            label="person",
            confidence=0.94,
            bbox=[260.0, 50.0, 380.0, 320.0],
            track_id=5,
            is_target=True,
        )
        detection = DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=30,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-21T09:00:00Z",
            monotonic_at=now,
            frame=None,  # type: ignore[arg-type]
            objects=[person],
            detector={"name": "person"},
        )
        tracking = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=30,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-21T09:00:00Z",
            monotonic_at=now,
            objects=[person],
        )
        old_fall_detection = DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=20,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-21T08:59:59Z",
            monotonic_at=now,
            frame=None,  # type: ignore[arg-type]
            objects=[
                DetectedObject(
                    label="fallen",
                    confidence=0.91,
                    bbox=[260.0, 50.0, 380.0, 320.0],
                )
            ],
            detector={"name": "fall"},
        )
        realtime_store.update_detection(detection)
        realtime_store.update_tracking(tracking)
        realtime_store.update_fall_detection(old_fall_detection)

        result = publisher._build_result("camera_01")  # type: ignore[attr-defined]

        self.assertIsNotNone(result)
        published_person = next(item for item in result.objects if item.label == "person")
        self.assertIsNone(published_person.fall_decision)
        self.assertIsNone(published_person.alarm_preview)
        self.assertEqual(result.detector["fall_detector_skipped"]["reason"], "stale_or_frame_misaligned")

    def test_field_confirm_blocked_when_no_current_fall_object(self) -> None:
        settings = replace(
            Settings(),
            field_fall_candidate_confirm_frames=1,
            field_fall_candidate_confirm_ms=0,
        )
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        publisher._fall_hint_seen_at["camera_01"] = time.monotonic()
        item = self._field_candidate_object(track_id=11)

        merged = publisher._merge_field_fall_candidates(  # type: ignore[attr-defined]
            "camera_01",
            [item],
            640,
            360,
            [],
            [self._person_detection_object()],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].fall_decision["fall_state"], "fallen_candidate")
        self.assertFalse(merged[0].alarm_preview["confirmed"])
        self.assertEqual(
            merged[0].fall_decision["rejected_reason"],
            "field_recent_hint_blocked_no_current_fall_object",
        )
        debug = merged[0].temporal["field_rule_debug"]
        self.assertFalse(debug["has_current_fall_object"])
        self.assertIn("has_current_fall_object", debug["missing_conditions"])

    def test_field_confirm_requires_stable_person_evidence_not_only_grid_key(self) -> None:
        settings = replace(
            Settings(),
            field_fall_candidate_confirm_frames=2,
            field_fall_candidate_confirm_ms=0,
        )
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        publisher._fall_hint_seen_at["camera_01"] = time.monotonic()
        fall_objects = [self._strong_fall_object()]
        person_objects = [self._person_detection_object()]

        first = publisher._merge_field_fall_candidates(  # type: ignore[attr-defined]
            "camera_01",
            [self._field_candidate_object(track_id=21)],
            640,
            360,
            fall_objects,
            person_objects,
        )[0]
        second = publisher._merge_field_fall_candidates(  # type: ignore[attr-defined]
            "camera_01",
            [self._field_candidate_object(track_id=22)],
            640,
            360,
            fall_objects,
            person_objects,
        )[0]

        self.assertFalse(first.alarm_preview["confirmed"])
        self.assertFalse(second.alarm_preview["confirmed"])
        self.assertEqual(
            second.fall_decision["rejected_reason"],
            "awaiting_field_confirm_frames_or_duration",
        )
        self.assertEqual(
            sorted(publisher._field_candidate_states.keys()),
            [
                "camera_01:field-fall:21:1:2",
                "camera_01:field-fall:22:1:2",
            ],
        )

    def test_sitting_like_low_posture_does_not_confirm_from_stale_recent_hint(self) -> None:
        settings = replace(
            Settings(),
            field_fall_candidate_confirm_frames=1,
            field_fall_candidate_confirm_ms=0,
        )
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        publisher._fall_hint_seen_at["camera_01"] = time.monotonic()
        item = self._field_candidate_object(
            track_id=31,
            behavior={"behavior_state": "sitting"},
        )

        merged = publisher._merge_field_fall_candidates(  # type: ignore[attr-defined]
            "camera_01",
            [item],
            640,
            360,
            [DetectedObject(label="lying", confidence=0.74, bbox=[102.0, 202.0, 342.0, 342.0])],
            [self._person_detection_object()],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].fall_decision["fall_state"], "fallen_candidate")
        self.assertFalse(merged[0].alarm_preview["confirmed"])
        self.assertEqual(
            merged[0].fall_decision["rejected_reason"],
            "field_confirm_blocked_adl_like_posture",
        )
        debug = merged[0].fall_decision["field_rule_debug"]
        self.assertTrue(debug["has_current_fall_object"])
        self.assertFalse(debug["has_current_strong_fall_object"])
        self.assertIn("adl_like_posture", debug["missing_conditions"])

    def test_field_rules_not_met_includes_missing_conditions(self) -> None:
        settings = replace(Settings())
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            result_channels=_ResultChannelSpy(),
        )
        item = self._field_candidate_object(
            track_id=41,
            bbox=[100.0, 20.0, 190.0, 200.0],
            temporal={
                "window_size": 8,
                "features": {
                    "aspect_ratio": 0.375,
                    "speed": 55.0,
                    "pose_available": False,
                },
                "bbox_aspect_ratio": 0.375,
                "velocity_y": 12.0,
                "stillness": False,
                "low_posture": False,
            },
        )

        merged = publisher._merge_field_fall_candidates(  # type: ignore[attr-defined]
            "camera_01",
            [item],
            640,
            360,
            [],
            [self._person_detection_object()],
        )

        self.assertEqual(len(merged), 1)
        self.assertIsNone(merged[0].fall_decision)
        debug = merged[0].temporal["field_rule_debug"]
        self.assertEqual(debug["drop_reason"], "field_rules_not_met")
        self.assertIn("has_recent_strong_hint", debug["missing_conditions"])
        self.assertIn("aspect_pass", debug["missing_conditions"])
        self.assertIn("center_y_pass", debug["missing_conditions"])
        self.assertIn("window_size_pass", debug["missing_conditions"])
        self.assertIn("speed_pass", debug["missing_conditions"])

    @staticmethod
    def _confirmed_result() -> VisionResult:
        return VisionResult(
            camera_id="camera_01",
            timestamp="2026-06-17T00:28:28Z",
            frame_seq=123,
            frame_width=1280,
            frame_height=720,
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.95,
                    bbox=[100.0, 120.0, 300.0, 420.0],
                    track_id=7,
                    temporal={"window_size": 16},
                    fall_decision={
                        "fall_state": "fallen_confirmed",
                        "risk_level": "critical",
                        "fall_probability": 0.94,
                    },
                    alarm_preview={
                        "confirmed": True,
                        "risk_level": "critical",
                        "fall_probability": 0.94,
                    },
                )
            ],
            detector={"fall_detector": "stub"},
        )

    @staticmethod
    def _field_candidate_object(
        track_id: int | None,
        bbox: list[float] | None = None,
        temporal: dict | None = None,
        behavior: dict | None = None,
    ) -> DetectedObject:
        default_bbox = [100.0, 200.0, 340.0, 340.0]
        default_temporal = {
            "window_size": 20,
            "features": {
                "aspect_ratio": 1.7143,
                "speed": 0.0,
                "pose_available": True,
            },
            "bbox_aspect_ratio": 1.7143,
            "body_angle": 18.0,
            "low_posture": True,
            "stillness": True,
            "velocity_y": 0.0,
            "candidate_duration_ms": 0,
            "confirm_duration_ms": 0,
        }
        return DetectedObject(
            label="person",
            confidence=0.92,
            bbox=bbox or default_bbox,
            track_id=track_id,
            temporal=temporal or default_temporal,
            behavior=behavior,
        )

    @staticmethod
    def _person_detection_object() -> DetectedObject:
        return DetectedObject(
            label="person",
            confidence=0.94,
            bbox=[100.0, 200.0, 340.0, 340.0],
        )

    @staticmethod
    def _strong_fall_object() -> DetectedObject:
        return DetectedObject(
            label="fall",
            confidence=0.86,
            bbox=[102.0, 202.0, 342.0, 342.0],
        )


if __name__ == "__main__":
    unittest.main()
