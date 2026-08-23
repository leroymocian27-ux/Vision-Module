from __future__ import annotations

import threading
import time

import numpy as np

from app.ai.inference_guard import current_ultralytics_inference_owner, ultralytics_inference_lock
from app.core.config import Settings
from app.core.logger import get_logger
from app.monitoring.metrics import FPSMeter
from app.pose.placeholders import (
    POSE_DISABLED_PROVIDER,
    POSE_DISABLED_REASON,
    build_pose_placeholder,
    effective_pose_provider,
    pose_runtime_enabled,
)
from app.pose.pose_estimator import PoseEstimator
from app.pose.schemas import PoseStatus
from app.schemas.vision_result import DetectedObject

logger = get_logger(__name__)


class PoseService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._estimator: PoseEstimator | None = None
        self._fps: dict[str, FPSMeter] = {}
        self._last_run_at: dict[str, float] = {}
        self._last_error: dict[str, str | None] = {}
        self._last_inference_latency_ms: dict[str, float | None] = {}
        self._slow_inference_count: dict[str, int] = {}
        self._skipped_due_to_busy: dict[str, int] = {}
        self._skip_reasons: dict[str, dict[str, int]] = {}
        self._worker_tick_count: dict[str, int] = {}
        self._inference_attempt_count: dict[str, int] = {}
        self._inference_success_count: dict[str, int] = {}
        self._pose_target_object_count: dict[str, int] = {}
        self._pose_attached_object_count: dict[str, int] = {}
        self._last_context: dict[str, dict[str, object]] = {}
        self._circuit_open_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def enrich(
        self,
        camera_id: str,
        frame: np.ndarray,
        objects: list[DetectedObject],
        frame_seq: int | None = None,
        tracking_frame_seq: int | None = None,
        frame_age_ms: float | None = None,
        frame_timestamp: str | None = None,
    ) -> list[DetectedObject]:
        if self.placeholder_mode:
            return self._attach_placeholders(
                objects,
                frame_seq=frame_seq,
                tracking_frame_seq=tracking_frame_seq,
                frame_age_ms=frame_age_ms,
                frame_timestamp=frame_timestamp,
            )
        if not self._should_run(camera_id):
            self.record_skip(camera_id, "pose_fps_throttle")
            return objects
        if self._is_circuit_open(camera_id):
            self.record_skip(camera_id, "circuit_open")
            return objects

        try:
            estimator = self._get_estimator()
            target_objects = self._select_pose_targets(objects)
            if not target_objects:
                self.record_skip(camera_id, "no_pose_targets")
                return objects
            lock_blocking, lock_timeout = self._pose_lock_options()
            with ultralytics_inference_lock(
                blocking=lock_blocking,
                owner=f"pose:{self.provider_name}",
                timeout=lock_timeout,
            ) as acquired:
                if not acquired:
                    owner = current_ultralytics_inference_owner()
                    with self._lock:
                        self._skipped_due_to_busy[camera_id] = self._skipped_due_to_busy.get(camera_id, 0) + 1
                        reasons = self._skip_reasons.setdefault(camera_id, {})
                        reasons["busy"] = reasons.get("busy", 0) + 1
                        if owner:
                            owner_reason = f"busy_by_{owner}"
                            reasons[owner_reason] = reasons.get(owner_reason, 0) + 1
                    return objects
                started_at = time.monotonic()
                with self._lock:
                    self._last_run_at[camera_id] = started_at
                self._record_inference_attempt(camera_id, len(target_objects))
                pose_by_track = estimator.estimate(frame, target_objects)
            latency_ms = (time.monotonic() - started_at) * 1000
            self._record_latency(camera_id, latency_ms)
            self._record_inference_success(camera_id)
            pose_debug = getattr(estimator, "last_debug", {})
            pose_debug_by_track = getattr(estimator, "last_debug_by_track", {})
            pose_frame_delta = (
                abs(frame_seq - tracking_frame_seq)
                if frame_seq is not None and tracking_frame_seq is not None
                else None
            )
            enriched: list[DetectedObject] = []
            attached_count = 0
            rejected_reasons: dict[str, int] = {}
            quality_levels: list[str] = []
            for item in objects:
                pose = pose_by_track.get(item.track_id) if item.track_id is not None else None
                pose_payload = self._build_pose_payload(
                    item=item,
                    pose=pose,
                    pose_debug=pose_debug,
                    pose_debug_by_track=pose_debug_by_track,
                    frame_seq=frame_seq,
                    tracking_frame_seq=tracking_frame_seq,
                    pose_frame_delta=pose_frame_delta,
                    frame_age_ms=frame_age_ms,
                    frame_timestamp=frame_timestamp,
                )
                quality_level = self._pose_payload_quality_level(pose_payload)
                if quality_level:
                    quality_levels.append(quality_level)
                if self._pose_payload_has_visible_keypoints(pose_payload):
                    attached_count += 1
                reason = self._pose_payload_rejected_reason(pose_payload)
                if reason:
                    rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
                enriched.append(item.model_copy(update={"pose": pose_payload}))
            with self._lock:
                self._pose_attached_object_count[camera_id] = (
                    self._pose_attached_object_count.get(camera_id, 0) + attached_count
                )
                reasons = self._skip_reasons.setdefault(camera_id, {})
                if attached_count <= 0:
                    reasons["no_pose_attached"] = reasons.get("no_pose_attached", 0) + 1
                for reason, count in rejected_reasons.items():
                    reasons[reason] = reasons.get(reason, 0) + count
                self._fps.setdefault(camera_id, FPSMeter()).tick()
                self._last_error[camera_id] = None
                self._last_context[camera_id] = {
                    **self._last_context.get(camera_id, {}),
                    "selected_track_id": pose_debug.get("selected_track_id"),
                    "keypoint_inside_bbox_ratio": pose_debug.get("keypoint_inside_bbox_ratio"),
                    "keypoint_inside_source_bbox_ratio": pose_debug.get("keypoint_inside_source_bbox_ratio"),
                    "candidate_iou": pose_debug.get("candidate_iou"),
                    "pose_track_match_score": pose_debug.get("pose_track_match_score"),
                    "pose_match_iou": pose_debug.get("pose_match_iou"),
                    "pose_match_center_distance_ratio": pose_debug.get("pose_match_center_distance_ratio"),
                    "pose_bounds": pose_debug.get("pose_bounds"),
                    "torso_inside_bbox": pose_debug.get("torso_inside_bbox"),
                    "skeleton_confidence": pose_debug.get("skeleton_confidence"),
                    "visible_keypoint_count": pose_debug.get("visible_keypoint_count"),
                    "filtered_keypoints_count": pose_debug.get("filtered_keypoints_count"),
                    "dropped_keypoints_count": pose_debug.get("dropped_keypoints_count"),
                    "dropped_reasons": pose_debug.get("dropped_reasons"),
                    "rejected_reason": pose_debug.get("rejected_reason"),
                    "pose_model_path": pose_debug.get("model_path"),
                    "pose_frame_seq": frame_seq,
                    "tracking_frame_seq": tracking_frame_seq,
                    "pose_tracking_seq_delta": pose_frame_delta,
                    "pose_frame_age_ms": round(frame_age_ms, 2) if frame_age_ms is not None else None,
                    "pose_quality_level": self._best_pose_quality_level(quality_levels),
                    "recorded_at": time.monotonic(),
                }
            return enriched
        except Exception as exc:
            logger.exception("pose_enrich_failed camera_id=%s", camera_id)
            with self._lock:
                self._last_error[camera_id] = str(exc)
            return self._attach_placeholders(
                objects,
                frame_seq=frame_seq,
                tracking_frame_seq=tracking_frame_seq,
                frame_age_ms=frame_age_ms,
                frame_timestamp=frame_timestamp,
                reason="pose_enrich_failed",
            )

    @property
    def placeholder_mode(self) -> bool:
        enable_pose = getattr(self.settings, "enable_pose", True)
        pose_provider = getattr(self.settings, "pose_provider", POSE_DISABLED_PROVIDER)
        return not pose_runtime_enabled(enable_pose, pose_provider)

    @property
    def provider_name(self) -> str:
        enable_pose = getattr(self.settings, "enable_pose", True)
        pose_provider = getattr(self.settings, "pose_provider", POSE_DISABLED_PROVIDER)
        return effective_pose_provider(enable_pose, pose_provider)

    def build_placeholder_payload(
        self,
        item: DetectedObject,
        *,
        frame_seq: int | None = None,
        tracking_frame_seq: int | None = None,
        frame_age_ms: float | None = None,
        frame_timestamp: str | None = None,
        reason: str | None = None,
    ) -> dict | None:
        if item.label != "person":
            return None
        extra_debug = {}
        if reason:
            extra_debug["runtime_reason"] = reason
        return build_pose_placeholder(
            item,
            frame_seq=frame_seq,
            tracking_frame_seq=tracking_frame_seq,
            frame_age_ms=frame_age_ms,
            frame_timestamp=frame_timestamp,
            extra_debug=extra_debug,
        )

    def _attach_placeholders(
        self,
        objects: list[DetectedObject],
        *,
        frame_seq: int | None = None,
        tracking_frame_seq: int | None = None,
        frame_age_ms: float | None = None,
        frame_timestamp: str | None = None,
        reason: str | None = None,
    ) -> list[DetectedObject]:
        enriched: list[DetectedObject] = []
        for item in objects:
            pose_payload = self.build_placeholder_payload(
                item,
                frame_seq=frame_seq,
                tracking_frame_seq=tracking_frame_seq,
                frame_age_ms=frame_age_ms,
                frame_timestamp=frame_timestamp,
                reason=reason or POSE_DISABLED_REASON,
            )
            enriched.append(item.model_copy(update={"pose": pose_payload}))
        return enriched

    @staticmethod
    def _build_pose_payload(
        *,
        item: DetectedObject,
        pose,
        pose_debug: dict[str, object],
        pose_debug_by_track: dict[int, dict[str, object]] | None,
        frame_seq: int | None,
        tracking_frame_seq: int | None,
        pose_frame_delta: int | None,
        frame_age_ms: float | None,
        frame_timestamp: str | None,
    ) -> dict | None:
        if pose is None:
            return None
        pose_payload = pose.model_dump()
        source_bbox = [float(value) for value in item.bbox]
        item_debug = (
            pose_debug_by_track.get(int(item.track_id))
            if pose_debug_by_track is not None and item.track_id is not None and int(item.track_id) in pose_debug_by_track
            else (pose_debug if item.track_id == pose_debug.get("selected_track_id") else {})
        )
        pose_bounds = pose_payload.get("pose_bbox")
        if not (isinstance(pose_bounds, list) and len(pose_bounds) == 4):
            pose_bounds = item_debug.get("pose_bounds")
        pose_bbox = (
            [float(value) for value in pose_bounds]
            if isinstance(pose_bounds, list) and len(pose_bounds) == 4
            else list(source_bbox)
        )
        pose_payload.update(
            {
                "track_id": pose_payload.get("track_id", item.track_id),
                "source_track_id": item.track_id,
                "source_bbox": source_bbox,
                "pose_bbox": pose_bbox,
                "pose_track_match_score": pose_payload.get("pose_track_match_score"),
                "pose_frame_seq": frame_seq,
                "pose_timestamp": frame_timestamp,
            }
        )
        if pose_payload.get("track_id") != item.track_id or pose_payload.get("source_track_id") != item.track_id:
            return {
                "track_id": pose_payload.get("track_id"),
                "source_track_id": pose_payload.get("source_track_id"),
                "source_bbox": source_bbox,
                "pose_bbox": pose_bbox,
                "pose_track_match_score": pose_payload.get("pose_track_match_score"),
                "pose_frame_seq": frame_seq,
                "pose_timestamp": frame_timestamp,
                "keypoints": [],
                "skeleton_confidence": pose_payload.get("skeleton_confidence", 0.0),
                "pose_quality_level": "pose_track_mismatch",
                "debug": {
                    "rejected_reason": "pose_track_mismatch",
                    "pose_frame_seq": frame_seq,
                    "tracking_frame_seq": tracking_frame_seq,
                    "pose_tracking_seq_delta": pose_frame_delta,
                    "pose_frame_age_ms": round(frame_age_ms, 2) if frame_age_ms is not None else None,
                    "pose_model_path": item_debug.get("model_path"),
                },
            }
        if item_debug:
            pose_payload["debug"] = {
                "keypoint_inside_bbox_ratio": item_debug.get("keypoint_inside_bbox_ratio"),
                "keypoint_inside_source_bbox_ratio": item_debug.get("keypoint_inside_source_bbox_ratio"),
                "candidate_iou": item_debug.get("candidate_iou"),
                "pose_track_match_score": item_debug.get("pose_track_match_score"),
                "pose_match_iou": item_debug.get("pose_match_iou"),
                "pose_match_center_distance_ratio": item_debug.get("pose_match_center_distance_ratio"),
                "pose_bounds": item_debug.get("pose_bounds"),
                "torso_inside_bbox": item_debug.get("torso_inside_bbox"),
                "skeleton_confidence": item_debug.get("skeleton_confidence"),
                "visible_keypoint_count": item_debug.get("visible_keypoint_count"),
                "filtered_keypoints_count": item_debug.get("filtered_keypoints_count"),
                "dropped_keypoints_count": item_debug.get("dropped_keypoints_count"),
                "dropped_reasons": item_debug.get("dropped_reasons"),
                "raw_keypoints": item_debug.get("raw_keypoints"),
                "pose_bounds_input_points": item_debug.get("pose_bounds_input_points"),
                "dropped_keypoints": item_debug.get("dropped_keypoints"),
                "rejected_reason": item_debug.get("rejected_reason"),
                "pose_frame_seq": frame_seq,
                "tracking_frame_seq": tracking_frame_seq,
                "pose_tracking_seq_delta": pose_frame_delta,
                "pose_frame_age_ms": round(frame_age_ms, 2) if frame_age_ms is not None else None,
                "pose_model_path": item_debug.get("model_path"),
            }
        pose_payload["pose_quality_level"] = PoseService._classify_pose_payload(pose_payload)
        return pose_payload

    def status(self, camera_id: str | None = None) -> PoseStatus:
        with self._lock:
            fps = self._fps.get(camera_id or "")
            last_error = self._last_error.get(camera_id or "")
            latency_ms = self._last_inference_latency_ms.get(camera_id or "")
            slow_count = self._slow_inference_count.get(camera_id or "", 0)
            skipped = self._skipped_due_to_busy.get(camera_id or "", 0)
            worker_ticks = self._worker_tick_count.get(camera_id or "", 0)
            attempts = self._inference_attempt_count.get(camera_id or "", 0)
            successes = self._inference_success_count.get(camera_id or "", 0)
            target_count = self._pose_target_object_count.get(camera_id or "", 0)
            attached_count = self._pose_attached_object_count.get(camera_id or "", 0)
            skip_reasons = dict(self._skip_reasons.get(camera_id or "", {}))
            open_until = self._circuit_open_until.get(camera_id or "", 0.0)
            context = self._last_context.get(camera_id or "", {})
            remaining_ms = max(0.0, (open_until - time.monotonic()) * 1000) if open_until else None
        return PoseStatus(
            pose_enabled=not self.placeholder_mode,
            pose_provider=self.provider_name,
            pose_pipeline_removed=self.placeholder_mode,
            placeholder_reason=POSE_DISABLED_REASON if self.placeholder_mode else None,
            pose_fps=fps.fps if fps else 0.0,
            last_inference_latency_ms=latency_ms,
            slow_inference_count=slow_count,
            skipped_due_to_busy=skipped,
            worker_tick_count=worker_ticks,
            inference_attempt_count=attempts,
            inference_success_count=successes,
            pose_target_object_count=target_count,
            pose_attached_object_count=attached_count,
            pose_valid_rate=round(attached_count / target_count, 4) if target_count else 0.0,
            inference_success_rate=round(successes / attempts, 4) if attempts else 0.0,
            skip_reasons=skip_reasons,
            circuit_open=bool(remaining_ms and remaining_ms > 0),
            circuit_cooldown_remaining_ms=remaining_ms,
            last_error=last_error,
            selected_track_id=context.get("selected_track_id"),
            keypoint_inside_bbox_ratio=context.get("keypoint_inside_bbox_ratio"),
            keypoint_inside_source_bbox_ratio=context.get("keypoint_inside_source_bbox_ratio"),
            candidate_iou=context.get("candidate_iou"),
            pose_track_match_score=context.get("pose_track_match_score"),
            pose_match_iou=context.get("pose_match_iou"),
            pose_match_center_distance_ratio=context.get("pose_match_center_distance_ratio"),
            pose_bounds=context.get("pose_bounds"),
            torso_inside_bbox=context.get("torso_inside_bbox"),
            skeleton_confidence=context.get("skeleton_confidence"),
            rejected_reason=context.get("rejected_reason"),
            pose_frame_seq=context.get("pose_frame_seq"),
            tracking_frame_seq=context.get("tracking_frame_seq"),
            pose_tracking_seq_delta=context.get("pose_tracking_seq_delta"),
            pose_frame_age_ms=context.get("pose_frame_age_ms"),
            pose_model_path=context.get("pose_model_path") or self._configured_pose_model_path(),
            pose_quality_level=context.get("pose_quality_level"),
        )

    def _configured_pose_model_path(self) -> str | None:
        provider = str(self.provider_name or "").strip().lower()
        if provider in {"yolo11_legacy", "branch4_legacy"}:
            return getattr(self.settings, "yolo11_pose_model_path", None)
        if provider == "yolo":
            return getattr(self.settings, "yolo_pose_model_path", None)
        if provider == "rtmpose_onnx":
            return getattr(self.settings, "rtmpose_onnx_model_path", None)
        if provider == "mmpose":
            return getattr(self.settings, "rtmpose_checkpoint_path", None)
        return (
            getattr(self.settings, "yolo11_pose_model_path", None)
            or getattr(self.settings, "yolo_pose_model_path", None)
            or getattr(self.settings, "rtmpose_onnx_model_path", None)
        )

    def record_worker_tick(self, camera_id: str) -> None:
        with self._lock:
            self._worker_tick_count[camera_id] = self._worker_tick_count.get(camera_id, 0) + 1

    def record_context(
        self,
        camera_id: str,
        *,
        detection_objects_count: int,
        tracking_objects_count: int,
        target_objects_count: int,
        identity_state: str | None,
    ) -> None:
        with self._lock:
            self._last_context[camera_id] = {
                "detection_objects_count": detection_objects_count,
                "tracking_objects_count": tracking_objects_count,
                "target_objects_count": target_objects_count,
                "identity_state": identity_state,
                "recorded_at": time.monotonic(),
            }

    def record_detection_fallback_context(self, camera_id: str, detection_objects_count: int) -> None:
        self.record_context(
            camera_id,
            detection_objects_count=detection_objects_count,
            tracking_objects_count=0,
            target_objects_count=0,
            identity_state="fallback_detection",
        )

    def record_skip(self, camera_id: str, reason: str) -> None:
        with self._lock:
            reasons = self._skip_reasons.setdefault(camera_id, {})
            reasons[reason] = reasons.get(reason, 0) + 1

    def record_desync(
        self,
        camera_id: str,
        *,
        pose_frame_seq: int | None,
        tracking_frame_seq: int | None,
        frame_age_ms: float | None,
        reason: str,
    ) -> None:
        with self._lock:
            self._last_context[camera_id] = {
                **self._last_context.get(camera_id, {}),
                "selected_track_id": None,
                "rejected_reason": reason,
                "pose_frame_seq": pose_frame_seq,
                "tracking_frame_seq": tracking_frame_seq,
                "pose_tracking_seq_delta": (
                    abs(pose_frame_seq - tracking_frame_seq)
                    if pose_frame_seq is not None and tracking_frame_seq is not None
                    else None
                ),
                "pose_frame_age_ms": round(frame_age_ms, 2) if frame_age_ms is not None else None,
                "recorded_at": time.monotonic(),
            }
            reasons = self._skip_reasons.setdefault(camera_id, {})
            reasons[reason] = reasons.get(reason, 0) + 1

    def _should_run(self, camera_id: str) -> bool:
        if self.settings.pose_fps <= 0:
            return False
        now = time.monotonic()
        min_interval = 1 / self.settings.pose_fps
        with self._lock:
            last_run_at = self._last_run_at.get(camera_id)
        return last_run_at is None or now - last_run_at >= min_interval

    def _is_circuit_open(self, camera_id: str) -> bool:
        now = time.monotonic()
        with self._lock:
            open_until = self._circuit_open_until.get(camera_id, 0.0)
            if open_until and now < open_until:
                self._last_run_at[camera_id] = now
                return True
            if open_until:
                self._circuit_open_until.pop(camera_id, None)
                self._slow_inference_count[camera_id] = 0
        return False

    def _record_latency(self, camera_id: str, latency_ms: float) -> None:
        max_ms = self.settings.pose_max_inference_ms
        with self._lock:
            self._last_inference_latency_ms[camera_id] = round(latency_ms, 2)
            if max_ms > 0 and latency_ms > max_ms:
                slow_count = self._slow_inference_count.get(camera_id, 0) + 1
                self._slow_inference_count[camera_id] = slow_count
                if slow_count >= self.settings.pose_slow_inference_circuit_breaker_count:
                    cooldown = self.settings.pose_circuit_breaker_cooldown_ms / 1000
                    self._circuit_open_until[camera_id] = time.monotonic() + cooldown
                    self._last_error[camera_id] = (
                        f"pose inference circuit open after {slow_count} slow runs "
                        f"(last={latency_ms:.0f}ms)"
                    )
            else:
                self._slow_inference_count[camera_id] = 0

    def _record_inference_attempt(self, camera_id: str, target_count: int) -> None:
        with self._lock:
            self._inference_attempt_count[camera_id] = self._inference_attempt_count.get(camera_id, 0) + 1
            self._pose_target_object_count[camera_id] = self._pose_target_object_count.get(camera_id, 0) + target_count

    def _record_inference_success(self, camera_id: str) -> None:
        with self._lock:
            self._inference_success_count[camera_id] = self._inference_success_count.get(camera_id, 0) + 1

    def _pose_lock_options(self) -> tuple[bool, float | None]:
        if not self.settings.pose_skip_when_inference_busy:
            return True, None
        wait_ms = max(0, self.settings.pose_inference_lock_wait_ms)
        if wait_ms <= 0:
            return False, None
        return True, wait_ms / 1000

    def _get_estimator(self) -> PoseEstimator:
        if self._estimator is not None:
            return self._estimator
        provider = self.provider_name
        if provider == POSE_DISABLED_PROVIDER:
            raise RuntimeError("pose runtime disabled in placeholder mode")
        if provider == "mock":
            from app.pose.mock_pose_estimator import MockPoseEstimator

            self._estimator = MockPoseEstimator()
        elif provider in {"yolo", "yolo_pose", "ultralytics"}:
            from app.pose.yolo_pose_estimator import YoloPoseEstimator

            self._estimator = YoloPoseEstimator(self.settings)
        elif provider in {"yolo11_legacy", "historical", "legacy_yolo11"}:
            from app.pose.yolo11_legacy_pose_estimator import Yolo11LegacyPoseEstimator

            self._estimator = Yolo11LegacyPoseEstimator(self.settings)
        elif provider in {"branch4_legacy", "branch4", "target_crop_legacy"}:
            from app.pose.branch4_legacy_pose_estimator import Branch4LegacyPoseEstimator

            self._estimator = Branch4LegacyPoseEstimator(self.settings)
        elif provider in {"rtmpose_onnx", "rtmpose", "rtm"}:
            from app.pose.rtmpose_onnx_estimator import RTMPoseOnnxEstimator

            self._estimator = RTMPoseOnnxEstimator(self.settings)
        elif provider in {"mmpose"}:
            from app.pose.rtmpose_estimator import RTMPoseEstimator

            self._estimator = RTMPoseEstimator(self.settings)
        else:
            raise RuntimeError(f"unsupported pose provider: {self.settings.pose_provider}")
        return self._estimator

    def _select_pose_targets(self, objects: list[DetectedObject]) -> list[DetectedObject]:
        provider = self.provider_name
        if provider in {"yolo11_legacy", "historical", "legacy_yolo11"}:
            candidates = [item for item in objects if item.track_id is not None and item.label == "person"]
            if any(item.is_target for item in candidates):
                return candidates
            return sorted(candidates, key=PoseService._area, reverse=True)
        if provider in {"branch4_legacy", "branch4", "target_crop_legacy"}:
            targets = [item for item in objects if item.is_target and item.track_id is not None and item.label == "person"]
            if targets:
                return targets[:1]
            candidates = [item for item in objects if item.track_id is not None and item.label == "person"]
            if not candidates:
                return []
            return [max(candidates, key=PoseService._area)]
        targets = [item for item in objects if item.is_target and item.track_id is not None]
        if targets:
            return targets[:1]
        candidates = [item for item in objects if item.track_id is not None]
        if not candidates:
            return []
        return [max(candidates, key=PoseService._area)]

    @staticmethod
    def _pose_payload_has_visible_keypoints(pose_payload: dict | None, threshold: float = 0.2) -> bool:
        if not isinstance(pose_payload, dict):
            return False
        debug = pose_payload.get("debug")
        if isinstance(debug, dict) and debug.get("rejected_reason"):
            return False
        keypoints = pose_payload.get("keypoints")
        if not isinstance(keypoints, list):
            return False
        for point in keypoints:
            if not isinstance(point, dict):
                continue
            try:
                if float(point.get("confidence") or 0.0) >= threshold:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    @staticmethod
    def _pose_payload_rejected_reason(pose_payload: dict | None) -> str | None:
        if not isinstance(pose_payload, dict):
            return None
        debug = pose_payload.get("debug")
        if not isinstance(debug, dict):
            return None
        reason = debug.get("rejected_reason")
        return str(reason) if reason else None

    @staticmethod
    def _pose_payload_quality_level(pose_payload: dict | None) -> str | None:
        if not isinstance(pose_payload, dict):
            return None
        level = pose_payload.get("pose_quality_level")
        return str(level) if level else PoseService._classify_pose_payload(pose_payload)

    @staticmethod
    def _classify_pose_payload(pose_payload: dict | None) -> str:
        if not isinstance(pose_payload, dict):
            return "pose_absent"
        reason = PoseService._pose_payload_rejected_reason(pose_payload)
        if reason == "pose_track_mismatch":
            return "pose_track_mismatch"
        if reason:
            return "low_quality"
        keypoints = pose_payload.get("keypoints")
        if not isinstance(keypoints, list):
            return "pose_absent"
        visible_count = 0
        for point in keypoints:
            if not isinstance(point, dict):
                continue
            try:
                if float(point.get("confidence") or 0.0) >= 0.2:
                    visible_count += 1
            except (TypeError, ValueError):
                continue
        if visible_count <= 0:
            return "low_quality"
        try:
            confidence = float(pose_payload.get("skeleton_confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if visible_count >= 8 and confidence >= 0.7:
            return "high_confidence"
        return "valid"

    @staticmethod
    def _best_pose_quality_level(levels: list[str]) -> str | None:
        if not levels:
            return None
        rank = {
            "pose_track_mismatch": 0,
            "pose_absent": 1,
            "low_quality": 2,
            "valid": 3,
            "high_confidence": 4,
        }
        return max(levels, key=lambda level: rank.get(level, -1))

    @staticmethod
    def _area(item: DetectedObject) -> float:
        x1, y1, x2, y2 = item.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)
