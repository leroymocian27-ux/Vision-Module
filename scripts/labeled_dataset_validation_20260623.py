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
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACT_DIR = ROOT / "artifacts" / "labeled_dataset_validation_20260623"
DOC_PATH = ROOT / "docs" / "labeled_dataset_validation_20260623.md"

POSITIVE_STATES = {"fallen_candidate", "fallen_confirmed", "confirmed_fall"}
CONFIRMED_STATES = {"fallen_confirmed", "confirmed_fall"}
POSITIVE_RISKS = {"high", "critical"}


def configure_eval_environment(output_dir: Path) -> None:
    overrides = {
        "VISION_SERVICE_RUNTIME_PROFILE": "labeled_dataset_validation_20260623",
        "ENABLE_TRACKING": "true",
        "ENABLE_POSE": "true",
        "POSE_PROVIDER": os.environ.get("POSE_PROVIDER") or "yolo11_legacy",
        "YOLO11_POSE_MODEL_PATH": os.environ.get("YOLO11_POSE_MODEL_PATH") or "yolo11n-pose.pt",
        "ENABLE_BEHAVIOR": "false",
        "ENABLE_TEMPORAL": "false",
        "MAIN_SYSTEM_ALERT_ENABLED": "true",
        "MAIN_SYSTEM_REPORT_DRY_RUN": "true",
        "MAIN_SYSTEM_BASE_URL": "http://127.0.0.1:9/api/v1",
        "MAIN_SYSTEM_FALL_EVENT_PATH": "/video-bridge/fall-events",
        "VISION_SERVICE_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
        "FALL_EVENT_SNAPSHOT_DIR": str((output_dir / "snapshots").resolve()),
        "POSE_FALLBACK_TO_DETECTION": "true",
        "POSE_FALLBACK_MIN_CONFIDENCE": "0.15",
        "POSE_SKIP_WHEN_INFERENCE_BUSY": "true",
    }
    for key, value in overrides.items():
        os.environ[key] = value


@dataclass
class LabelRow:
    video_path: Path
    label: str
    scene: str
    fall_start_sec: float | None
    fall_end_sec: float | None
    notes: str


@dataclass
class FramePacket:
    camera_id: str
    seq: int
    frame: np.ndarray
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

    def update_frame(self, camera_id: str, frame_seq: int, frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        self.get_buffer(camera_id).set_latest(
            FramePacket(camera_id=camera_id, seq=frame_seq, frame=frame, width=width, height=height)
        )


class SimulatedClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += max(float(seconds), 1e-6)


def import_runtime_modules():
    from app.core.config import get_settings
    from app.detection.object_detector import YoloPersonDetector
    from app.detection.realtime_result_store import DetectionSnapshot, ObjectSnapshot, RealtimeResultStore
    from app.detection.yolo_fall_detector import YoloFallDetector
    from app.schemas.common import utc_now_iso
    from app.services.fall_event_reporter_service import FallEventReporterService
    from app.services.pose_service import PoseService
    from app.services.result_publisher_service import ResultPublisherService
    from app.services.tracking_service import TrackingService
    from app.streaming.result_channel_manager import ResultChannelManager

    return {
        "get_settings": get_settings,
        "YoloPersonDetector": YoloPersonDetector,
        "YoloFallDetector": YoloFallDetector,
        "DetectionSnapshot": DetectionSnapshot,
        "ObjectSnapshot": ObjectSnapshot,
        "RealtimeResultStore": RealtimeResultStore,
        "utc_now_iso": utc_now_iso,
        "FallEventReporterService": FallEventReporterService,
        "PoseService": PoseService,
        "ResultPublisherService": ResultPublisherService,
        "TrackingService": TrackingService,
        "ResultChannelManager": ResultChannelManager,
    }


class LabeledDatasetEvaluator:
    def __init__(self, output_dir: Path, frame_stride: int, max_frames_per_video: int) -> None:
        configure_eval_environment(output_dir)
        self.rt = import_runtime_modules()
        self.settings = self.rt["get_settings"]()
        self.output_dir = output_dir
        self.sample_dir = output_dir / "sample_frames"
        self.frame_stride = max(1, frame_stride)
        self.max_frames_per_video = max(1, max_frames_per_video)
        self.person_detector = self.rt["YoloPersonDetector"](self.settings)
        self.fall_detector = self.rt["YoloFallDetector"](self.settings)
        self.result_channels = self.rt["ResultChannelManager"]()

    def evaluate(self, labels: list[LabelRow]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.sample_dir.mkdir(parents=True, exist_ok=True)
        per_video: list[dict[str, Any]] = []
        for index, row in enumerate(labels, start=1):
            print(f"[{index}/{len(labels)}] evaluating {row.label} {row.video_path}", flush=True)
            per_video.append(self.evaluate_video(row, index))
        summary = compute_summary(per_video, self.settings)
        return per_video, summary

    def evaluate_video(self, label: LabelRow, ordinal: int) -> dict[str, Any]:
        camera_id = f"eval_{ordinal:03d}_{safe_slug(label.video_path.stem)}"
        store = self.rt["RealtimeResultStore"]()
        source_manager = FakeSourceManager()
        tracking = self.rt["TrackingService"](self.settings)
        pose = self.rt["PoseService"](self.settings)
        reporter = self.rt["FallEventReporterService"](self.settings, source_manager)
        reporter.start()
        publisher = self.rt["ResultPublisherService"](
            settings=self.settings,
            realtime_store=store,
            result_channels=self.result_channels,
            temporal_service=None,
            fall_event_reporter=reporter,
        )

        cap = cv2.VideoCapture(str(label.video_path))
        if not cap.isOpened():
            reporter.stop()
            return failed_video_row(label, "video_open_failed")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 25.0
        native_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        clock = SimulatedClock()
        frame_index = -1
        processed = 0
        frame_rows: list[dict[str, Any]] = []
        saved_sample = False
        started = time.perf_counter()

        try:
            with ExitStack() as stack:
                self._patch_time(stack, clock)
                while processed < self.max_frames_per_video:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    frame_index += 1
                    if frame_index % self.frame_stride != 0:
                        clock.advance(1.0 / fps)
                        continue
                    frame_row, result = self._process_frame(
                        camera_id=camera_id,
                        frame_index=frame_index,
                        timestamp_ms=int(round(frame_index * 1000.0 / fps)),
                        frame=frame,
                        store=store,
                        source_manager=source_manager,
                        tracking=tracking,
                        pose=pose,
                        reporter=reporter,
                        publisher=publisher,
                    )
                    frame_rows.append(frame_row)
                    processed += 1
                    if not saved_sample and should_save_sample(frame_row):
                        self._write_sample_frame(label, ordinal, frame, frame_row, result)
                        saved_sample = True
                    clock.advance(1.0 / fps)
        finally:
            cap.release()
            wait_for_reporter(reporter)
            reporter_status = reporter.status()
            reporter.stop()

        elapsed = time.perf_counter() - started
        video_row = summarize_video(
            label=label,
            camera_id=camera_id,
            native_frame_count=native_frame_count,
            width=width,
            height=height,
            fps=fps,
            processed_frames=processed,
            frame_rows=frame_rows,
            elapsed=elapsed,
            reporter_status=reporter_status,
            frame_stride=self.frame_stride,
            max_frames_per_video=self.max_frames_per_video,
        )
        write_jsonl(self.output_dir / "frame_results.jsonl", frame_rows, append=True)
        return video_row

    def _process_frame(
        self,
        *,
        camera_id: str,
        frame_index: int,
        timestamp_ms: int,
        frame: np.ndarray,
        store,
        source_manager: FakeSourceManager,
        tracking,
        pose,
        reporter,
        publisher,
    ):
        height, width = frame.shape[:2]
        source_manager.update_frame(camera_id, frame_index, frame)

        person_started = time.perf_counter()
        person_objects = self.person_detector.detect(frame)
        person_latency_ms = round((time.perf_counter() - person_started) * 1000.0, 2)

        fall_started = time.perf_counter()
        fall_objects = self.fall_detector.detect(frame)
        fall_latency_ms = round((time.perf_counter() - fall_started) * 1000.0, 2)

        timestamp = self.rt["utc_now_iso"]()
        monotonic_at = time.monotonic()
        store.update_detection(
            self.rt["DetectionSnapshot"](
                camera_id=camera_id,
                frame_seq=frame_index,
                frame_width=width,
                frame_height=height,
                timestamp=timestamp,
                monotonic_at=monotonic_at,
                frame=frame,
                objects=person_objects,
                detector={
                    "name": "yolov8n.pt",
                    "latency_ms": person_latency_ms,
                    "mode": "offline_labeled_eval_person",
                },
            )
        )
        store.update_fall_detection(
            self.rt["DetectionSnapshot"](
                camera_id=camera_id,
                frame_seq=frame_index,
                frame_width=width,
                frame_height=height,
                timestamp=timestamp,
                monotonic_at=monotonic_at,
                frame=frame,
                objects=fall_objects,
                detector={
                    "name": self.settings.yolo_fall_model_path,
                    "latency_ms": fall_latency_ms,
                    "mode": "offline_labeled_eval_fall",
                },
            )
        )

        track_started = time.perf_counter()
        tracked_objects = tracking.enrich(camera_id, person_objects, frame=frame)
        track_latency_ms = round((time.perf_counter() - track_started) * 1000.0, 2)
        store.update_tracking(
            self.rt["ObjectSnapshot"](
                camera_id=camera_id,
                frame_seq=frame_index,
                frame_width=width,
                frame_height=height,
                timestamp=timestamp,
                monotonic_at=monotonic_at,
                objects=tracked_objects,
            )
        )

        pose_started = time.perf_counter()
        pose_objects = pose.enrich(
            camera_id,
            frame,
            tracked_objects,
            frame_seq=frame_index,
            tracking_frame_seq=frame_index,
            frame_age_ms=0.0,
            frame_timestamp=timestamp,
        )
        pose_wall_latency_ms = round((time.perf_counter() - pose_started) * 1000.0, 2)
        if any(item.pose is not None for item in pose_objects):
            store.update_pose(
                self.rt["ObjectSnapshot"](
                    camera_id=camera_id,
                    frame_seq=frame_index,
                    frame_width=width,
                    frame_height=height,
                    timestamp=timestamp,
                    monotonic_at=monotonic_at,
                    objects=pose_objects,
                )
            )

        result = publisher._build_result(camera_id)
        if result is not None:
            reporter.inspect_result(result)
            store.update_published(result)

        return frame_result_row(
            frame_index=frame_index,
            timestamp_ms=timestamp_ms,
            person_objects=person_objects,
            fall_objects=fall_objects,
            tracked_objects=tracked_objects,
            pose_objects=pose_objects,
            pose_status=pose.status(camera_id).model_dump(),
            tracking_status=tracking.status(camera_id).model_dump(),
            result=result,
            person_latency_ms=person_latency_ms,
            fall_latency_ms=fall_latency_ms,
            track_latency_ms=track_latency_ms,
            pose_wall_latency_ms=pose_wall_latency_ms,
        ), result

    def _patch_time(self, stack: ExitStack, clock: SimulatedClock) -> None:
        for target in [
            "app.services.pose_service.time.monotonic",
            "app.tracking.target_manager.time.monotonic",
            "app.services.result_publisher_service.time.monotonic",
            "app.services.fall_event_reporter_service.time.monotonic",
            "app.detection.realtime_result_store.time.monotonic",
            "app.monitoring.metrics.time.monotonic",
        ]:
            stack.enter_context(patch(target, clock.monotonic))

    def _write_sample_frame(self, label: LabelRow, ordinal: int, frame: np.ndarray, row: dict[str, Any], result) -> None:
        canvas = frame.copy()
        if result is not None:
            for obj in result.objects:
                color = (0, 0, 255) if runtime_positive(obj) else (0, 210, 0)
                draw_object(canvas, obj, color)
        out = self.sample_dir / f"{ordinal:03d}_{safe_slug(label.video_path.stem)}_{row['frame_index']}.jpg"
        cv2.imwrite(str(out), canvas)
        row["sample_frame"] = str(out)


def frame_result_row(
    *,
    frame_index: int,
    timestamp_ms: int,
    person_objects,
    fall_objects,
    tracked_objects,
    pose_objects,
    pose_status: dict[str, Any],
    tracking_status: dict[str, Any],
    result,
    person_latency_ms: float,
    fall_latency_ms: float,
    track_latency_ms: float,
    pose_wall_latency_ms: float,
) -> dict[str, Any]:
    best = best_person(result.objects if result is not None else pose_objects)
    pose_payload = best.pose if best is not None and isinstance(best.pose, dict) else None
    keypoints = pose_payload.get("keypoints") if isinstance(pose_payload, dict) else None
    keypoint_count = len(keypoints) if isinstance(keypoints, list) else 0
    visible_keypoints = [
        item for item in (keypoints or []) if isinstance(item, dict) and float(item.get("confidence") or 0.0) >= 0.2
    ]
    fall_state = str((best.fall_decision or {}).get("fall_state") or "") if best is not None else ""
    alarm_preview = best.alarm_preview or {} if best is not None else {}
    decision = best.fall_decision or {} if best is not None else {}
    risk_level = str(alarm_preview.get("risk_level") or decision.get("risk_level") or "")
    fall_score = best_score(best)
    incident_id = event_metadata(best).get("incident_id") if best is not None else None
    return {
        "frame_index": frame_index,
        "timestamp_ms": timestamp_ms,
        "person_count": len(person_objects),
        "fall_model_count": len(fall_objects),
        "fall_model_labels": "|".join(sorted({str(item.label) for item in fall_objects})),
        "fall_model_max_conf": max([float(item.confidence) for item in fall_objects], default=0.0),
        "tracked_objects_count": len(tracked_objects),
        "tracking_state": tracking_status.get("tracking_state"),
        "active_target_exists": tracking_status.get("active_target_exists"),
        "track_id": best.track_id if best is not None else None,
        "fall_state": fall_state,
        "risk_level": risk_level,
        "fall_score": fall_score,
        "alarm_confirmed": bool(alarm_preview.get("confirmed")),
        "incident_id": incident_id,
        "runtime_positive": bool(best is not None and runtime_positive(best)),
        "pose_attached": pose_payload is not None,
        "pose_provider": pose_payload.get("pose_provider") if isinstance(pose_payload, dict) else None,
        "keypoint_count": keypoint_count,
        "keypoint_count_is_17": keypoint_count == 17,
        "visible_keypoint_count": len(visible_keypoints),
        "skeleton_confidence": pose_payload.get("skeleton_confidence") if isinstance(pose_payload, dict) else None,
        "pose_rejected_reason": pose_status.get("rejected_reason"),
        "pose_model_path": pose_status.get("pose_model_path"),
        "person_latency_ms": person_latency_ms,
        "fall_latency_ms": fall_latency_ms,
        "track_latency_ms": track_latency_ms,
        "pose_latency_ms": pose_status.get("last_inference_latency_ms") or pose_wall_latency_ms,
    }


def summarize_video(
    *,
    label: LabelRow,
    camera_id: str,
    native_frame_count: int,
    width: int,
    height: int,
    fps: float,
    processed_frames: int,
    frame_rows: list[dict[str, Any]],
    elapsed: float,
    reporter_status: dict[str, Any],
    frame_stride: int,
    max_frames_per_video: int,
) -> dict[str, Any]:
    states = [str(row["fall_state"]) for row in frame_rows if row.get("fall_state")]
    risks = [str(row["risk_level"]) for row in frame_rows if row.get("risk_level")]
    predicted = any(bool(row.get("runtime_positive")) for row in frame_rows)
    confirmed = any(str(row.get("fall_state")) in CONFIRMED_STATES or row.get("alarm_confirmed") for row in frame_rows)
    expected = label.label == "fall"
    outcome = "TP" if expected and predicted else "FN" if expected else "FP" if predicted else "TN"
    first_positive = next((row for row in frame_rows if row.get("runtime_positive")), None)
    first_confirmed = next(
        (row for row in frame_rows if str(row.get("fall_state")) in CONFIRMED_STATES or row.get("alarm_confirmed")),
        None,
    )
    fall_start_ms = int(label.fall_start_sec * 1000) if label.fall_start_sec is not None else None
    first_positive_latency_ms = (
        int(first_positive["timestamp_ms"]) - fall_start_ms
        if first_positive is not None and fall_start_ms is not None
        else None
    )
    first_confirmed_latency_ms = (
        int(first_confirmed["timestamp_ms"]) - fall_start_ms
        if first_confirmed is not None and fall_start_ms is not None
        else None
    )
    reporter_last_status = str(reporter_status.get("last_post_status") or "")
    return {
        "video_path": str(label.video_path),
        "label": label.label,
        "scene": label.scene,
        "notes": label.notes,
        "camera_id": camera_id,
        "frame_width": width,
        "frame_height": height,
        "native_fps": round(fps, 3),
        "native_frame_count": native_frame_count,
        "frame_stride": frame_stride,
        "max_frames_per_video": max_frames_per_video,
        "processed_frames": processed_frames,
        "offline_elapsed_sec": round(elapsed, 3),
        "offline_processing_fps": round(processed_frames / elapsed, 3) if elapsed > 0 else 0.0,
        "person_frames": sum(1 for row in frame_rows if int(row.get("person_count") or 0) > 0),
        "fall_model_frames": sum(1 for row in frame_rows if int(row.get("fall_model_count") or 0) > 0),
        "tracked_frames": sum(1 for row in frame_rows if int(row.get("tracked_objects_count") or 0) > 0),
        "pose_attached_frames": sum(1 for row in frame_rows if row.get("pose_attached")),
        "pose_attached_rate": safe_rate(sum(1 for row in frame_rows if row.get("pose_attached")), processed_frames),
        "avg_keypoint_count": safe_avg([row.get("keypoint_count") for row in frame_rows if row.get("pose_attached")]),
        "keypoint_count_17_rate": safe_rate(sum(1 for row in frame_rows if row.get("keypoint_count_is_17")), processed_frames),
        "avg_skeleton_confidence": safe_avg([row.get("skeleton_confidence") for row in frame_rows]),
        "pose_rejected_reasons": json.dumps(reason_counts(frame_rows), ensure_ascii=False),
        "avg_person_latency_ms": safe_avg([row.get("person_latency_ms") for row in frame_rows]),
        "avg_fall_latency_ms": safe_avg([row.get("fall_latency_ms") for row in frame_rows]),
        "avg_pose_latency_ms": safe_avg([row.get("pose_latency_ms") for row in frame_rows if row.get("pose_attached")]),
        "avg_total_model_latency_ms": safe_avg(
            [
                float(row.get("person_latency_ms") or 0.0)
                + float(row.get("fall_latency_ms") or 0.0)
                + float(row.get("pose_latency_ms") or 0.0)
                for row in frame_rows
            ]
        ),
        "fall_state_peak": peak_value(states, {"normal": 0, "falling": 1, "fallen_candidate": 2, "fallen_confirmed": 3}),
        "risk_level_peak": peak_value(risks, {"low": 0, "medium": 1, "high": 2, "critical": 3}),
        "max_fall_score": max([float(row.get("fall_score") or 0.0) for row in frame_rows], default=0.0),
        "predicted_fall": predicted,
        "confirmed_fall": confirmed,
        "outcome": outcome,
        "first_positive_timestamp_ms": first_positive.get("timestamp_ms") if first_positive else None,
        "first_confirmed_timestamp_ms": first_confirmed.get("timestamp_ms") if first_confirmed else None,
        "first_positive_latency_ms": first_positive_latency_ms,
        "first_confirmed_latency_ms": first_confirmed_latency_ms,
        "incident_id": first_non_empty(row.get("incident_id") for row in frame_rows),
        "reporter_dry_run": bool(reporter_status.get("dry_run")),
        "reporter_last_post_status": reporter_last_status or "no_real_post",
        "reporter_no_real_post": bool(reporter_status.get("dry_run")) and reporter_last_status in {"", "dry_run_skipped"},
    }


def compute_summary(per_video: list[dict[str, Any]], settings) -> dict[str, Any]:
    tp = sum(1 for row in per_video if row["outcome"] == "TP")
    fp = sum(1 for row in per_video if row["outcome"] == "FP")
    fn = sum(1 for row in per_video if row["outcome"] == "FN")
    tn = sum(1 for row in per_video if row["outcome"] == "TN")
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    scene_fp: dict[str, int] = {}
    for row in per_video:
        if row["outcome"] == "FP":
            scene_fp[row["scene"]] = scene_fp.get(row["scene"], 0) + 1
    return {
        "evaluated_videos": len(per_video),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "scene_false_positives": scene_fp,
        "avg_offline_processing_fps": safe_avg([row["offline_processing_fps"] for row in per_video]),
        "avg_total_model_latency_ms": safe_avg([row["avg_total_model_latency_ms"] for row in per_video]),
        "avg_pose_attached_rate": safe_avg([row["pose_attached_rate"] for row in per_video]),
        "avg_keypoint_count": safe_avg([row["avg_keypoint_count"] for row in per_video]),
        "avg_keypoint_count_17_rate": safe_avg([row["keypoint_count_17_rate"] for row in per_video]),
        "avg_skeleton_confidence": safe_avg([row["avg_skeleton_confidence"] for row in per_video]),
        "dry_run_all": all(bool(row["reporter_dry_run"]) for row in per_video),
        "no_real_post_all": all(bool(row["reporter_no_real_post"]) for row in per_video),
        "models": {
            "person": settings.yolo_model_path,
            "fall": settings.yolo_fall_model_path,
            "pose_provider": settings.pose_provider,
            "yolo11_pose": settings.yolo11_pose_model_path,
            "yolo_pose": settings.yolo_pose_model_path,
            "bytetrack": "ultralytics.trackers.byte_tracker.BYTETracker",
            "temporal_enabled": settings.enable_temporal,
            "dry_run": settings.main_system_report_dry_run,
        },
    }


def make_default_labels(output_csv: Path, max_public_fall: int, max_public_non_fall: int, max_local: int, max_hard_negative: int) -> None:
    rows: list[dict[str, str]] = []
    rows.extend(select_split_rows(ROOT / "datasets/fast_pose_fall/splits/local_test.jsonl", limit=max_local))
    rows.extend(select_split_rows(ROOT / "datasets/fast_pose_fall/splits/hard_negative_test.jsonl", limit=max_hard_negative))
    rows.extend(select_split_rows(ROOT / "datasets/fast_pose_fall/splits/public_test.jsonl", label="fall", limit=max_public_fall))
    rows.extend(select_split_rows(ROOT / "datasets/fast_pose_fall/splits/public_test.jsonl", label="non_fall", limit=max_public_non_fall))
    seen: set[str] = set()
    deduped = []
    for row in rows:
        if row["video_path"] in seen:
            continue
        seen.add(row["video_path"])
        deduped.append(row)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["video_path", "label", "scene", "fall_start_sec", "fall_end_sec", "notes"])
        writer.writeheader()
        writer.writerows(deduped)


def select_split_rows(path: Path, label: str | None = None, limit: int = 4) -> list[dict[str, str]]:
    if limit <= 0 or not path.exists():
        return []
    selected = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            item = json.loads(line)
            item_label = str(item.get("label") or item.get("binary_label") or "").strip()
            if label is not None and item_label != label:
                continue
            video_path = Path(str(item.get("path") or item.get("absolute_path") or ""))
            if not video_path.exists():
                continue
            scene_tags = item.get("scene_tags") if isinstance(item.get("scene_tags"), list) else []
            scene = infer_scene(video_path, scene_tags)
            selected.append(
                {
                    "video_path": str(video_path),
                    "label": "fall" if item_label == "fall" else "non_fall",
                    "scene": scene,
                    "fall_start_sec": "",
                    "fall_end_sec": "",
                    "notes": f"{path.name}; asset_id={item.get('asset_id', '')}; tags={'|'.join(scene_tags)}",
                }
            )
            if len(selected) >= limit:
                break
    return selected


def load_labels(path: Path) -> list[LabelRow]:
    rows: list[LabelRow] = []
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            video_path = Path(str(raw.get("video_path") or "")).expanduser()
            if not video_path.is_absolute():
                video_path = (ROOT / video_path).resolve()
            rows.append(
                LabelRow(
                    video_path=video_path,
                    label=normalize_label(raw.get("label")),
                    scene=str(raw.get("scene") or "unknown"),
                    fall_start_sec=parse_optional_float(raw.get("fall_start_sec")),
                    fall_end_sec=parse_optional_float(raw.get("fall_end_sec")),
                    notes=str(raw.get("notes") or ""),
                )
            )
    return rows


def write_outputs(output_dir: Path, labels_path: Path, per_video: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    write_csv(output_dir / "per_video_results.csv", per_video)
    summary_rows = [{"metric": key, "value": json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value} for key, value in summary.items()]
    write_csv(output_dir / "metrics_summary.csv", summary_rows)
    (output_dir / "metrics_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_confusion_matrix(output_dir / "confusion_matrix.png", summary)
    write_report(DOC_PATH, output_dir, labels_path, per_video, summary)


def write_report(path: Path, output_dir: Path, labels_path: Path, per_video: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "# Labeled Dataset Validation - 2026-06-23",
        "",
        "## 1. Scope",
        "",
        "This validation is a reproducible offline / quasi-realtime experiment on labeled local datasets. It is not a live RTSP field demonstration.",
        "",
        "Boundaries:",
        "",
        "- Production code was not modified.",
        "- `.env` was not modified by this stage.",
        "- No model training was performed.",
        "- Temporal was forced disabled in the evaluation process.",
        "- 0-5 VisualRiskMarker was not enabled as realtime main functionality.",
        "- `MAIN_SYSTEM_REPORT_DRY_RUN=true` was forced in the evaluation process.",
        "- No real POST was sent.",
        "- No git add / commit was performed.",
        "",
        "## 2. Dataset",
        "",
        f"- labels.csv: `{labels_path}`",
        f"- evaluated videos: `{summary['evaluated_videos']}`",
        "- Label granularity: video-level fall / non_fall labels. `fall_start_sec` / `fall_end_sec` are supported by the CSV schema but blank in the generated default labels.",
        "",
        "## 3. Models And Runtime Chain",
        "",
        f"- YOLO person: `{summary['models']['person']}`",
        f"- YOLO fall detector: `{summary['models']['fall']}`",
        f"- Pose provider: `{summary['models']['pose_provider']}`",
        f"- YOLO11 pose path: `{summary['models']['yolo11_pose']}`",
        f"- YOLO pose fallback path: `{summary['models']['yolo_pose']}`",
        "- ByteTrack: `ultralytics.trackers.byte_tracker.BYTETracker`",
        f"- Temporal enabled: `{summary['models']['temporal_enabled']}`",
        f"- Reporter dry-run: `{summary['models']['dry_run']}`",
        "",
        "## 4. Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| TP | {summary['tp']} |",
        f"| FP | {summary['fp']} |",
        f"| FN | {summary['fn']} |",
        f"| TN | {summary['tn']} |",
        f"| Precision | {summary['precision']} |",
        f"| Recall | {summary['recall']} |",
        f"| F1-score | {summary['f1']} |",
        f"| False Positive Rate | {summary['false_positive_rate']} |",
        f"| Avg offline processing FPS | {summary['avg_offline_processing_fps']} |",
        f"| Avg total model latency ms | {summary['avg_total_model_latency_ms']} |",
        f"| Avg pose attached rate | {summary['avg_pose_attached_rate']} |",
        f"| Avg keypoint count | {summary['avg_keypoint_count']} |",
        f"| Avg keypoint_count=17 rate | {summary['avg_keypoint_count_17_rate']} |",
        f"| Avg skeleton confidence | {summary['avg_skeleton_confidence']} |",
        f"| Dry-run all videos | {summary['dry_run_all']} |",
        f"| No real POST all videos | {summary['no_real_post_all']} |",
        "",
        f"Scene false positives: `{json.dumps(summary['scene_false_positives'], ensure_ascii=False)}`",
        "",
        "## 5. Per-video Results",
        "",
        "| Label | Scene | Outcome | Predicted | Peak State | Peak Risk | Fall Frames | Pose Attach Rate | Reporter | Video |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in per_video:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["label"]),
                    str(row["scene"]),
                    str(row["outcome"]),
                    str(row["predicted_fall"]),
                    str(row["fall_state_peak"]),
                    str(row["risk_level_peak"]),
                    str(row["fall_model_frames"]),
                    str(row["pose_attached_rate"]),
                    str(row["reporter_last_post_status"]),
                    Path(str(row["video_path"])).name,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 6. Artifacts",
            "",
            f"- `{output_dir / 'metrics_summary.csv'}`",
            f"- `{output_dir / 'per_video_results.csv'}`",
            f"- `{output_dir / 'metrics_summary.json'}`",
            f"- `{output_dir / 'confusion_matrix.png'}`",
            f"- `{output_dir / 'sample_frames'}`",
            f"- `{output_dir / 'frame_results.jsonl'}`",
            "",
            "## 7. Acceptance Interpretation",
            "",
            "- Fall videos are counted positive only when current runtime output fields reach `fallen_candidate` / `fallen_confirmed` or `high` / `critical`.",
            "- Non-fall videos are counted false positive when those same runtime fields reach a positive state.",
            "- Pose is evaluated without keypoint labels by pose_attached rate, average keypoint count, keypoint_count=17 rate, skeleton confidence, rejected_reason distribution, and pose latency.",
            "- Reporter safety passes only if dry-run remains true and no real POST is observed.",
            "",
            "## 8. Demo Positioning",
            "",
            "The fall recognition claim should be grounded in labeled dataset metrics and the existing local replay end-to-end evidence. RTSP camera remains an optional online-ingest demonstration only, not the main proof of fall recognition stability.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]], append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_confusion_matrix(path: Path, summary: dict[str, Any]) -> None:
    img = np.full((360, 480, 3), 255, dtype=np.uint8)
    cv2.putText(img, "Confusion Matrix", (115, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 20, 20), 2)
    x0, y0, w, h = 120, 90, 140, 90
    cells = [
        ("TP", summary["tp"], x0, y0),
        ("FN", summary["fn"], x0 + w, y0),
        ("FP", summary["fp"], x0, y0 + h),
        ("TN", summary["tn"], x0 + w, y0 + h),
    ]
    for name, value, x, y in cells:
        color = (218, 245, 225) if name in {"TP", "TN"} else (230, 225, 255)
        cv2.rectangle(img, (x, y), (x + w, y + h), color, -1)
        cv2.rectangle(img, (x, y), (x + w, y + h), (80, 80, 80), 2)
        cv2.putText(img, name, (x + 48, y + 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (20, 20, 20), 2)
        cv2.putText(img, str(value), (x + 60, y + 68), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (20, 20, 20), 2)
    cv2.putText(img, "Actual fall", (25, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1)
    cv2.putText(img, "Actual non-fall", (5, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1)
    cv2.putText(img, "Pred fall", (142, 310), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1)
    cv2.putText(img, "Pred non-fall", (258, 310), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1)
    cv2.imwrite(str(path), img)


def draw_object(frame: np.ndarray, obj, color: tuple[int, int, int]) -> None:
    x1, y1, x2, y2 = [int(round(float(v))) for v in obj.bbox]
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    label = f"{obj.label}#{obj.track_id if obj.track_id is not None else '-'}"
    state = (obj.fall_decision or {}).get("fall_state") if isinstance(obj.fall_decision, dict) else None
    if state:
        label += f" {state}"
    cv2.putText(frame, label, (max(0, x1), max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    pose = obj.pose if isinstance(obj.pose, dict) else None
    keypoints = pose.get("keypoints") if isinstance(pose, dict) else []
    for point in keypoints or []:
        try:
            if float(point.get("confidence") or 0.0) < 0.2:
                continue
            cv2.circle(frame, (int(point["x"]), int(point["y"])), 3, (255, 255, 255), -1)
        except Exception:
            continue


def runtime_positive(obj) -> bool:
    decision = obj.fall_decision or {}
    alarm = obj.alarm_preview or {}
    state = str(decision.get("fall_state") or decision.get("state") or "").lower()
    risk = str(alarm.get("risk_level") or decision.get("risk_level") or "").lower()
    return state in POSITIVE_STATES or risk in POSITIVE_RISKS or bool(alarm.get("confirmed"))


def best_person(objects) -> Any | None:
    people = [item for item in objects if getattr(item, "label", "") == "person"]
    if not people:
        return None
    return max(people, key=lambda item: float(getattr(item, "confidence", 0.0) or 0.0))


def best_score(obj) -> float | None:
    if obj is None:
        return None
    values = []
    for payload in [obj.alarm_preview or {}, obj.fall_decision or {}]:
        for key in ["fall_probability", "fall_score"]:
            try:
                if payload.get(key) is not None:
                    values.append(float(payload[key]))
            except Exception:
                pass
    return round(max(values), 4) if values else None


def event_metadata(obj) -> dict[str, Any]:
    if obj is None:
        return {}
    for payload in [obj.temporal or {}, obj.fall_decision or {}, obj.alarm_preview or {}]:
        metadata = payload.get("event_metadata") if isinstance(payload, dict) else None
        if isinstance(metadata, dict):
            event = metadata.get("event")
            if isinstance(event, dict):
                return event
            return metadata
    return {}


def should_save_sample(row: dict[str, Any]) -> bool:
    return bool(row.get("runtime_positive") or row.get("fall_model_count") or row.get("pose_attached"))


def failed_video_row(label: LabelRow, reason: str) -> dict[str, Any]:
    expected = label.label == "fall"
    return {
        "video_path": str(label.video_path),
        "label": label.label,
        "scene": label.scene,
        "notes": label.notes,
        "camera_id": "",
        "frame_width": 0,
        "frame_height": 0,
        "native_fps": 0,
        "native_frame_count": 0,
        "frame_stride": 0,
        "max_frames_per_video": 0,
        "processed_frames": 0,
        "offline_elapsed_sec": 0,
        "offline_processing_fps": 0,
        "person_frames": 0,
        "fall_model_frames": 0,
        "tracked_frames": 0,
        "pose_attached_frames": 0,
        "pose_attached_rate": 0,
        "avg_keypoint_count": 0,
        "keypoint_count_17_rate": 0,
        "avg_skeleton_confidence": 0,
        "pose_rejected_reasons": "{}",
        "avg_person_latency_ms": 0,
        "avg_fall_latency_ms": 0,
        "avg_pose_latency_ms": 0,
        "avg_total_model_latency_ms": 0,
        "fall_state_peak": "",
        "risk_level_peak": "",
        "max_fall_score": 0,
        "predicted_fall": False,
        "confirmed_fall": False,
        "outcome": "FN" if expected else "TN",
        "first_positive_timestamp_ms": None,
        "first_confirmed_timestamp_ms": None,
        "first_positive_latency_ms": None,
        "first_confirmed_latency_ms": None,
        "incident_id": None,
        "reporter_dry_run": True,
        "reporter_last_post_status": f"not_run:{reason}",
        "reporter_no_real_post": True,
    }


def wait_for_reporter(reporter) -> None:
    for _ in range(20):
        status = reporter.status()
        if int(status.get("queue_size") or 0) == 0:
            time.sleep(0.05)
            return
        time.sleep(0.05)


def safe_rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def safe_avg(values) -> float:
    nums = []
    for value in values:
        try:
            if value is not None and value != "":
                nums.append(float(value))
        except Exception:
            continue
    return round(sum(nums) / len(nums), 4) if nums else 0.0


def reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("pose_rejected_reason") or "")
        if not reason:
            continue
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def peak_value(values: list[str], rank: dict[str, int]) -> str:
    best = ""
    best_rank = -1
    for value in values:
        value = value.lower()
        score = rank.get(value, -1)
        if score > best_rank:
            best = value
            best_rank = score
    return best


def first_non_empty(values) -> Any | None:
    for value in values:
        if value:
            return value
    return None


def infer_scene(path: Path, scene_tags: list[str]) -> str:
    tags = [str(tag).lower() for tag in scene_tags]
    tag_text = " ".join(tags)
    name_text = " ".join(part.lower() for part in [path.stem, path.parent.name, path.parent.parent.name])
    text = f"{tag_text} {name_text}"
    if "no_person" in text:
        return "no_person"
    if "squat" in text:
        return "squat"
    if "sitting" in text or "sit" in text:
        return "sit"
    if "walking" in text or "walk" in text or "adl" in tags:
        return "walk"
    if "lying" in text or "lie" in text:
        return "lie_down_non_fall"
    if "fall" in tags or path.parent.name.lower() == "fall":
        return "fall"
    return "unknown"


def normalize_label(value: Any) -> str:
    label = str(value or "").strip().lower()
    if label in {"fall", "fallen", "positive", "1", "true"}:
        return "fall"
    if label in {"non_fall", "non-fall", "adl", "negative", "0", "false"}:
        return "non_fall"
    raise ValueError(f"unsupported label: {value!r}")


def parse_optional_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    return float(text)


def safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("._") or "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Labeled dataset validation for the current vision fall chain.")
    parser.add_argument("--output-dir", type=Path, default=ARTIFACT_DIR)
    parser.add_argument("--labels", type=Path, default=ARTIFACT_DIR / "labels.csv")
    parser.add_argument("--make-labels", action="store_true")
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--max-frames-per-video", type=int, default=36)
    parser.add_argument("--public-fall", type=int, default=2)
    parser.add_argument("--public-non-fall", type=int, default=2)
    parser.add_argument("--local", type=int, default=4)
    parser.add_argument("--hard-negative", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.make_labels or not args.labels.exists():
        make_default_labels(
            args.labels,
            max_public_fall=args.public_fall,
            max_public_non_fall=args.public_non_fall,
            max_local=args.local,
            max_hard_negative=args.hard_negative,
        )
    labels = load_labels(args.labels)
    if not labels:
        raise SystemExit(f"no labels found in {args.labels}")
    frame_results = args.output_dir / "frame_results.jsonl"
    if frame_results.exists():
        frame_results.unlink()
    evaluator = LabeledDatasetEvaluator(
        output_dir=args.output_dir,
        frame_stride=args.frame_stride,
        max_frames_per_video=args.max_frames_per_video,
    )
    per_video, summary = evaluator.evaluate(labels)
    write_outputs(args.output_dir, args.labels, per_video, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
