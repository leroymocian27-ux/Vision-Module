from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import cv2


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
OUTPUT_DIR = ROOT / "logs" / "offline_fall_eval"


def configure_offline_environment() -> None:
    defaults = {
        "VISION_SERVICE_RUNTIME_PROFILE": "offline_fall_video_eval",
        "ENABLE_TRACKING": "true",
        "ENABLE_POSE": "true",
        "POSE_PROVIDER": "yolo",
        "ENABLE_BEHAVIOR": "true",
        "ENABLE_TEMPORAL": "true",
        "TEMPORAL_TRACK_MODE": "all_tracks",
        "TEMPORAL_SEQUENCE_KEY_MODE": "spatial",
        "TEMPORAL_MODEL_PROVIDER": "shadow",
        "POSE_FALLBACK_TO_DETECTION": "true",
        "POSE_FALLBACK_MIN_CONFIDENCE": "0.15",
        "MAIN_SYSTEM_ALERT_ENABLED": "false",
        "VISION_SERVICE_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
        "FALL_EVENT_SNAPSHOT_DIR": str((OUTPUT_DIR / "snapshots").resolve()),
        "TEMPORAL_ONNX_PROVIDERS": "CUDAExecutionProvider,CPUExecutionProvider",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


configure_offline_environment()

from app.core.config import get_settings
from app.detection.realtime_result_store import DetectionSnapshot, ObjectSnapshot, RealtimeResultStore
from app.detection.yolo_fall_detector import YoloFallDetector
from app.detection.object_detector import YoloPersonDetector
from app.schemas.common import utc_now_iso
from app.schemas.vision_result import DetectedObject, VisionResult
from app.fall.fusion import FallFusionService
from app.services.behavior_service import BehaviorService
from app.services.fall_event_reporter_service import FallEventReporterService
from app.services.pose_service import PoseService
from app.services.result_publisher_service import ResultPublisherService
from app.services.temporal_service import TemporalService
from app.services.tracking_service import TrackingService
from app.streaming.result_channel_manager import ResultChannelManager


@dataclass
class FramePacket:
    camera_id: str
    seq: int
    frame: Any
    width: int
    height: int


class FakeFrameBuffer:
    def __init__(self) -> None:
        self._packet: FramePacket | None = None

    def set_latest(self, packet: FramePacket) -> None:
        self._packet = packet

    def latest(self) -> FramePacket | None:
        return self._packet


class FakeSourceManager:
    def __init__(self) -> None:
        self._buffers: dict[str, FakeFrameBuffer] = {}

    def get_buffer(self, camera_id: str) -> FakeFrameBuffer:
        return self._buffers.setdefault(camera_id, FakeFrameBuffer())

    def update_frame(self, camera_id: str, frame_seq: int, frame: Any) -> None:
        height, width = frame.shape[:2]
        self.get_buffer(camera_id).set_latest(
            FramePacket(
                camera_id=camera_id,
                seq=frame_seq,
                frame=frame,
                width=width,
                height=height,
            )
        )


class SimulatedClock:
    def __init__(self, start: float = 1000.0) -> None:
        self._now = float(start)

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += max(float(seconds), 1e-6)


@dataclass
class VideoSummary:
    video: str
    frame_count: int
    processed_frames: int
    fps: float
    duration_ms: int
    person_detection: str
    tracking: str
    pose: str
    fall_confirm: str
    incident_id: str | None
    block_point: str
    fall_state_peak: str | None
    max_person_count: int
    max_tracked_objects: int
    pose_success_frames: int
    alarm_confirmed_frames: int
    confirmed_frames: int
    first_confirmed_frame: int | None
    first_confirmed_timestamp_ms: int | None
    first_incident_id_frame: int | None
    snapshot_path: str | None
    snapshot_url: str | None
    latest_result_consumable: bool
    manifest_label: str | None = None
    expected_alarm: bool | None = None
    fall_start_ms: int | None = None
    fall_end_ms: int | None = None
    allowed_confirm_after_ms: int | None = None
    scene_type: str | None = None
    support_surface: str | None = None
    hard_negative_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "video": self.video,
            "frame_count": self.frame_count,
            "processed_frames": self.processed_frames,
            "fps": self.fps,
            "duration_ms": self.duration_ms,
            "person_detection": self.person_detection,
            "tracking": self.tracking,
            "pose": self.pose,
            "fall_confirm": self.fall_confirm,
            "incident_id": self.incident_id,
            "block_point": self.block_point,
            "fall_state_peak": self.fall_state_peak,
            "max_person_count": self.max_person_count,
            "max_tracked_objects": self.max_tracked_objects,
            "pose_success_frames": self.pose_success_frames,
            "alarm_confirmed_frames": self.alarm_confirmed_frames,
            "confirmed_frames": self.confirmed_frames,
            "first_confirmed_frame": self.first_confirmed_frame,
            "first_confirmed_timestamp_ms": self.first_confirmed_timestamp_ms,
            "first_incident_id_frame": self.first_incident_id_frame,
            "snapshot_path": self.snapshot_path,
            "snapshot_url": self.snapshot_url,
            "latest_result_consumable": self.latest_result_consumable,
            "manifest_label": self.manifest_label,
            "expected_alarm": self.expected_alarm,
            "fall_start_ms": self.fall_start_ms,
            "fall_end_ms": self.fall_end_ms,
            "allowed_confirm_after_ms": self.allowed_confirm_after_ms,
            "scene_type": self.scene_type,
            "support_surface": self.support_surface,
            "hard_negative_type": self.hard_negative_type,
        }


@dataclass(frozen=True)
class VideoEvalCase:
    path: Path
    video_id: str | None = None
    label: str | None = None
    expected_alarm: bool | None = None
    fall_start_ms: int | None = None
    fall_end_ms: int | None = None
    allowed_confirm_after_ms: int | None = None
    scene_type: str | None = None
    support_surface: str | None = None
    hard_negative_type: str | None = None


class OfflineFallVideoEvaluator:
    def __init__(self, output_dir: Path, camera_id: str, frame_stride: int) -> None:
        self.output_dir = output_dir
        self.camera_id = camera_id
        self.frame_stride = max(1, frame_stride)
        self.settings = get_settings()
        self.detector = YoloPersonDetector(self.settings)
        self.fall_detector = YoloFallDetector(self.settings)
        self.tracking = TrackingService(self.settings)
        self.pose = PoseService(self.settings)
        self.behavior = BehaviorService(self.settings)
        self.temporal = TemporalService(self.settings)
        self.fall_fusion = FallFusionService(self.settings)
        self.result_store = RealtimeResultStore()
        self.result_channels = ResultChannelManager()
        self.source_manager = FakeSourceManager()
        self.event_reporter = FallEventReporterService(self.settings, self.source_manager)
        self.publisher = ResultPublisherService(
            settings=self.settings,
            realtime_store=self.result_store,
            result_channels=self.result_channels,
            temporal_service=self.temporal,
            fall_fusion_service=self.fall_fusion,
            fall_event_reporter=self.event_reporter,
        )

    def evaluate_videos(self, videos: list[Path]) -> list[VideoSummary]:
        return self.evaluate_cases([VideoEvalCase(path=video) for video in videos])

    def evaluate_cases(self, cases: list[VideoEvalCase]) -> list[VideoSummary]:
        summaries: list[VideoSummary] = []
        for case in cases:
            summaries.append(self.evaluate_video(case.path, case=case))
        return summaries

    def evaluate_video(self, video_path: Path, case: VideoEvalCase | None = None) -> VideoSummary:
        self._reset_services()
        video_slug = safe_slug(video_path.stem)
        video_camera_id = f"{self.camera_id}_{video_slug}"
        frames_csv = self.output_dir / f"offline_eval_{video_slug}_frames.csv"
        frames_jsonl = self.output_dir / f"offline_eval_{video_slug}_frames.jsonl"
        summary_json = self.output_dir / f"offline_eval_{video_slug}_summary.json"

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"could not open video: {video_path}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 0:
            fps = 25.0
        frame_duration = 1.0 / fps
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration_ms = int(round(frame_count * 1000 / fps)) if frame_count > 0 else 0

        rows: list[dict[str, Any]] = []
        pose_success_frames = 0
        confirmed_frames = 0
        alarm_confirmed_frames = 0
        max_person_count = 0
        max_tracked_objects = 0
        incident_id: str | None = None
        snapshot_path: str | None = None
        snapshot_url: str | None = None
        latest_result_consumable = False
        first_confirmed_frame: int | None = None
        first_confirmed_timestamp_ms: int | None = None
        first_incident_id_frame: int | None = None

        clock = SimulatedClock()
        frame_index = 0

        with ExitStack() as stack:
            self._patch_time(stack, clock)
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_index % self.frame_stride != 0:
                    frame_index += 1
                    clock.advance(frame_duration)
                    continue
                row = self._process_frame(
                    camera_id=video_camera_id,
                    video_name=video_path.name,
                    frame_index=frame_index,
                    timestamp_ms=int(round(frame_index * 1000 / fps)),
                    frame=frame,
                    frame_monotonic=clock.monotonic(),
                    case=case,
                )
                rows.append(row)
                max_person_count = max(max_person_count, int(row["latest_raw_person_count"]))
                max_tracked_objects = max(max_tracked_objects, int(row["tracked_objects_count"]))
                if row["pose_success"]:
                    pose_success_frames += 1
                if row["alarm_confirmed"]:
                    alarm_confirmed_frames += 1
                if row["fall_state"] == "fallen_confirmed":
                    confirmed_frames += 1
                    if first_confirmed_frame is None:
                        first_confirmed_frame = frame_index
                        first_confirmed_timestamp_ms = int(row["timestamp_ms"])
                if row["incident_id"]:
                    incident_id = str(row["incident_id"])
                    snapshot_path = row["snapshot_path"] or snapshot_path
                    snapshot_url = row["snapshot_url"] or snapshot_url
                    latest_result_consumable = bool(
                        row["camera_id"]
                        and row["fall_state"] == "fallen_confirmed"
                        and row["alarm_confirmed"]
                        and row["incident_id"]
                    )
                    if first_incident_id_frame is None:
                        first_incident_id_frame = frame_index
                frame_index += 1
                clock.advance(frame_duration)

        cap.release()

        write_frame_outputs(frames_csv, frames_jsonl, rows)
        summary = build_video_summary(
            video_path=video_path,
            case=case,
            frame_count=frame_count or frame_index,
            processed_frames=len(rows),
            fps=fps,
            duration_ms=duration_ms,
            rows=rows,
            max_person_count=max_person_count,
            max_tracked_objects=max_tracked_objects,
            pose_success_frames=pose_success_frames,
            alarm_confirmed_frames=alarm_confirmed_frames,
            confirmed_frames=confirmed_frames,
            first_confirmed_frame=first_confirmed_frame,
            first_confirmed_timestamp_ms=first_confirmed_timestamp_ms,
            first_incident_id_frame=first_incident_id_frame,
            incident_id=incident_id,
            snapshot_path=snapshot_path,
            snapshot_url=snapshot_url,
            latest_result_consumable=latest_result_consumable,
        )
        summary_json.write_text(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    def _process_frame(
        self,
        *,
        camera_id: str,
        video_name: str,
        frame_index: int,
        timestamp_ms: int,
        frame: Any,
        frame_monotonic: float,
        case: VideoEvalCase | None,
    ) -> dict[str, Any]:
        frame_height, frame_width = frame.shape[:2]
        self.source_manager.update_frame(camera_id, frame_index, frame)

        detection_started = time.perf_counter()
        detected = self.detector.detect(frame)
        person_latency_ms = round((time.perf_counter() - detection_started) * 1000, 2)

        fall_started = time.perf_counter()
        fall_detected = self.fall_detector.detect(frame)
        fall_latency_ms = round((time.perf_counter() - fall_started) * 1000, 2)

        self.result_store.update_detection(
            DetectionSnapshot(
                camera_id=camera_id,
                frame_seq=frame_index,
                frame_width=frame_width,
                frame_height=frame_height,
                timestamp=utc_now_iso(),
                monotonic_at=frame_monotonic,
                frame=frame,
                objects=detected,
                detector={
                    "name": "ultralytics_yolo",
                    "mode": "person_detect",
                    "latency_ms": person_latency_ms,
                },
            )
        )
        self.result_store.update_fall_detection(
            DetectionSnapshot(
                camera_id=camera_id,
                frame_seq=frame_index,
                frame_width=frame_width,
                frame_height=frame_height,
                timestamp=utc_now_iso(),
                monotonic_at=frame_monotonic,
                frame=frame,
                objects=fall_detected,
                detector={
                    "name": "ultralytics_yolo_fall",
                    "mode": "fall_detect",
                    "latency_ms": fall_latency_ms,
                    "model_name": self.fall_detector.status().model_name,
                },
            )
        )

        tracking_objects = self.tracking.enrich(camera_id, detected, frame=frame)
        tracking_objects = self._attach_scene_context(tracking_objects, case)
        self.result_store.update_tracking(
            ObjectSnapshot(
                camera_id=camera_id,
                frame_seq=frame_index,
                frame_width=frame_width,
                frame_height=frame_height,
                timestamp=utc_now_iso(),
                monotonic_at=frame_monotonic,
                objects=tracking_objects,
            )
        )

        pose_objects = self.pose.enrich(
            camera_id,
            frame,
            tracking_objects,
            frame_seq=frame_index,
            tracking_frame_seq=frame_index,
            frame_age_ms=0.0,
        )
        pose_objects = self._attach_scene_context(pose_objects, case)
        if any(obj.pose is not None for obj in pose_objects):
            self.result_store.update_pose(
                ObjectSnapshot(
                    camera_id=camera_id,
                    frame_seq=frame_index,
                    frame_width=frame_width,
                    frame_height=frame_height,
                    timestamp=utc_now_iso(),
                    monotonic_at=frame_monotonic,
                    objects=pose_objects,
                )
            )

        behavior_objects = self.behavior.enrich(camera_id, pose_objects)
        behavior_objects = self._attach_scene_context(behavior_objects, case)
        if any(obj.behavior is not None for obj in behavior_objects):
            self.result_store.update_behavior(
                ObjectSnapshot(
                    camera_id=camera_id,
                    frame_seq=frame_index,
                    frame_width=frame_width,
                    frame_height=frame_height,
                    timestamp=utc_now_iso(),
                    monotonic_at=frame_monotonic,
                    objects=behavior_objects,
                )
            )

        result = self.publisher._build_result(camera_id)
        if result is not None:
            self.event_reporter.inspect_result(result)
            self.result_store.update_published(result)

        return self._frame_row(
            video_name=video_name,
            camera_id=camera_id,
            frame_index=frame_index,
            timestamp_ms=timestamp_ms,
            frame_width=frame_width,
            frame_height=frame_height,
            detected=detected,
            tracking_objects=tracking_objects,
            pose_objects=pose_objects,
            result=result,
            detection_latency_ms=person_latency_ms,
            fall_detection_latency_ms=fall_latency_ms,
        )

    def _frame_row(
        self,
        *,
        video_name: str,
        camera_id: str,
        frame_index: int,
        timestamp_ms: int,
        frame_width: int,
        frame_height: int,
        detected: list[DetectedObject],
        tracking_objects: list[DetectedObject],
        pose_objects: list[DetectedObject],
        result: VisionResult | None,
        detection_latency_ms: float,
        fall_detection_latency_ms: float,
    ) -> dict[str, Any]:
        pose_status = self.pose.status(camera_id).model_dump()
        tracking_status = self.tracking.status(camera_id).model_dump()
        best_person = pick_best_person(result.objects if result is not None else pose_objects)
        event_metadata = object_event_metadata(best_person)
        fall_state = coalesce_text(
            (best_person.fall_decision or {}).get("fall_state") if best_person else None,
            event_metadata.get("status"),
            event_metadata.get("state"),
        )
        alarm_confirmed = bool((best_person.alarm_preview or {}).get("confirmed")) if best_person else False
        fall_prob = best_fall_probability(best_person)
        features = best_person.features if best_person is not None and isinstance(best_person.features, dict) else {}
        fall_hint = features.get("fall_hint") if isinstance(features.get("fall_hint"), dict) else {}
        fusion_debug = best_person.fusion_debug if best_person is not None and isinstance(best_person.fusion_debug, dict) else {}
        temporal = best_person.temporal if best_person is not None and isinstance(best_person.temporal, dict) else {}
        temporal_shadow = temporal.get("shadow") if isinstance(temporal.get("shadow"), dict) else {}
        v6_scores = temporal.get("v6_scores") if isinstance(temporal.get("v6_scores"), dict) else {}
        v6_motion = v6_scores.get("motion") if isinstance(v6_scores.get("motion"), dict) else {}
        v6_fall = v6_scores.get("fall") if isinstance(v6_scores.get("fall"), dict) else {}
        v6_adl = v6_scores.get("adl") if isinstance(v6_scores.get("adl"), dict) else {}
        v6_scene = temporal.get("scene_context") if isinstance(temporal.get("scene_context"), dict) else {}
        fall_decision = best_person.fall_decision if best_person is not None and isinstance(best_person.fall_decision, dict) else {}
        risk_level = coalesce_text(
            (best_person.alarm_preview or {}).get("risk_level") if best_person else None,
            fall_decision.get("risk_level"),
            event_metadata.get("risk_level"),
            event_metadata.get("risk"),
        )
        bbox = [float(value) for value in best_person.bbox] if best_person is not None else None
        pose_success = any(obj.pose is not None for obj in pose_objects)
        pose_attempted = bool(tracking_objects)
        latest_result_incident_id = coalesce_text(
            event_metadata.get("incident_id"),
            (self.event_reporter.latest_alert(camera_id) or {}).get("incident_id"),
        )
        snapshot_url = coalesce_text(
            event_metadata.get("snapshot_url"),
            (self.event_reporter.latest_alert(camera_id) or {}).get("snapshot_url"),
        )
        snapshot_path = coalesce_text(
            event_metadata.get("snapshot_path"),
            (self.event_reporter.latest_alert(camera_id) or {}).get("snapshot_path"),
        )
        return {
            "video_name": video_name,
            "camera_id": camera_id,
            "frame_index": frame_index,
            "timestamp_ms": timestamp_ms,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "latest_raw_person_count": len(detected),
            "tracked_objects_count": len(tracking_objects),
            "selected_track_id": pose_status.get("selected_track_id"),
            "track_id": best_person.track_id if best_person is not None else None,
            "bbox": json.dumps(bbox, ensure_ascii=False) if bbox is not None else "",
            "bbox_area": bbox_area(bbox),
            "pose_attempted": pose_attempted,
            "pose_success": pose_success,
            "pose_rejected_reason": pose_status.get("rejected_reason"),
            "fall_state": fall_state,
            "alarm_confirmed": alarm_confirmed,
            "incident_id": latest_result_incident_id,
            "fall_prob": fall_prob,
            "fall_score": fall_prob,
            "risk_level": risk_level,
            "fall_hint_label": fall_hint.get("strongest_label"),
            "fall_hint_confidence": fall_hint.get("confidence"),
            "fall_hint_iou": fall_hint.get("iou_with_track"),
            "fall_hint_strong": fall_hint.get("strong_hint"),
            "fall_hint_weak": fall_hint.get("weak_hint"),
            "lstm_probability": temporal.get("fall_probability") or temporal_shadow.get("fall_probability"),
            "v6_motion_path": coalesce_text(fall_decision.get("motion_path"), temporal.get("motion_path")),
            "v6_fall_evidence_score": coerce_float(
                fall_decision.get("fall_evidence_score"),
                temporal.get("fall_evidence_score"),
            ),
            "v6_adl_suppression_score": coerce_float(
                fall_decision.get("adl_suppression_score"),
                temporal.get("adl_suppression_score"),
            ),
            "v6_vertical_drop_score": coerce_float(v6_fall.get("vertical_drop_score")),
            "v6_low_posture_score": coerce_float(v6_fall.get("low_posture_score")),
            "v6_post_fall_stillness_score": coerce_float(v6_fall.get("post_fall_stillness_score")),
            "v6_floor_contact_score": coerce_float(v6_fall.get("floor_contact_score")),
            "v6_impact_proxy_score": coerce_float(v6_fall.get("impact_proxy_score")),
            "v6_low_posture_duration_ms": coerce_int(v6_motion.get("low_posture_duration_ms")),
            "v6_track_quality_score": coerce_float(v6_motion.get("track_quality_score")),
            "v6_recovery_score": coerce_float(v6_adl.get("recovery_score")),
            "v6_support_surface_score": coerce_float(v6_adl.get("support_surface_score")),
            "v6_scene_type": v6_scene.get("scene_type"),
            "v6_scene_support_surface": v6_scene.get("support_surface"),
            "v6_scene_support_surface_score": coerce_float(v6_scene.get("support_surface_score")),
            "v6_scene_floor_risk_score": coerce_float(v6_scene.get("floor_risk_score")),
            "v6_suppressed_by_adl": bool(fall_decision.get("suppressed_by_adl") or temporal.get("suppressed_by_adl")),
            "v6_uncertain_review": bool(fall_decision.get("uncertain_review") or temporal.get("uncertain_review")),
            "v6_fall_latched": bool(fall_decision.get("fall_latched") or temporal.get("fall_latched")),
            "v6_decision_reason": json.dumps(
                fall_decision.get("decision_reason") or temporal.get("decision_reason") or [],
                ensure_ascii=False,
            ),
            "fusion_state": fall_state,
            "fusion_suppressed_reason": coalesce_text(
                fall_decision.get("suppressed_reason"),
                fusion_debug.get("suppressed_reason"),
            ),
            "fusion_rejected_reason": coalesce_text(
                fall_decision.get("rejected_reason"),
                fusion_debug.get("rejected_reason"),
            ),
            "fusion_evidence_sources": json.dumps(fusion_debug.get("evidence_sources") or [], ensure_ascii=False),
            "pose_latency_ms": pose_status.get("last_inference_latency_ms"),
            "detection_latency_ms": detection_latency_ms,
            "fall_detection_latency_ms": fall_detection_latency_ms,
            "tracking_state": tracking_status.get("tracking_state"),
            "target_lost": tracking_status.get("tracking_state") in {"target_lost", "target_reacquiring"},
            "snapshot_url": snapshot_url,
            "snapshot_path": snapshot_path,
        }

    def _patch_time(self, stack: ExitStack, clock: SimulatedClock) -> None:
        patches = [
            "app.services.pose_service.time.monotonic",
            "app.services.temporal_service.time.monotonic",
            "app.temporal.fall_state_machine.time.monotonic",
            "app.tracking.target_manager.time.monotonic",
            "app.services.result_publisher_service.time.monotonic",
            "app.services.fall_event_reporter_service.time.monotonic",
            "app.fall.feature_builder.time.monotonic",
            "app.fall.fusion.time.monotonic",
            "app.detection.realtime_result_store.time.monotonic",
        ]
        for target in patches:
            stack.enter_context(patch(target, clock.monotonic))

    def _reset_services(self) -> None:
        self.result_store.clear_camera(self.camera_id)
        self.pose = PoseService(self.settings)
        self.tracking = TrackingService(self.settings)
        self.behavior = BehaviorService(self.settings)
        self.temporal = TemporalService(self.settings)
        self.fall_fusion = FallFusionService(self.settings)
        self.result_store = RealtimeResultStore()
        self.source_manager = FakeSourceManager()
        self.event_reporter = FallEventReporterService(self.settings, self.source_manager)
        self.publisher = ResultPublisherService(
            settings=self.settings,
            realtime_store=self.result_store,
            result_channels=self.result_channels,
            temporal_service=self.temporal,
            fall_fusion_service=self.fall_fusion,
            fall_event_reporter=self.event_reporter,
        )

    @staticmethod
    def _attach_scene_context(objects: list[DetectedObject], case: VideoEvalCase | None) -> list[DetectedObject]:
        if case is None or (not case.scene_type and not case.support_surface):
            return objects
        normalized: list[DetectedObject] = []
        scene_context = {
            "scene_type": case.scene_type,
            "support_surface": case.support_surface,
        }
        for item in objects:
            if item.label != "person":
                normalized.append(item)
                continue
            temporal = dict(item.temporal or {})
            temporal["scene_context"] = {key: value for key, value in scene_context.items() if value is not None}
            normalized.append(item.model_copy(update={"temporal": temporal}))
        return normalized


def write_frame_outputs(csv_path: Path, jsonl_path: Path, rows: list[dict[str, Any]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "video_name",
        "camera_id",
        "frame_index",
        "timestamp_ms",
        "frame_width",
        "frame_height",
        "latest_raw_person_count",
        "tracked_objects_count",
        "selected_track_id",
        "track_id",
        "bbox",
        "bbox_area",
        "pose_attempted",
        "pose_success",
        "pose_rejected_reason",
        "fall_state",
        "alarm_confirmed",
        "incident_id",
        "fall_prob",
        "fall_score",
        "risk_level",
        "fall_hint_label",
        "fall_hint_confidence",
        "fall_hint_iou",
        "fall_hint_strong",
        "fall_hint_weak",
        "lstm_probability",
        "v6_motion_path",
        "v6_fall_evidence_score",
        "v6_adl_suppression_score",
        "v6_vertical_drop_score",
        "v6_low_posture_score",
        "v6_post_fall_stillness_score",
        "v6_floor_contact_score",
        "v6_impact_proxy_score",
        "v6_low_posture_duration_ms",
        "v6_track_quality_score",
        "v6_recovery_score",
        "v6_support_surface_score",
        "v6_scene_type",
        "v6_scene_support_surface",
        "v6_scene_support_surface_score",
        "v6_scene_floor_risk_score",
        "v6_suppressed_by_adl",
        "v6_uncertain_review",
        "v6_fall_latched",
        "v6_decision_reason",
        "fusion_state",
        "fusion_suppressed_reason",
        "fusion_rejected_reason",
        "fusion_evidence_sources",
        "pose_latency_ms",
        "detection_latency_ms",
        "fall_detection_latency_ms",
        "tracking_state",
        "target_lost",
        "snapshot_url",
        "snapshot_path",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_video_summary(
    *,
    video_path: Path,
    case: VideoEvalCase | None,
    frame_count: int,
    processed_frames: int,
    fps: float,
    duration_ms: int,
    rows: list[dict[str, Any]],
    max_person_count: int,
    max_tracked_objects: int,
    pose_success_frames: int,
    alarm_confirmed_frames: int,
    confirmed_frames: int,
    first_confirmed_frame: int | None,
    first_confirmed_timestamp_ms: int | None,
    first_incident_id_frame: int | None,
    incident_id: str | None,
    snapshot_path: str | None,
    snapshot_url: str | None,
    latest_result_consumable: bool,
) -> VideoSummary:
    states_seen = [str(row["fall_state"]) for row in rows if row.get("fall_state")]
    peak_state = peak_fall_state(states_seen)
    person_detection_ok = max_person_count > 0
    tracking_ok = person_detection_ok and max_tracked_objects > 0
    pose_ok = tracking_ok and pose_success_frames > 0
    fall_confirm_ok = confirmed_frames > 0
    block_point = determine_block_point(
        person_detection_ok=person_detection_ok,
        tracking_ok=tracking_ok,
        pose_ok=pose_ok,
        fall_confirm_ok=fall_confirm_ok,
        incident_id=incident_id,
    )
    return VideoSummary(
        video=video_path.name,
        frame_count=frame_count,
        processed_frames=processed_frames,
        fps=round(fps, 2),
        duration_ms=duration_ms,
        person_detection="OK" if person_detection_ok else "FAIL",
        tracking="OK" if tracking_ok else "FAIL",
        pose="OK" if pose_ok else "FAIL",
        fall_confirm="OK" if fall_confirm_ok else "FAIL",
        incident_id=incident_id,
        block_point=block_point,
        fall_state_peak=peak_state,
        max_person_count=max_person_count,
        max_tracked_objects=max_tracked_objects,
        pose_success_frames=pose_success_frames,
        alarm_confirmed_frames=alarm_confirmed_frames,
        confirmed_frames=confirmed_frames,
        first_confirmed_frame=first_confirmed_frame,
        first_confirmed_timestamp_ms=first_confirmed_timestamp_ms,
        first_incident_id_frame=first_incident_id_frame,
        snapshot_path=snapshot_path,
        snapshot_url=snapshot_url,
        latest_result_consumable=latest_result_consumable,
        manifest_label=case.label if case else None,
        expected_alarm=case.expected_alarm if case else None,
            fall_start_ms=case.fall_start_ms if case else None,
            fall_end_ms=case.fall_end_ms if case else None,
            allowed_confirm_after_ms=case.allowed_confirm_after_ms if case else None,
            scene_type=case.scene_type if case else None,
            support_surface=case.support_surface if case else None,
            hard_negative_type=case.hard_negative_type if case else None,
        )


def determine_block_point(
    *,
    person_detection_ok: bool,
    tracking_ok: bool,
    pose_ok: bool,
    fall_confirm_ok: bool,
    incident_id: str | None,
) -> str:
    if not person_detection_ok:
        return "Detection"
    if not tracking_ok:
        return "Tracking"
    if not pose_ok:
        return "Pose"
    if not fall_confirm_ok:
        return "FallStateMachine"
    if not incident_id:
        return "ResultLayer"
    return "Passed"


def pick_best_person(objects: list[DetectedObject]) -> DetectedObject | None:
    people = [obj for obj in objects if obj.label == "person"]
    if not people:
        return None
    confirmed = [obj for obj in people if bool((obj.alarm_preview or {}).get("confirmed"))]
    if confirmed:
        return max(confirmed, key=lambda item: float(item.confidence))
    return max(people, key=lambda item: float(item.confidence))


def object_event_metadata(obj: DetectedObject | None) -> dict[str, Any]:
    if obj is None or not isinstance(obj.temporal, dict):
        return {}
    metadata = obj.temporal.get("event_metadata")
    if not isinstance(metadata, dict):
        return {}
    return dict(metadata)


def best_fall_probability(obj: DetectedObject | None) -> float | None:
    if obj is None:
        return None
    temporal = dict(obj.temporal or {})
    shadow = dict(temporal.get("shadow") or {}) if isinstance(temporal.get("shadow"), dict) else {}
    candidates = [
        temporal.get("fall_probability"),
        shadow.get("fall_probability"),
        (obj.fall_decision or {}).get("fall_probability"),
        (obj.alarm_preview or {}).get("fall_probability"),
    ]
    values: list[float] = []
    for candidate in candidates:
        try:
            if candidate is not None:
                values.append(max(0.0, min(1.0, float(candidate))))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def bbox_area(bbox: list[float] | None) -> float | None:
    if bbox is None or len(bbox) != 4:
        return None
    return round(max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1]), 2)


def peak_fall_state(states: list[str]) -> str | None:
    if not states:
        return None
    rank = {
        "normal": 0,
        "unstable": 1,
        "falling": 2,
        "fallen_candidate": 3,
        "fallen_confirmed": 4,
        "cooldown": 5,
    }
    return max(states, key=lambda item: rank.get(item, -1))


def coalesce_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def safe_slug(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in value)
    cleaned = cleaned.strip("._")
    return cleaned or "video"


def scan_videos(video_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in video_dir.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def load_manifest(path: Path) -> list[VideoEvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("videos") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("manifest must be a list or an object with a 'videos' list")
    cases: list[VideoEvalCase] = []
    for index, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"manifest item #{index} must be an object")
        raw_path = item.get("path") or item.get("video") or item.get("file")
        if not raw_path:
            raise ValueError(f"manifest item #{index} missing path/video")
        video_path = Path(str(raw_path))
        if not video_path.is_absolute():
            video_path = (path.parent / video_path).resolve()
        label = coalesce_text(item.get("label"))
        expected_alarm = item.get("expected_alarm")
        if expected_alarm is None:
            expected_alarm = label == "fall"
        cases.append(
            VideoEvalCase(
                path=video_path,
                video_id=coalesce_text(item.get("video_id"), video_path.stem),
                label=label,
                expected_alarm=bool(expected_alarm),
                fall_start_ms=coerce_int(item.get("fall_start_ms")),
                fall_end_ms=coerce_int(item.get("fall_end_ms")),
                allowed_confirm_after_ms=coerce_int(item.get("allowed_confirm_after_ms")),
                scene_type=coalesce_text(item.get("scene_type")),
                support_surface=coalesce_text(item.get("support_surface")),
                hard_negative_type=coalesce_text(item.get("hard_negative_type")),
            )
        )
    return cases


def build_event_metrics(summaries: list[VideoSummary], output_dir: Path) -> dict[str, Any]:
    fall_cases = [item for item in summaries if item.expected_alarm is True or item.manifest_label == "fall"]
    non_fall_cases = [item for item in summaries if item.expected_alarm is False or item.manifest_label == "non_fall"]
    detected_fall_cases = [item for item in fall_cases if item.alarm_confirmed_frames > 0 or item.confirmed_frames > 0]
    missed_falls = [item for item in fall_cases if item not in detected_fall_cases]
    confirmed_fps = [item for item in non_fall_cases if item.alarm_confirmed_frames > 0 or item.confirmed_frames > 0]
    candidate_fps = [
        item
        for item in non_fall_cases
        if (item.fall_state_peak in {"falling", "fallen_candidate", "fallen_confirmed"} or item.alarm_confirmed_frames > 0)
    ]
    delays = []
    for item in detected_fall_cases:
        if item.first_confirmed_timestamp_ms is None:
            continue
        start_ms = item.fall_start_ms or 0
        delays.append(max(0, item.first_confirmed_timestamp_ms - start_ms))
    suppressed_distribution: dict[str, int] = {}
    block_counts: dict[str, int] = {}
    v6_motion_paths: dict[str, int] = {}
    v6_decision_reasons: dict[str, int] = {}
    v6_adl_suppressed_frames = 0
    v6_uncertain_review_frames = 0
    v6_fall_latched_frames = 0
    for item in summaries:
        block_counts[item.block_point] = block_counts.get(item.block_point, 0) + 1
        reason = load_summary_suppressed_reason(item, output_dir)
        if reason:
            suppressed_distribution[reason] = suppressed_distribution.get(reason, 0) + 1
        frame_metrics = load_v6_frame_metrics(item, output_dir)
        for path, count in frame_metrics["motion_paths"].items():
            v6_motion_paths[path] = v6_motion_paths.get(path, 0) + count
        for reason_item, count in frame_metrics["decision_reasons"].items():
            v6_decision_reasons[reason_item] = v6_decision_reasons.get(reason_item, 0) + count
        v6_adl_suppressed_frames += frame_metrics["adl_suppressed_frames"]
        v6_uncertain_review_frames += frame_metrics["uncertain_review_frames"]
        v6_fall_latched_frames += frame_metrics["fall_latched_frames"]
    return {
        "fall_event_recall": round(len(detected_fall_cases) / len(fall_cases), 4) if fall_cases else None,
        "confirmed_false_positive_count": len(confirmed_fps),
        "confirmed_false_positive_rate": round(len(confirmed_fps) / len(non_fall_cases), 4) if non_fall_cases else None,
        "candidate_false_positive_count": len(candidate_fps),
        "first_confirm_delay_ms": round(sum(delays) / len(delays), 2) if delays else None,
        "missed_fall_count": len(missed_falls),
        "block_point": block_counts,
        "suppressed_reason_distribution": suppressed_distribution,
        "v6": {
            "motion_path_distribution": v6_motion_paths,
            "decision_reason_distribution": v6_decision_reasons,
            "adl_suppressed_frames": v6_adl_suppressed_frames,
            "uncertain_review_frames": v6_uncertain_review_frames,
            "fall_latched_frames": v6_fall_latched_frames,
        },
        "confusion": {
            "true_positive": len(detected_fall_cases),
            "false_negative": len(missed_falls),
            "false_positive": len(confirmed_fps),
            "true_negative": max(0, len(non_fall_cases) - len(confirmed_fps)),
        },
        "gates": {
            "adl_confirmed_fp_zero": len(confirmed_fps) == 0,
            "initial_fall_recall_0_70": None if not fall_cases else len(detected_fall_cases) / len(fall_cases) >= 0.70,
            "stable_fall_recall_0_80": None if not fall_cases else len(detected_fall_cases) / len(fall_cases) >= 0.80,
            "mean_confirm_delay_under_2500_ms": None if not delays else (sum(delays) / len(delays)) < 2500,
        },
    }


def load_summary_suppressed_reason(summary: VideoSummary, output_dir: Path) -> str | None:
    frames_jsonl = output_dir / f"offline_eval_{safe_slug(Path(summary.video).stem)}_frames.jsonl"
    if not frames_jsonl.exists():
        return None
    reasons: dict[str, int] = {}
    for line in frames_jsonl.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        reason = coalesce_text(row.get("fusion_suppressed_reason"), row.get("fusion_rejected_reason"))
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    return max(reasons.items(), key=lambda item: item[1])[0] if reasons else None


def load_v6_frame_metrics(summary: VideoSummary, output_dir: Path) -> dict[str, Any]:
    frames_jsonl = output_dir / f"offline_eval_{safe_slug(Path(summary.video).stem)}_frames.jsonl"
    metrics: dict[str, Any] = {
        "motion_paths": {},
        "decision_reasons": {},
        "adl_suppressed_frames": 0,
        "uncertain_review_frames": 0,
        "fall_latched_frames": 0,
    }
    if not frames_jsonl.exists():
        return metrics
    for line in frames_jsonl.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        path = coalesce_text(row.get("v6_motion_path"))
        if path:
            metrics["motion_paths"][path] = metrics["motion_paths"].get(path, 0) + 1
        for reason in parse_reason_list(row.get("v6_decision_reason")):
            metrics["decision_reasons"][reason] = metrics["decision_reasons"].get(reason, 0) + 1
        if bool(row.get("v6_suppressed_by_adl")):
            metrics["adl_suppressed_frames"] += 1
        if bool(row.get("v6_uncertain_review")):
            metrics["uncertain_review_frames"] += 1
        if bool(row.get("v6_fall_latched")):
            metrics["fall_latched_frames"] += 1
    return metrics


def coerce_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_float(*values: Any) -> float | None:
    for value in values:
        try:
            if value is not None and value != "":
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def parse_reason_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
        return [str(parsed)]
    return [str(value)]


def write_markdown_report(
    *,
    report_path: Path,
    video_dir: Path,
    summaries: list[VideoSummary],
    event_metrics: dict[str, Any] | None = None,
) -> None:
    layer_counts: dict[str, int] = {}
    failure_layer_counts: dict[str, int] = {}
    for summary in summaries:
        layer_counts[summary.block_point] = layer_counts.get(summary.block_point, 0) + 1
        if summary.block_point != "Passed":
            failure_layer_counts[summary.block_point] = failure_layer_counts.get(summary.block_point, 0) + 1
    worst_layer = (
        max(failure_layer_counts.items(), key=lambda item: item[1])[0]
        if failure_layer_counts
        else ("Passed" if summaries else "None")
    )
    lines = [
        "# Offline Fall Eval Summary",
        "",
        f"- Video dir: `{video_dir}`",
        f"- Total videos: `{len(summaries)}`",
        f"- Passed: `{sum(1 for item in summaries if item.block_point == 'Passed')}`",
        f"- Failed: `{sum(1 for item in summaries if item.block_point != 'Passed')}`",
        f"- Most frequent failure layer: `{worst_layer}`",
        "",
        "## Event Metrics",
        "",
    ]
    if event_metrics:
        lines.extend(
            [
                f"- fall_event_recall: `{event_metrics.get('fall_event_recall')}`",
                f"- confirmed_false_positive_count: `{event_metrics.get('confirmed_false_positive_count')}`",
                f"- confirmed_false_positive_rate: `{event_metrics.get('confirmed_false_positive_rate')}`",
                f"- candidate_false_positive_count: `{event_metrics.get('candidate_false_positive_count')}`",
                f"- first_confirm_delay_ms: `{event_metrics.get('first_confirm_delay_ms')}`",
                f"- missed_fall_count: `{event_metrics.get('missed_fall_count')}`",
                "",
                "### Confusion Table",
                "",
            ]
        )
        confusion = event_metrics.get("confusion") or {}
        for key in ["true_positive", "false_negative", "false_positive", "true_negative"]:
            lines.append(f"- {key}: `{confusion.get(key)}`")
        lines.extend(["", "### Gates", ""])
        gates = event_metrics.get("gates") or {}
        for key, value in gates.items():
            lines.append(f"- {key}: `{value}`")
        v6 = event_metrics.get("v6") or {}
        lines.extend(["", "### V6 Temporal Logic", ""])
        lines.append(f"- adl_suppressed_frames: `{v6.get('adl_suppressed_frames')}`")
        lines.append(f"- uncertain_review_frames: `{v6.get('uncertain_review_frames')}`")
        lines.append(f"- fall_latched_frames: `{v6.get('fall_latched_frames')}`")
        lines.extend(["", "#### Motion Path Distribution", ""])
        for key, value in sorted((v6.get("motion_path_distribution") or {}).items()):
            lines.append(f"- {key}: `{value}`")
        lines.extend(["", "#### Decision Reason Distribution", ""])
        for key, value in sorted((v6.get("decision_reason_distribution") or {}).items()):
            lines.append(f"- {key}: `{value}`")
        lines.append("")
    else:
        lines.extend(["- No manifest labels supplied; event-level metrics are unavailable.", ""])
    lines.extend(
        [
        "## Video List",
        "",
        ]
    )
    for index, summary in enumerate(summaries, start=1):
        lines.extend(
            [
                f"### {index}. {summary.video}",
                "",
                f"- block_point: `{summary.block_point}`",
                f"- incident_id: `{summary.incident_id or 'null'}`",
                f"- person_detection: `{summary.person_detection}`",
                f"- tracking: `{summary.tracking}`",
                f"- pose: `{summary.pose}`",
                f"- fall_confirm: `{summary.fall_confirm}`",
                f"- fall_state_peak: `{summary.fall_state_peak or 'none'}`",
                f"- snapshot_path: `{summary.snapshot_path or 'null'}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Layer Counts",
            "",
        ]
    )
    for layer, count in sorted(layer_counts.items()):
        lines.append(f"- {layer}: `{count}`")
    lines.extend(
        [
            "",
            "## Next Step",
            "",
            f"- Focus first on `{worst_layer}` because it is the dominant block point in this batch."
            if summaries
            else "- No videos were evaluated.",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline fall pipeline evaluation for local videos.")
    parser.add_argument("--video", action="append", default=[], help="Specific video file to evaluate. May be repeated.")
    parser.add_argument("--video-dir", default=str(ROOT / "video"), help="Directory to scan for local videos.")
    parser.add_argument("--manifest", default=None, help="JSON manifest with video paths and event labels.")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "snapshots").mkdir(parents=True, exist_ok=True)

    cases: list[VideoEvalCase] | None = None
    if args.manifest:
        cases = load_manifest(Path(args.manifest))
    explicit_videos = [Path(item) for item in args.video]
    scanned_videos = scan_videos(Path(args.video_dir))
    videos = explicit_videos or scanned_videos
    if not cases and not videos:
        raise SystemExit(f"No video files found in {args.video_dir}")

    evaluator = OfflineFallVideoEvaluator(
        output_dir=output_dir,
        camera_id=args.camera_id,
        frame_stride=args.frame_stride,
    )
    summaries = evaluator.evaluate_cases(cases) if cases is not None else evaluator.evaluate_videos(videos)
    event_metrics = build_event_metrics(summaries, output_dir) if cases is not None else None

    report_path = output_dir / "offline_fall_eval_summary.md"
    write_markdown_report(
        report_path=report_path,
        video_dir=Path(args.video_dir),
        summaries=summaries,
        event_metrics=event_metrics,
    )

    payload = {
        "video_dir": str(Path(args.video_dir).resolve()),
        "total_videos": len(summaries),
        "manifest": str(Path(args.manifest).resolve()) if args.manifest else None,
        "passed": sum(1 for item in summaries if item.block_point == "Passed"),
        "failed": sum(1 for item in summaries if item.block_point != "Passed"),
        "event_metrics": event_metrics,
        "videos": [item.to_dict() for item in summaries],
        "report": str(report_path.resolve()),
    }
    summary_path = output_dir / "offline_fall_eval_summary.json"
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
