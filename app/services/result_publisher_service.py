from __future__ import annotations

import threading
import time

from app.core.config import Settings
from app.core.logger import get_logger
from app.events.pipeline import EventPipelineService
from app.detection.realtime_result_store import ObjectSnapshot, RealtimeResultStore
from app.fall.feature_builder import FallFeatureBuilder, FallFeatureContext
from app.fall.fusion import FallFusionService
from app.fall.unified_decision import UnifiedFallDecisionEngine
from app.monitoring.metrics import FPSMeter
from app.pose.placeholders import (
    build_pose_placeholder,
    pose_has_visible_keypoints,
    pose_runtime_enabled,
)
from app.schemas.common import utc_now_iso
from app.schemas.vision_result import DetectedObject, VisionResult
from app.services.fall_event_reporter_service import FallEventReporterService
from app.services.temporal_service import TemporalService
from app.streaming.result_channel_manager import ResultChannelManager

logger = get_logger(__name__)
STRONG_FALL_LABELS = {"fall", "fallen"}
TRANSITION_FALL_LABELS = {"falling"}
WEAK_FALL_LABELS = {"lying"}


class ResultPublisherService:
    def __init__(
        self,
        settings: Settings,
        realtime_store: RealtimeResultStore,
        result_channels: ResultChannelManager,
        temporal_service: TemporalService | None = None,
        fall_fusion_service: FallFusionService | None = None,
        fall_event_reporter: FallEventReporterService | None = None,
        event_pipeline: EventPipelineService | None = None,
    ) -> None:
        self.settings = settings
        self.realtime_store = realtime_store
        self.result_channels = result_channels
        self.temporal_service = temporal_service
        self.fall_feature_builder = FallFeatureBuilder()
        self.fall_fusion_service = fall_fusion_service
        self.unified_decision_engine = UnifiedFallDecisionEngine(settings)
        self.fall_event_reporter = fall_event_reporter
        self.event_pipeline = event_pipeline
        self._workers: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._fps: dict[str, FPSMeter] = {}
        self._last_error: dict[str, str | None] = {}
        self._last_detection_to_publish_lag_ms: dict[str, float | None] = {}
        self._fall_candidate_states: dict[str, dict[str, float | int]] = {}
        self._field_candidate_states: dict[str, dict[str, float | int]] = {}
        self._fall_hint_seen_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def start_for_camera(self, camera_id: str) -> None:
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing and existing.is_alive():
                return
            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._run_loop,
                args=(camera_id, stop_event),
                name=f"result-publisher-{camera_id}",
                daemon=True,
            )
            self._stops[camera_id] = stop_event
            self._fps[camera_id] = FPSMeter()
            self._workers[camera_id] = worker
            worker.start()

    def stop_for_camera(self, camera_id: str) -> None:
        with self._lock:
            stop_event = self._stops.pop(camera_id, None)
            worker = self._workers.pop(camera_id, None)
        if stop_event:
            stop_event.set()
        if worker and worker.is_alive():
            worker.join(timeout=3)

    def stop_all(self) -> None:
        for camera_id in list(self._workers.keys()):
            self.stop_for_camera(camera_id)

    def status_fps(self, camera_id: str) -> float:
        with self._lock:
            fps = self._fps.get(camera_id)
        return fps.fps if fps else 0.0

    def detection_to_publish_lag_ms(self, camera_id: str) -> float | None:
        with self._lock:
            return self._last_detection_to_publish_lag_ms.get(camera_id)

    def last_error(self, camera_id: str) -> str | None:
        with self._lock:
            return self._last_error.get(camera_id)

    def _run_loop(self, camera_id: str, stop_event: threading.Event) -> None:
        interval = 1 / max(self.settings.result_publish_fps, 1)
        logger.info("result_publisher_started camera_id=%s", camera_id)
        while not stop_event.is_set():
            try:
                result = self._build_result(camera_id)
                if result is not None:
                    if self.event_pipeline is not None:
                        try:
                            self.event_pipeline.observe_result(result)
                        except Exception:
                            logger.exception("event_pipeline_observe_failed camera_id=%s", camera_id)
                    if self.fall_event_reporter is not None:
                        # Persist confirmed-fall event metadata before any store/API publication.
                        self.fall_event_reporter.inspect_result(result)
                    self.realtime_store.update_published(result)
                    self.result_channels.publish(result)
                    with self._lock:
                        self._fps.setdefault(camera_id, FPSMeter()).tick()
                        self._last_error[camera_id] = None
                else:
                    with self._lock:
                        self._last_error[camera_id] = None
            except Exception as exc:
                logger.exception("result_publisher_error camera_id=%s", camera_id)
                with self._lock:
                    self._last_error[camera_id] = str(exc)
            stop_event.wait(interval)
        logger.info("result_publisher_stopped camera_id=%s", camera_id)

    def _build_result(self, camera_id: str) -> VisionResult | None:
        if self.settings.fusion_worker_enabled:
            fused = self._build_result_from_fused(camera_id)
            if fused is not None:
                return fused
            snapshot = self.build_result_snapshot(camera_id)
            if snapshot is not None:
                detector = dict(snapshot.detector or {})
                detector["result_source"] = "snapshot_fallback"
                return snapshot.model_copy(update={"detector": detector})
            return None
        return self.build_result_snapshot(camera_id)

    def build_result_snapshot(self, camera_id: str) -> VisionResult | None:
        pipeline = self.realtime_store.snapshot(camera_id)
        base = pipeline.latest_tracking or pipeline.latest_detection
        if base is None:
            return None
        if (time.monotonic() - base.monotonic_at) * 1000 > self.settings.stream_stale_threshold_ms:
            return None
        evidence_debug = self._evidence_debug(camera_id, base)

        objects = base.objects
        if self._is_fresh(pipeline.latest_pose, self.settings.pose_result_ttl_ms) and self._is_frame_aligned(
            base,
            pipeline.latest_pose,
        ):
            objects = self._merge_objects(objects, pipeline.latest_pose)
        if self._is_fresh(pipeline.latest_behavior, self.settings.behavior_result_ttl_ms):
            objects = self._merge_objects(objects, pipeline.latest_behavior)
        fall_detection = self._current_fall_detection(base, pipeline.latest_fall_detection)
        objects = self._ensure_pose_payloads(
            objects,
            frame_seq=base.frame_seq,
            frame_timestamp=base.timestamp,
        )
        objects = self.fall_feature_builder.build_for_objects(
            objects=objects,
            context=FallFeatureContext(
                frame_width=base.frame_width,
                frame_height=base.frame_height,
                fall_detection=fall_detection,
            ),
        )
        if self.settings.temporal_worker_enabled:
            if self._is_fresh(pipeline.latest_temporal, self.settings.temporal_result_ttl_ms) and self._is_frame_aligned(
                base,
                pipeline.latest_temporal,
                max_delta=self.settings.temporal_max_frame_delta,
            ):
                objects = self._merge_temporal_objects(objects, pipeline.latest_temporal)
        elif self.temporal_service is not None:
            objects = self.temporal_service.enrich(camera_id=camera_id, objects=objects)
            objects = self.fall_feature_builder.build_for_objects(
                objects=objects,
                context=FallFeatureContext(
                    frame_width=base.frame_width,
                    frame_height=base.frame_height,
                    fall_detection=fall_detection,
                ),
            )
        detection = pipeline.latest_detection
        person_detection_objects = [
            item for item in (detection.objects if detection is not None else []) if item.label == "person"
        ]
        if fall_detection is not None:
            self._remember_recent_fall_hint(camera_id, fall_detection)
            objects = self._merge_fall_detection(
                camera_id,
                objects,
                fall_detection.objects,
                person_detection_objects,
            )
            objects = self._merge_weak_fall_hints(camera_id, objects, fall_detection.objects)
        current_fall_objects = fall_detection.objects if fall_detection is not None else []
        objects = self._merge_field_fall_candidates(
            camera_id,
            objects,
            base.frame_width,
            base.frame_height,
            current_fall_objects,
            person_detection_objects,
        )
        objects = self.fall_feature_builder.build_for_objects(
            objects=objects,
            context=FallFeatureContext(
                frame_width=base.frame_width,
                frame_height=base.frame_height,
                fall_detection=fall_detection,
            ),
        )
        if self.fall_fusion_service is not None:
            objects = self.fall_fusion_service.enrich(camera_id=camera_id, objects=objects)
        objects = self._ensure_tracking_fields(objects)
        objects = self._apply_core_freshness_guard(objects, evidence_debug)
        objects = self._attach_evidence_debug(objects, evidence_debug)
        objects = self.unified_decision_engine.enrich(camera_id=camera_id, objects=objects)
        objects = self._apply_upright_recovery_guard(objects)

        detector = dict(detection.detector) if detection else {}
        detector["unified_decision_shadow_enabled"] = bool(
            self.settings.unified_decision_enabled and self.settings.unified_decision_shadow
        )
        detector["unified_decision_primary_enabled"] = bool(
            self.settings.unified_decision_enabled and self.settings.unified_decision_primary_enabled
        )
        if self.settings.fusion_evidence_debug_enabled:
            detector["evidence_freshness"] = evidence_debug["evidence_freshness"]
            detector["evidence_age_ms"] = evidence_debug["evidence_age_ms"]
            detector["evidence_frame_seq"] = evidence_debug["evidence_frame_seq"]
        detector["temporal_worker_enabled"] = bool(self.settings.temporal_worker_enabled)
        detector["fusion_worker_enabled"] = bool(self.settings.fusion_worker_enabled)
        detector["result_source"] = "snapshot"
        if fall_detection is not None:
            detector["fall_detector"] = fall_detection.detector
        elif pipeline.latest_fall_detection is not None:
            detector["fall_detector_skipped"] = {
                "reason": "stale_or_frame_misaligned",
                "fall_frame_seq": pipeline.latest_fall_detection.frame_seq,
                "base_frame_seq": base.frame_seq,
            }
        if detection is not None:
            lag_ms = round((time.monotonic() - detection.monotonic_at) * 1000, 2)
            with self._lock:
                self._last_detection_to_publish_lag_ms[camera_id] = lag_ms

        return VisionResult(
            camera_id=camera_id,
            timestamp=utc_now_iso(),
            frame_seq=base.frame_seq,
            frame_width=base.frame_width,
            frame_height=base.frame_height,
            objects=objects,
            detector=detector,
        )

    def _build_result_from_fused(self, camera_id: str) -> VisionResult | None:
        fused = self.realtime_store.latest_fused(camera_id)
        if fused is None:
            return None
        monotonic_at = fused.detector.get("_monotonic_at") if isinstance(fused.detector, dict) else None
        age_ms = self.realtime_store.age_ms(monotonic_at)
        if age_ms is not None and age_ms > self.settings.fused_result_ttl_ms:
            return None
        detector = dict(fused.detector or {})
        detector.pop("_monotonic_at", None)
        detector["result_source"] = "fusion_slot"
        return fused.model_copy(update={"detector": detector})

    def _apply_upright_recovery_guard(self, objects: list[DetectedObject]) -> list[DetectedObject]:
        guarded: list[DetectedObject] = []
        for item in objects:
            if item.label != "person" or not self._should_clear_unconfirmed_fall(item):
                guarded.append(item)
                continue
            previous_decision = dict(item.fall_decision or {})
            previous_alarm = dict(item.alarm_preview or {})
            recovery_payload = {
                "fall_state": "normal",
                "risk_level": "low",
                "fall_probability": min(float(previous_decision.get("fall_probability") or previous_alarm.get("fall_probability") or 0.0), 0.2),
                "source": "upright_recovery_guard",
                "previous_source": previous_decision.get("source") or previous_alarm.get("source"),
                "previous_fall_state": previous_decision.get("fall_state"),
                "previous_risk_level": previous_alarm.get("risk_level") or previous_decision.get("risk_level"),
                "rejected_reason": "upright_recovery_observed",
                "suppressed_reason": None,
                "confirm_source": None,
            }
            alarm_payload = {
                "confirmed": False,
                "risk_level": "low",
                "fall_probability": recovery_payload["fall_probability"],
                "source": "upright_recovery_guard",
                "previous_source": recovery_payload["previous_source"],
                "previous_fall_state": recovery_payload["previous_fall_state"],
                "previous_risk_level": recovery_payload["previous_risk_level"],
                "rejected_reason": "upright_recovery_observed",
                "suppressed_reason": None,
                "confirm_source": None,
            }
            fusion_debug = dict(item.fusion_debug or {})
            fusion_debug["upright_recovery_guard"] = True
            fusion_debug["upright_recovery_previous_state"] = recovery_payload["previous_fall_state"]
            guarded.append(
                item.model_copy(
                    update={
                        "fall_decision": recovery_payload,
                        "alarm_preview": alarm_payload,
                        "fusion_debug": fusion_debug,
                    }
                )
            )
        return guarded

    def _should_clear_unconfirmed_fall(self, item: DetectedObject) -> bool:
        fall_decision = item.fall_decision if isinstance(item.fall_decision, dict) else {}
        alarm_preview = item.alarm_preview if isinstance(item.alarm_preview, dict) else {}
        if alarm_preview.get("confirmed") is True or str(fall_decision.get("fall_state") or "") == "fallen_confirmed":
            return False
        state = str(fall_decision.get("fall_state") or "").lower()
        risk = str(alarm_preview.get("risk_level") or fall_decision.get("risk_level") or "").lower()
        if state not in {"falling", "fallen_candidate", "suppressed", "suspicious"} and risk not in {"medium", "high"}:
            return False
        features = item.features if isinstance(item.features, dict) else {}
        motion = features.get("motion") if isinstance(features.get("motion"), dict) else {}
        pose = features.get("pose") if isinstance(features.get("pose"), dict) else {}
        fall_hint = features.get("fall_hint") if isinstance(features.get("fall_hint"), dict) else {}
        temporal = item.temporal if isinstance(item.temporal, dict) else {}
        behavior = item.behavior if isinstance(item.behavior, dict) else {}
        behavior_state = str(behavior.get("behavior_state") or "").lower()
        if behavior_state in {"lying", "fallen"}:
            return False
        if bool(fall_hint.get("strong_hint")):
            return False
        label = str(fall_hint.get("strongest_label") or "").lower()
        if label in {"fall", "fallen"} and float(fall_hint.get("confidence") or 0.0) >= self.settings.fall_detector_confirm_min_probability:
            return False
        aspect = float(motion.get("aspect_ratio") or temporal.get("bbox_aspect_ratio") or 0.0)
        low_posture = bool(pose.get("low_posture") or temporal.get("low_posture"))
        if low_posture or aspect >= self.settings.field_fall_candidate_min_aspect:
            return False
        return True

    @staticmethod
    def _ensure_tracking_fields(objects: list[DetectedObject]) -> list[DetectedObject]:
        people = [item for item in objects if item.label == "person"]
        if not people:
            return objects
        if all(item.track_id is not None for item in people) and any(item.is_target for item in people):
            return objects

        next_track_id = 1
        used_track_ids = {int(item.track_id) for item in people if item.track_id is not None}
        while next_track_id in used_track_ids:
            next_track_id += 1
        has_target = any(item.is_target for item in people)
        promoted_target = False
        normalized: list[DetectedObject] = []
        for item in objects:
            if item.label != "person":
                normalized.append(item)
                continue
            updates = {}
            if item.track_id is None:
                while next_track_id in used_track_ids:
                    next_track_id += 1
                updates["track_id"] = next_track_id
                used_track_ids.add(next_track_id)
                next_track_id += 1
            if not has_target and not promoted_target:
                updates["is_target"] = True
                if item.identity_state is None:
                    updates["identity_state"] = "target_locked"
                promoted_target = True
            normalized.append(item.model_copy(update=updates) if updates else item)
        return normalized

    def _evidence_debug(self, camera_id: str, base: ObjectSnapshot) -> dict:
        detection = self.realtime_store.latest_with_freshness(
            camera_id,
            "detection",
            self.settings.person_detection_result_ttl_ms,
            base_frame_seq=base.frame_seq,
            max_frame_delta=self.settings.fusion_max_frame_delta_detection,
        )
        tracking = self.realtime_store.latest_with_freshness(
            camera_id,
            "tracking",
            self.settings.tracking_result_ttl_ms,
            base_frame_seq=base.frame_seq,
            max_frame_delta=self.settings.fusion_max_frame_delta_tracking,
        )
        fall_hint = self.realtime_store.latest_with_freshness(
            camera_id,
            "fall_hint",
            self.settings.fall_hint_result_ttl_ms,
            base_frame_seq=base.frame_seq,
            max_frame_delta=self.settings.fusion_max_frame_delta_fall_hint,
            disabled=not self.settings.fall_detector_enabled,
        )
        pose = self.realtime_store.latest_with_freshness(
            camera_id,
            "pose",
            self.settings.pose_result_ttl_ms,
            base_frame_seq=base.frame_seq,
            max_frame_delta=self.settings.pose_publish_max_frame_delta,
            disabled=not self.settings.enable_pose,
        )
        behavior = self.realtime_store.latest_with_freshness(
            camera_id,
            "behavior",
            self.settings.behavior_result_ttl_ms,
            base_frame_seq=base.frame_seq,
            disabled=not self.settings.enable_behavior,
        )
        temporal = self.realtime_store.latest_with_freshness(
            camera_id,
            "temporal",
            self.settings.temporal_result_ttl_ms,
            base_frame_seq=base.frame_seq,
            max_frame_delta=self.settings.temporal_max_frame_delta,
            disabled=not self.settings.enable_temporal or not self.settings.temporal_worker_enabled,
        )
        values = {
            "detection": detection,
            "tracking": tracking,
            "fall_hint": fall_hint,
            "pose": pose,
            "behavior": behavior,
            "temporal": temporal,
        }
        missing_conditions = [
            f"{name}_{item.state}"
            for name, item in values.items()
            if item.state not in {"fresh", "disabled"}
        ]
        confirm_blocked_by = [
            f"{name}_{values[name].state}"
            for name in ("detection", "tracking")
            if values[name].state != "fresh"
        ]
        return {
            "evidence_freshness": {name: item.state for name, item in values.items()},
            "evidence_age_ms": {name: item.age_ms for name, item in values.items()},
            "evidence_frame_seq": {name: item.frame_seq for name, item in values.items()},
            "evidence_frame_delta": {name: item.frame_delta for name, item in values.items()},
            "missing_conditions": missing_conditions,
            "confirm_blocked_by": confirm_blocked_by,
            "degraded_mode": bool(missing_conditions),
        }

    @staticmethod
    def _apply_core_freshness_guard(objects: list[DetectedObject], evidence_debug: dict) -> list[DetectedObject]:
        blocked_by = evidence_debug.get("confirm_blocked_by") or []
        if not blocked_by:
            return objects
        guarded: list[DetectedObject] = []
        for item in objects:
            alarm_preview = dict(item.alarm_preview or {})
            fall_decision = dict(item.fall_decision or {})
            changed = False
            if alarm_preview.get("confirmed") is True:
                alarm_preview["confirmed"] = False
                alarm_preview["suppressed_reason"] = "core_evidence_stale"
                alarm_preview["confirm_blocked_by"] = blocked_by
                changed = True
            if str(fall_decision.get("fall_state") or "").lower() in {"fallen_confirmed", "confirmed_fall"}:
                fall_decision["fall_state"] = "fallen_candidate"
                fall_decision["suppressed_reason"] = "core_evidence_stale"
                fall_decision["confirm_blocked_by"] = blocked_by
                changed = True
            guarded.append(
                item.model_copy(update={"alarm_preview": alarm_preview, "fall_decision": fall_decision})
                if changed
                else item
            )
        return guarded

    def _attach_evidence_debug(self, objects: list[DetectedObject], evidence_debug: dict) -> list[DetectedObject]:
        if not self.settings.fusion_evidence_debug_enabled:
            return objects
        attached: list[DetectedObject] = []
        for item in objects:
            debug = dict(item.fusion_debug or {})
            debug["evidence_freshness"] = evidence_debug["evidence_freshness"]
            debug["evidence_age_ms"] = evidence_debug["evidence_age_ms"]
            debug["evidence_frame_seq"] = evidence_debug["evidence_frame_seq"]
            debug["missing_conditions"] = evidence_debug["missing_conditions"]
            debug["confirm_blocked_by"] = evidence_debug["confirm_blocked_by"]
            debug["degraded_mode"] = evidence_debug["degraded_mode"]
            attached.append(item.model_copy(update={"fusion_debug": debug}))
        return attached

    @staticmethod
    def _merge_objects(base_objects: list[DetectedObject], snapshot: ObjectSnapshot) -> list[DetectedObject]:
        by_track = {
            item.track_id: item
            for item in snapshot.objects
            if item.track_id is not None
        }
        merged: list[DetectedObject] = []
        for item in base_objects:
            patch = by_track.get(item.track_id)
            if patch is None:
                merged.append(item)
                continue
            updates = {}
            if patch.pose is not None:
                updates["pose"] = ResultPublisherService._validated_pose_payload(item, patch.pose)
            if patch.behavior is not None:
                updates["behavior"] = patch.behavior
            if patch.person_id is not None:
                updates["person_id"] = patch.person_id
                updates["person_name"] = patch.person_name
                updates["identity_state"] = patch.identity_state
                updates["is_target"] = patch.is_target
            merged.append(item.model_copy(update=updates))
        return merged

    @staticmethod
    def _merge_temporal_objects(base_objects: list[DetectedObject], snapshot: ObjectSnapshot) -> list[DetectedObject]:
        by_track = {
            item.track_id: item
            for item in snapshot.objects
            if item.track_id is not None
        }
        merged: list[DetectedObject] = []
        for item in base_objects:
            patch = by_track.get(item.track_id)
            if patch is None:
                merged.append(item)
                continue
            updates = {}
            if patch.temporal is not None:
                updates["temporal"] = patch.temporal
            if patch.fall_decision is not None:
                updates["fall_decision"] = patch.fall_decision
            if patch.alarm_preview is not None:
                updates["alarm_preview"] = patch.alarm_preview
            if patch.features is not None:
                updates["features"] = patch.features
            if patch.fusion_debug is not None:
                updates["fusion_debug"] = {
                    **(item.fusion_debug or {}),
                    **patch.fusion_debug,
                }
            merged.append(item.model_copy(update=updates) if updates else item)
        return merged

    @staticmethod
    def _validated_pose_payload(item: DetectedObject, pose: dict) -> dict | None:
        expected_track_id = ResultPublisherService._coerce_track_id(item.track_id)
        if expected_track_id is None:
            return None
        pose_track_id = ResultPublisherService._coerce_track_id(pose.get("track_id"))
        source_track_id = ResultPublisherService._coerce_track_id(pose.get("source_track_id"))
        if pose_track_id != expected_track_id or source_track_id != expected_track_id:
            debug = dict(pose.get("debug") or {})
            debug["rejected_reason"] = "pose_track_mismatch"
            return {
                "track_id": pose_track_id,
                "source_track_id": source_track_id,
                "source_bbox": pose.get("source_bbox"),
                "pose_bbox": pose.get("pose_bbox"),
                "pose_frame_seq": pose.get("pose_frame_seq") or debug.get("pose_frame_seq"),
                "pose_timestamp": pose.get("pose_timestamp"),
                "keypoints": [],
                "skeleton_confidence": float(pose.get("skeleton_confidence") or 0.0),
                "debug": debug,
            }
        return pose

    def _ensure_pose_payloads(
        self,
        objects: list[DetectedObject],
        *,
        frame_seq: int | None,
        frame_timestamp: str | None,
    ) -> list[DetectedObject]:
        if pose_runtime_enabled(self.settings.enable_pose, self.settings.pose_provider):
            return objects
        normalized: list[DetectedObject] = []
        for item in objects:
            if item.label != "person":
                normalized.append(item.model_copy(update={"pose": None}) if item.pose is not None else item)
                continue
            normalized.append(
                item.model_copy(
                    update={
                        "pose": build_pose_placeholder(
                            item,
                            frame_seq=frame_seq,
                            frame_timestamp=frame_timestamp,
                        )
                    }
                )
            )
        return normalized

    @staticmethod
    def _coerce_track_id(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_fresh(snapshot: ObjectSnapshot | None, ttl_ms: int) -> bool:
        if snapshot is None:
            return False
        if ttl_ms <= 0:
            return True
        return (time.monotonic() - snapshot.monotonic_at) * 1000 <= ttl_ms

    def _is_frame_aligned(
        self,
        base: ObjectSnapshot,
        patch: ObjectSnapshot | None,
        *,
        max_delta: int | None = None,
    ) -> bool:
        if patch is None:
            return False
        return abs(base.frame_seq - patch.frame_seq) <= (
            self.settings.pose_publish_max_frame_delta if max_delta is None else max_delta
        )

    def _current_fall_detection(self, base: ObjectSnapshot, fall_detection: ObjectSnapshot | None) -> ObjectSnapshot | None:
        if not self._is_fresh(fall_detection, self.settings.fall_hint_result_ttl_ms):
            return None
        if fall_detection is None:
            return None
        if abs(base.frame_seq - fall_detection.frame_seq) > self.settings.fusion_max_frame_delta_fall_hint:
            return None
        return fall_detection

    def _merge_fall_detection(
        self,
        camera_id: str,
        base_objects: list[DetectedObject],
        fall_objects: list[DetectedObject],
        person_objects: list[DetectedObject],
    ) -> list[DetectedObject]:
        if not base_objects or not fall_objects:
            if base_objects and not fall_objects:
                logger.info("fall_raw_hint_absent camera_id=%s reason=no_fall_objects", camera_id)
            return base_objects

        merged: list[DetectedObject] = []
        for item in base_objects:
            if item.label != "person":
                merged.append(item)
                continue
            match = ResultPublisherService._best_fall_match(item, fall_objects)
            if match is None:
                logger.info("fall_raw_hint_unmatched camera_id=%s track_id=%s reason=no_iou_match", camera_id, item.track_id)
                merged.append(item)
                continue
            if str(match.label).lower() not in STRONG_FALL_LABELS:
                logger.info(
                    "fall_weak_hint_dropped camera_id=%s track_id=%s label=%s reason=raw_only_weak_hint",
                    camera_id,
                    item.track_id,
                    match.label,
                )
                merged.append(item)
                continue
            probability = round(float(match.confidence), 4)
            has_person_evidence = self._has_person_evidence(item, person_objects)
            confirmed, confirm_debug = self._fall_detector_confirmed(
                camera_id,
                item,
                probability,
                has_person_evidence,
                str(match.label).lower(),
            )
            candidate_state = "fallen_confirmed" if confirmed else "fallen_candidate"
            candidate_risk = "critical" if confirmed else "medium"
            rejected_reason = str(confirm_debug.get("rejected_reason") or "") or None
            if not confirmed and self._has_existing_fall_evidence(item):
                logger.info(
                    "fall_candidate_preserved camera_id=%s track_id=%s label=%s reason=existing_evidence",
                    camera_id,
                    item.track_id,
                    match.label,
                )
                merged.append(item)
                continue
            logger.info(
                "fall_candidate_promoted camera_id=%s track_id=%s label=%s confirmed=%s probability=%.4f "
                "detector_only_guard_pass=%s upright_guard_pass=%s low_posture_evidence=%s rejected_reason=%s",
                camera_id,
                item.track_id,
                match.label,
                confirmed,
                probability,
                confirm_debug.get("detector_only_guard_pass"),
                confirm_debug.get("upright_guard_pass"),
                confirm_debug.get("low_posture_evidence"),
                rejected_reason,
            )
            merged.append(
                item.model_copy(
                    update={
                        "fall_decision": {
                            "fall_state": candidate_state,
                            "risk_level": candidate_risk,
                            "fall_probability": probability,
                            "source": "yolo_fall_detector",
                            "detector_label": match.label,
                            "person_evidence": has_person_evidence,
                            "detector_only_debug": confirm_debug,
                            "requires_temporal_confirmation": not confirmed,
                            "confirm_source": "fall_detector_continuous_candidate" if confirmed else None,
                            "suppressed_reason": None
                            if confirmed
                            else (rejected_reason or "awaiting_confirm_frames_or_duration"),
                            "rejected_reason": rejected_reason,
                        },
                        "alarm_preview": {
                            "confirmed": confirmed,
                            "risk_level": candidate_risk,
                            "fall_probability": probability,
                            "source": "yolo_fall_detector",
                            "person_evidence": has_person_evidence,
                            "detector_only_debug": confirm_debug,
                            "requires_temporal_confirmation": not confirmed,
                            "confirm_source": "fall_detector_continuous_candidate" if confirmed else None,
                            "suppressed_reason": None
                            if confirmed
                            else (rejected_reason or "awaiting_confirm_frames_or_duration"),
                            "rejected_reason": rejected_reason,
                        },
                    }
                )
            )
        return merged

    @staticmethod
    def _has_existing_fall_evidence(item: DetectedObject) -> bool:
        fall_decision = item.fall_decision or {}
        alarm_preview = item.alarm_preview or {}
        if alarm_preview.get("confirmed") is True:
            return True
        state = str(fall_decision.get("fall_state") or "")
        if state in {"falling", "fallen_candidate", "fallen_confirmed"}:
            return True
        return False

    @staticmethod
    def _has_confirmed_fall_evidence(item: DetectedObject) -> bool:
        fall_decision = item.fall_decision or {}
        alarm_preview = item.alarm_preview or {}
        if alarm_preview.get("confirmed") is True:
            return True
        state = str(fall_decision.get("fall_state") or "")
        return state == "fallen_confirmed"

    def _fall_detector_confirmed(
        self,
        camera_id: str,
        item: DetectedObject,
        probability: float,
        has_person_evidence: bool,
        detector_label: str,
    ) -> tuple[bool, dict[str, object]]:
        debug = self._detector_only_confirm_debug(
            item=item,
            probability=probability,
            has_person_evidence=has_person_evidence,
            detector_label=detector_label,
        )
        if not self.settings.fall_detector_confirm_enabled:
            debug["rejected_reason"] = "detector_confirm_disabled"
            return False, debug
        if not has_person_evidence:
            logger.info(
                "fall_candidate_dropped camera_id=%s track_id=%s reason=detector_only_no_person_evidence",
                camera_id,
                item.track_id,
            )
            self._decay_fall_candidate(camera_id, item)
            debug["rejected_reason"] = "detector_only_no_person_evidence"
            return False, debug
        if probability < self.settings.fall_detector_confirm_min_probability:
            logger.info(
                "fall_candidate_dropped camera_id=%s track_id=%s reason=low_fall_probability probability=%.4f threshold=%.4f",
                camera_id,
                item.track_id,
                probability,
                self.settings.fall_detector_confirm_min_probability,
            )
            self._decay_fall_candidate(camera_id, item)
            debug["rejected_reason"] = "low_fall_probability"
            return False, debug
        if float(item.confidence) < self.settings.fall_detector_confirm_min_person_confidence:
            logger.info(
                "fall_candidate_dropped camera_id=%s track_id=%s reason=low_person_confidence confidence=%.4f threshold=%.4f",
                camera_id,
                item.track_id,
                float(item.confidence),
                self.settings.fall_detector_confirm_min_person_confidence,
            )
            self._decay_fall_candidate(camera_id, item)
            debug["rejected_reason"] = "low_person_confidence"
            return False, debug
        if not bool(debug.get("upright_guard_pass")):
            logger.info(
                "fall_candidate_dropped camera_id=%s track_id=%s reason=detector_only_upright_guard "
                "label=%s bbox_aspect_ratio=%.4f low_posture_evidence=%s temporal_confirm_evidence=%s behavior=%s",
                camera_id,
                item.track_id,
                detector_label,
                float(debug.get("bbox_aspect_ratio") or 0.0),
                debug.get("low_posture_evidence"),
                debug.get("temporal_confirm_evidence"),
                debug.get("behavior_state"),
            )
            self._decay_fall_candidate(camera_id, item)
            debug["rejected_reason"] = "detector_only_upright_guard"
            return False, debug
        if bool(debug.get("adl_like_guard_active")):
            logger.info(
                "fall_candidate_dropped camera_id=%s track_id=%s reason=detector_only_adl_like_guard "
                "label=%s behavior=%s bbox_aspect_ratio=%.4f temporal_confirm_evidence=%s",
                camera_id,
                item.track_id,
                detector_label,
                debug.get("behavior_state"),
                float(debug.get("bbox_aspect_ratio") or 0.0),
                debug.get("temporal_confirm_evidence"),
            )
            self._decay_fall_candidate(camera_id, item)
            debug["rejected_reason"] = "detector_only_adl_like_guard"
            return False, debug

        key = self._fall_candidate_key(camera_id, item)
        now = time.monotonic()
        state = self._fall_candidate_states.get(key)
        if state is None or now - float(state.get("last_seen", 0.0)) > 2.0:
            state = {"frames": 0, "started_at": now, "last_seen": now}
        state["frames"] = int(state.get("frames", 0)) + 1
        state["last_seen"] = now
        self._fall_candidate_states[key] = state

        frames_ready = int(state["frames"]) >= self.settings.fall_detector_confirm_frames
        duration_ms = (now - float(state["started_at"])) * 1000
        debug["candidate_frames"] = int(state["frames"])
        debug["candidate_duration_ms"] = round(duration_ms, 1)
        if not (frames_ready and duration_ms >= self.settings.fall_detector_confirm_ms):
            logger.info(
                "fall_confirm_blocked camera_id=%s track_id=%s reason=awaiting_confirm_frames_or_duration frames=%s duration_ms=%.1f required_frames=%s required_ms=%s",
                camera_id,
                item.track_id,
                state["frames"],
                duration_ms,
                self.settings.fall_detector_confirm_frames,
                self.settings.fall_detector_confirm_ms,
            )
            debug["rejected_reason"] = "awaiting_confirm_frames_or_duration"
            return False, debug
        debug["rejected_reason"] = None
        debug["detector_only_guard_pass"] = True
        return True, debug

    def _detector_only_confirm_debug(
        self,
        *,
        item: DetectedObject,
        probability: float,
        has_person_evidence: bool,
        detector_label: str,
    ) -> dict[str, object]:
        x1, y1, x2, y2 = [float(value) for value in item.bbox]
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        bbox_aspect_ratio = width / height
        temporal = item.temporal or {}
        behavior = item.behavior or {}
        behavior_state = str(behavior.get("behavior_state") or "").lower()
        detector_label_normalized = str(detector_label or "").lower()
        temporal_low_posture = bool(temporal.get("low_posture"))
        temporal_fall_decision = item.fall_decision or {}
        temporal_source = str(temporal_fall_decision.get("source") or "")
        temporal_state = str(temporal_fall_decision.get("fall_state") or "")
        temporal_confirm_evidence = (
            temporal_source == "temporal_state_machine"
            and temporal_state in {"falling", "fallen_candidate", "fallen_confirmed"}
        )
        pose_payload = item.pose if isinstance(item.pose, dict) else None
        pose_available = pose_has_visible_keypoints(pose_payload)
        low_posture_evidence = (
            temporal_low_posture
            or bbox_aspect_ratio >= self.settings.field_fall_candidate_min_aspect
            or behavior_state in {"lying", "fallen"}
        )
        adl_like_guard_active = (
            behavior_state in {"sitting", "bending", "kneeling"}
            and detector_label_normalized in STRONG_FALL_LABELS
            and not temporal_confirm_evidence
        )
        upright_guard_required = detector_label in STRONG_FALL_LABELS
        upright_guard_pass = (not upright_guard_required) or low_posture_evidence or temporal_confirm_evidence
        return {
            "detector_label": detector_label,
            "detector_confidence": round(float(probability), 4),
            "person_evidence": has_person_evidence,
            "bbox_aspect_ratio": round(bbox_aspect_ratio, 4),
            "temporal_low_posture": temporal_low_posture,
            "temporal_confirm_evidence": temporal_confirm_evidence,
            "temporal_fall_state": temporal_state or None,
            "behavior_state": behavior_state,
            "adl_like_guard_active": adl_like_guard_active,
            "pose_available": pose_available,
            "low_posture_evidence": low_posture_evidence,
            "upright_guard_required": upright_guard_required,
            "upright_guard_pass": upright_guard_pass,
            "detector_only_guard_pass": False,
            "rejected_reason": None,
        }

    def _decay_fall_candidate(self, camera_id: str, item: DetectedObject) -> None:
        key = self._fall_candidate_key(camera_id, item)
        state = self._fall_candidate_states.get(key)
        if state is None:
            return
        frames = max(0, int(state.get("frames", 0)) - 1)
        if frames <= 0:
            self._fall_candidate_states.pop(key, None)
            return
        state["frames"] = frames
        state["last_seen"] = time.monotonic()

    @staticmethod
    def _fall_candidate_key(camera_id: str, item: DetectedObject) -> str:
        if item.track_id is not None:
            return f"{camera_id}:fall-detector:track:{int(item.track_id)}"
        x1, y1, x2, y2 = [float(value) for value in item.bbox]
        cx = int(((x1 + x2) / 2) // 160)
        cy = int(((y1 + y2) / 2) // 120)
        return f"{camera_id}:fall-detector:{cx}:{cy}"

    def _has_person_evidence(self, item: DetectedObject, person_objects: list[DetectedObject]) -> bool:
        for candidate in person_objects:
            if float(candidate.confidence) < self.settings.fall_detector_confirm_min_person_confidence:
                continue
            if self._iou(item.bbox, candidate.bbox) >= 0.1:
                return True
        return False

    @staticmethod
    def _best_fall_match(item: DetectedObject, fall_objects: list[DetectedObject]) -> DetectedObject | None:
        best: DetectedObject | None = None
        best_iou = 0.0
        for candidate in fall_objects:
            iou = ResultPublisherService._iou(item.bbox, candidate.bbox)
            if iou > best_iou:
                best_iou = iou
                best = candidate
        if best_iou < 0.1:
            return None
        return best

    def _remember_recent_fall_hint(self, camera_id: str, fall_detection: ObjectSnapshot) -> None:
        if any(str(item.label).lower() in STRONG_FALL_LABELS for item in fall_detection.objects):
            self._fall_hint_seen_at[camera_id] = time.monotonic()

    def _merge_weak_fall_hints(
        self,
        camera_id: str,
        base_objects: list[DetectedObject],
        fall_objects: list[DetectedObject],
    ) -> list[DetectedObject]:
        if not base_objects or not fall_objects:
            return base_objects

        merged: list[DetectedObject] = []
        for item in base_objects:
            if item.label != "person" or self._has_existing_fall_evidence(item):
                merged.append(item)
                continue

            match = self._best_weak_fall_match(item, fall_objects)
            if match is None:
                merged.append(item)
                continue

            behavior = item.behavior or {}
            behavior_state = str(behavior.get("behavior_state") or "").lower()
            temporal = item.temporal or {}
            features = temporal.get("features") if isinstance(temporal.get("features"), dict) else {}
            aspect_ratio = float(features.get("aspect_ratio") or 0.0)
            speed = float(features.get("speed") or 0.0)
            has_lying_behavior = behavior_state == "lying"
            has_low_posture = aspect_ratio >= self.settings.field_fall_candidate_min_aspect
            has_low_speed = speed <= self.settings.field_fall_candidate_max_speed

            if not ((has_lying_behavior or has_low_posture) and has_low_speed):
                logger.info(
                    "fall_weak_hint_dropped camera_id=%s track_id=%s label=%s reason=weak_hint_guard_not_met behavior=%s aspect=%.4f speed=%.4f",
                    camera_id,
                    item.track_id,
                    match.label,
                    behavior_state,
                    aspect_ratio,
                    speed,
                )
                merged.append(item)
                continue

            probability = round(max(float(match.confidence), 0.18), 4)
            logger.info(
                "fall_weak_hint_promoted camera_id=%s track_id=%s label=%s probability=%.4f behavior=%s aspect=%.4f speed=%.4f",
                camera_id,
                item.track_id,
                match.label,
                probability,
                behavior_state,
                aspect_ratio,
                speed,
            )
            merged.append(
                item.model_copy(
                    update={
                        "fall_decision": {
                            "fall_state": "fallen_candidate",
                            "risk_level": "high",
                            "fall_probability": probability,
                            "source": "yolo_fall_detector_weak_lying",
                            "detector_label": match.label,
                            "requires_temporal_confirmation": True,
                            "suppressed_reason": "awaiting_confirm_frames_or_duration",
                            "debug_reason": "weak_hint_guard_passed",
                        },
                        "alarm_preview": {
                            "confirmed": False,
                            "risk_level": "high",
                            "fall_probability": probability,
                            "source": "yolo_fall_detector_weak_lying",
                            "requires_temporal_confirmation": True,
                            "suppressed_reason": "awaiting_confirm_frames_or_duration",
                            "debug_reason": "weak_hint_guard_passed",
                        },
                    }
                )
            )
        return merged

    @staticmethod
    def _best_weak_fall_match(item: DetectedObject, fall_objects: list[DetectedObject]) -> DetectedObject | None:
        weak_objects = [candidate for candidate in fall_objects if str(candidate.label).lower() in WEAK_FALL_LABELS]
        if not weak_objects:
            return None
        return ResultPublisherService._best_fall_match(item, weak_objects)

    def _merge_field_fall_candidates(
        self,
        camera_id: str,
        objects: list[DetectedObject],
        frame_width: int,
        frame_height: int,
        fall_objects: list[DetectedObject],
        person_objects: list[DetectedObject],
    ) -> list[DetectedObject]:
        if not self.settings.field_fall_candidate_enabled:
            return objects

        merged: list[DetectedObject] = []
        for item in objects:
            if item.label != "person" or self._has_confirmed_fall_evidence(item):
                merged.append(item)
                continue
            field_debug = self._field_rule_debug(
                camera_id=camera_id,
                item=item,
                frame_width=frame_width,
                frame_height=frame_height,
                fall_objects=fall_objects,
                person_objects=person_objects,
            )
            if not field_debug["field_candidate_pass"]:
                logger.info(
                    "field_fall_candidate_dropped camera_id=%s track_id=%s reason=%s missing_conditions=%s "
                    "has_recent_strong_hint=%s has_current_fall_object=%s aspect=%.4f aspect_pass=%s "
                    "center_y_norm=%.4f center_y_pass=%s height_norm=%.4f height_pass=%s "
                    "window_size=%s window_size_pass=%s speed=%.4f speed_pass=%s "
                    "stable_track=%s stable_track_pass=%s person_evidence=%s person_evidence_pass=%s "
                    "pose_available=%s body_angle=%s low_posture=%s stillness=%s velocity_y=%s "
                    "bbox_aspect_ratio=%s candidate_duration_ms=%s confirm_duration_ms=%s",
                    camera_id,
                    item.track_id,
                    field_debug["drop_reason"],
                    ",".join(field_debug["missing_conditions"]),
                    field_debug["has_recent_strong_hint"],
                    field_debug["has_current_fall_object"],
                    field_debug["aspect"],
                    field_debug["aspect_pass"],
                    field_debug["center_y_norm"],
                    field_debug["center_y_pass"],
                    field_debug["height_norm"],
                    field_debug["height_pass"],
                    field_debug["window_size"],
                    field_debug["window_size_pass"],
                    field_debug["speed"],
                    field_debug["speed_pass"],
                    field_debug["stable_track"],
                    field_debug["stable_track_pass"],
                    field_debug["person_evidence"],
                    field_debug["person_evidence_pass"],
                    field_debug["pose_available"],
                    field_debug["body_angle"],
                    field_debug["low_posture"],
                    field_debug["stillness"],
                    field_debug["velocity_y"],
                    field_debug["bbox_aspect_ratio"],
                    field_debug["candidate_duration_ms"],
                    field_debug["confirm_duration_ms"],
                )
                self._decay_field_candidate(camera_id, item)
                merged.append(self._with_field_rule_debug(item, field_debug))
                continue

            confirmed, promotion_reason, rejected_reason, field_debug = self._field_fall_candidate_confirmed(
                camera_id,
                item,
                field_debug,
            )
            probability = self._field_candidate_probability(item, confirmed)
            risk = "critical" if confirmed else "medium"
            logger.info(
                "field_fall_candidate_promoted camera_id=%s track_id=%s confirmed=%s probability=%.4f "
                "promotion_reason=%s drop_reason=%s missing_conditions=%s has_current_fall_object=%s "
                "stable_track=%s person_evidence=%s pose_available=%s body_angle=%s low_posture=%s "
                "stillness=%s velocity_y=%s bbox_aspect_ratio=%s candidate_duration_ms=%s confirm_duration_ms=%s",
                camera_id,
                item.track_id,
                confirmed,
                probability,
                promotion_reason,
                rejected_reason,
                ",".join(field_debug["missing_conditions"]),
                field_debug["has_current_fall_object"],
                field_debug["stable_track"],
                field_debug["person_evidence"],
                field_debug["pose_available"],
                field_debug["body_angle"],
                field_debug["low_posture"],
                field_debug["stillness"],
                field_debug["velocity_y"],
                field_debug["bbox_aspect_ratio"],
                field_debug["candidate_duration_ms"],
                field_debug["confirm_duration_ms"],
            )
            merged.append(
                self._with_field_rule_debug(
                    item,
                    field_debug,
                    extra_updates={
                        "fall_decision": {
                            "fall_state": "fallen_confirmed" if confirmed else "fallen_candidate",
                            "risk_level": risk,
                            "fall_probability": probability,
                            "source": "field_fall_candidate_fusion",
                            "requires_temporal_confirmation": not confirmed,
                            "confirm_source": "field_low_posture_recent_fall_hint" if confirmed else None,
                            "suppressed_reason": None
                            if confirmed
                            else (rejected_reason or "awaiting_field_confirm_frames_or_duration"),
                            "rejected_reason": rejected_reason,
                            "promotion_reason": promotion_reason,
                            "field_rule_debug": field_debug,
                        },
                        "alarm_preview": {
                            "confirmed": confirmed,
                            "risk_level": risk,
                            "fall_probability": probability,
                            "source": "field_fall_candidate_fusion",
                            "requires_temporal_confirmation": not confirmed,
                            "confirm_source": "field_low_posture_recent_fall_hint" if confirmed else None,
                            "suppressed_reason": None
                            if confirmed
                            else (rejected_reason or "awaiting_field_confirm_frames_or_duration"),
                            "rejected_reason": rejected_reason,
                            "promotion_reason": promotion_reason,
                            "field_rule_debug": field_debug,
                        },
                    },
                )
            )
        return merged

    def _field_rule_debug(
        self,
        camera_id: str,
        item: DetectedObject,
        frame_width: int,
        frame_height: int,
        fall_objects: list[DetectedObject],
        person_objects: list[DetectedObject],
    ) -> dict[str, object]:
        x1, y1, x2, y2 = [float(value) for value in item.bbox]
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        aspect = width / height
        center_y_norm = ((y1 + y2) / 2) / frame_height if frame_height > 0 else 0.0
        height_norm = height / frame_height if frame_height > 0 else 1.0
        temporal = item.temporal or {}
        features = temporal.get("features") if isinstance(temporal.get("features"), dict) else {}
        window_size = int(temporal.get("window_size") or 0)
        speed = float(features.get("speed") or 0.0)
        behavior = item.behavior or {}
        behavior_state = str(behavior.get("behavior_state") or "").lower()
        pose_available = bool(features.get("pose_available") is True) or pose_has_visible_keypoints(
            item.pose if isinstance(item.pose, dict) else None
        )
        last_hint = self._fall_hint_seen_at.get(camera_id)
        hint_age_ms = (time.monotonic() - last_hint) * 1000 if last_hint is not None else None
        has_recent_strong_hint = (
            not self.settings.field_fall_candidate_requires_recent_fall_hint
            or (hint_age_ms is not None and hint_age_ms <= self.settings.field_fall_candidate_recent_hint_ms)
        )
        current_fall_match = self._best_fall_match(item, fall_objects) if fall_objects else None
        strong_fall_match = self._best_strong_fall_match(item, fall_objects)
        has_current_fall_object = current_fall_match is not None
        has_current_strong_fall_object = strong_fall_match is not None
        stable_track = item.track_id is not None
        person_evidence = self._has_field_person_evidence(item, person_objects)
        aspect_pass = aspect >= self.settings.field_fall_candidate_min_aspect
        center_y_pass = center_y_norm >= self.settings.field_fall_candidate_min_center_y_norm
        height_pass = height_norm <= self.settings.field_fall_candidate_max_height_norm
        window_size_pass = window_size >= self.settings.field_fall_candidate_min_window
        speed_pass = speed <= self.settings.field_fall_candidate_max_speed
        low_posture = bool(temporal.get("low_posture")) or aspect_pass
        temporal_fall_decision = item.fall_decision or {}
        has_temporal_confirm_evidence = (
            str(temporal_fall_decision.get("source") or "") == "temporal_state_machine"
            and str(temporal_fall_decision.get("fall_state") or "") in {"falling", "fallen_candidate", "fallen_confirmed"}
        )
        missing_conditions: list[str] = []
        if frame_width <= 0 or frame_height <= 0:
            missing_conditions.extend(["frame_width", "frame_height"])
        if not has_recent_strong_hint:
            missing_conditions.append("has_recent_strong_hint")
        if not aspect_pass:
            missing_conditions.append("aspect_pass")
        if not center_y_pass:
            missing_conditions.append("center_y_pass")
        if not height_pass:
            missing_conditions.append("height_pass")
        if not window_size_pass:
            missing_conditions.append("window_size_pass")
        if not speed_pass:
            missing_conditions.append("speed_pass")
        field_candidate_pass = frame_width > 0 and frame_height > 0 and not missing_conditions
        return {
            "track_id": item.track_id,
            "has_recent_strong_hint": has_recent_strong_hint,
            "has_current_fall_object": has_current_fall_object,
            "has_current_strong_fall_object": has_current_strong_fall_object,
            "has_temporal_confirm_evidence": has_temporal_confirm_evidence,
            "aspect": round(aspect, 4),
            "aspect_pass": aspect_pass,
            "center_y_norm": round(center_y_norm, 4),
            "center_y_pass": center_y_pass,
            "height_norm": round(height_norm, 4),
            "height_pass": height_pass,
            "window_size": window_size,
            "window_size_pass": window_size_pass,
            "speed": round(speed, 4),
            "speed_pass": speed_pass,
            "stable_track": stable_track,
            "stable_track_pass": stable_track,
            "person_evidence": person_evidence,
            "person_evidence_pass": person_evidence,
            "pose_available": pose_available,
            "body_angle": temporal.get("body_angle"),
            "low_posture": low_posture,
            "stillness": temporal.get("stillness"),
            "velocity_y": temporal.get("velocity_y"),
            "bbox_aspect_ratio": temporal.get("bbox_aspect_ratio", round(aspect, 4)),
            "fall_probability": self._field_candidate_probability(item, confirmed=False),
            "candidate_duration_ms": temporal.get("candidate_duration_ms"),
            "confirm_duration_ms": temporal.get("confirm_duration_ms"),
            "behavior_state": behavior_state,
            "field_candidate_pass": field_candidate_pass,
            "promotion_reason": "field_candidate_base_rules_met" if field_candidate_pass else None,
            "drop_reason": "field_rules_not_met" if not field_candidate_pass else None,
            "missing_conditions": missing_conditions,
        }

    def _field_fall_candidate_confirmed(
        self,
        camera_id: str,
        item: DetectedObject,
        field_debug: dict[str, object],
    ) -> tuple[bool, str | None, str | None, dict[str, object]]:
        rejected_reason: str | None = None
        promotion_reason: str | None = "field_candidate_base_rules_met"
        if not bool(field_debug.get("stable_track_pass")) or not bool(field_debug.get("person_evidence_pass")):
            rejected_reason = "field_confirm_requires_stable_person_evidence"
        elif str(field_debug.get("behavior_state") or "").lower() in {"sitting", "bending", "kneeling"} and not bool(
            field_debug.get("has_temporal_confirm_evidence")
        ):
            rejected_reason = "field_confirm_blocked_adl_like_posture"
        elif not bool(field_debug.get("has_current_fall_object")) and not bool(field_debug.get("has_temporal_confirm_evidence")):
            rejected_reason = "field_recent_hint_blocked_no_current_fall_object"
        elif not bool(field_debug.get("has_current_strong_fall_object")) and not bool(
            field_debug.get("has_temporal_confirm_evidence")
        ):
            rejected_reason = "field_confirm_blocked_possible_sitting"

        if rejected_reason is not None:
            field_debug = dict(field_debug)
            missing_conditions = list(field_debug.get("missing_conditions") or [])
            if rejected_reason == "field_confirm_requires_stable_person_evidence":
                if not bool(field_debug.get("stable_track_pass")) and "stable_track_pass" not in missing_conditions:
                    missing_conditions.append("stable_track_pass")
                if not bool(field_debug.get("person_evidence_pass")) and "person_evidence_pass" not in missing_conditions:
                    missing_conditions.append("person_evidence_pass")
            elif rejected_reason == "field_recent_hint_blocked_no_current_fall_object":
                if "has_current_fall_object" not in missing_conditions:
                    missing_conditions.append("has_current_fall_object")
            elif rejected_reason == "field_confirm_blocked_adl_like_posture":
                if "adl_like_posture" not in missing_conditions:
                    missing_conditions.append("adl_like_posture")
            elif rejected_reason == "field_confirm_blocked_possible_sitting":
                if "has_current_strong_fall_object" not in missing_conditions:
                    missing_conditions.append("has_current_strong_fall_object")
            field_debug["drop_reason"] = rejected_reason
            field_debug["promotion_reason"] = promotion_reason
            field_debug["missing_conditions"] = missing_conditions
            return False, promotion_reason, rejected_reason, field_debug

        key = self._field_candidate_key(camera_id, item)
        now = time.monotonic()
        state = self._field_candidate_states.get(key)
        if state is None or now - float(state.get("last_seen", 0.0)) > 2.5:
            state = {"frames": 0, "started_at": now, "last_seen": now}
        state["frames"] = int(state.get("frames", 0)) + 1
        state["last_seen"] = now
        self._field_candidate_states[key] = state

        frames_ready = int(state["frames"]) >= self.settings.field_fall_candidate_confirm_frames
        duration_ms = (now - float(state["started_at"])) * 1000
        field_debug = dict(field_debug)
        field_debug["field_confirm_frames"] = int(state["frames"])
        field_debug["field_confirm_duration_ms"] = round(duration_ms, 1)
        if not (frames_ready and duration_ms >= self.settings.field_fall_candidate_confirm_ms):
            rejected_reason = "awaiting_field_confirm_frames_or_duration"
            missing_conditions = list(field_debug.get("missing_conditions") or [])
            if not frames_ready and "field_confirm_frames" not in missing_conditions:
                missing_conditions.append("field_confirm_frames")
            if duration_ms < self.settings.field_fall_candidate_confirm_ms and "field_confirm_duration_ms" not in missing_conditions:
                missing_conditions.append("field_confirm_duration_ms")
            field_debug["drop_reason"] = rejected_reason
            field_debug["promotion_reason"] = promotion_reason
            field_debug["missing_conditions"] = missing_conditions
            return False, promotion_reason, rejected_reason, field_debug
        field_debug["drop_reason"] = None
        field_debug["promotion_reason"] = "field_low_posture_recent_fall_hint"
        field_debug["missing_conditions"] = []
        return True, "field_low_posture_recent_fall_hint", None, field_debug

    def _decay_field_candidate(self, camera_id: str, item: DetectedObject) -> None:
        key = self._field_candidate_key(camera_id, item)
        state = self._field_candidate_states.get(key)
        if state is None:
            return
        frames = max(0, int(state.get("frames", 0)) - 1)
        if frames <= 0:
            self._field_candidate_states.pop(key, None)
            return
        state["frames"] = frames
        state["last_seen"] = time.monotonic()

    @staticmethod
    def _field_candidate_probability(item: DetectedObject, confirmed: bool) -> float:
        temporal = item.temporal or {}
        shadow = temporal.get("shadow") if isinstance(temporal.get("shadow"), dict) else {}
        values = [
            temporal.get("fall_probability"),
            shadow.get("fall_probability") if isinstance(shadow, dict) else None,
            item.confidence,
        ]
        best = max(float(value) for value in values if value is not None)
        floor = 0.72 if confirmed else 0.52
        return round(max(floor, min(0.95, best)), 4)

    @staticmethod
    def _best_strong_fall_match(item: DetectedObject, fall_objects: list[DetectedObject]) -> DetectedObject | None:
        strong_objects = [candidate for candidate in fall_objects if str(candidate.label).lower() in STRONG_FALL_LABELS]
        if not strong_objects:
            return None
        return ResultPublisherService._best_fall_match(item, strong_objects)

    def _has_field_person_evidence(self, item: DetectedObject, person_objects: list[DetectedObject]) -> bool:
        if self._has_person_evidence(item, person_objects):
            return True
        if item.is_target:
            return True
        return item.track_id is not None and float(item.confidence) >= self.settings.fall_detector_confirm_min_person_confidence

    @staticmethod
    def _with_field_rule_debug(
        item: DetectedObject,
        field_debug: dict[str, object],
        extra_updates: dict[str, object] | None = None,
    ) -> DetectedObject:
        temporal = dict(item.temporal or {})
        temporal["field_rule_debug"] = field_debug
        updates: dict[str, object] = {"temporal": temporal}
        if extra_updates:
            updates.update(extra_updates)
        return item.model_copy(update=updates)

    @staticmethod
    def _field_candidate_key(camera_id: str, item: DetectedObject) -> str:
        x1, y1, x2, y2 = [float(value) for value in item.bbox]
        cx = int(((x1 + x2) / 2) // 160)
        cy = int(((y1 + y2) / 2) // 120)
        track_component = str(int(item.track_id)) if item.track_id is not None else "no-track"
        return f"{camera_id}:field-fall:{track_component}:{cx}:{cy}"

    @staticmethod
    def _iou(a: list[float], b: list[float]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0.0, inter_x2 - inter_x1)
        inter_h = max(0.0, inter_y2 - inter_y1)
        inter = inter_w * inter_h
        if inter <= 0:
            return 0.0
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        union = area_a + area_b - inter
        if union <= 0:
            return 0.0
        return inter / union
