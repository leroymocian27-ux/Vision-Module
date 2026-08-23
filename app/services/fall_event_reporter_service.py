from __future__ import annotations

import copy
import queue
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import requests

from app.camera.source_manager import CameraSourceManager
from app.core.config import Settings
from app.core.logger import get_logger
from app.schemas.vision_result import DetectedObject, VisionResult
from app.services.alert_outbox_service import AlertOutboxService

logger = get_logger(__name__)
INCIDENT_REUSE_WINDOW_MS = 15_000.0
INCIDENT_REUSE_MIN_IOU = 0.2
INCIDENT_REUSE_MAX_CENTER_DISTANCE_RATIO = 0.6


class FallEventReporterService:
    """Push confirmed fall events to the health-main backend without blocking inference."""

    def __init__(
        self,
        settings: Settings,
        source_manager: CameraSourceManager,
        alert_outbox: AlertOutboxService | None = None,
    ) -> None:
        self.settings = settings
        self.source_manager = source_manager
        self.alert_outbox = alert_outbox
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=32)
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_sent_at: dict[str, float] = {}
        self._last_post_status: str | None = None
        self._last_incident_id: str | None = None
        self._last_snapshot_url: str | None = None
        self._last_error: str | None = None
        self._last_payload: dict[str, Any] | None = None
        self._latest_alert_by_camera: dict[str, dict[str, Any]] = {}
        self._active_alerts_by_key: dict[str, dict[str, Any]] = {}
        self._recent_alerts_by_key: dict[str, dict[str, Any]] = {}
        self._active_alert_keys_by_camera: dict[str, set[str]] = {}
        self._incident_cache_by_id: dict[str, dict[str, Any]] = {}
        self._incident_ids_by_camera: dict[str, set[str]] = {}
        self._active_keys_by_incident_id: dict[str, set[str]] = {}
        self._enabled = settings.main_system_alert_enabled
        self._dry_run = settings.main_system_report_dry_run
        self._endpoint_base_url = settings.main_system_base_url.rstrip("/")
        path = settings.main_system_fall_event_path.strip() or "/video-bridge/fall-events"
        self._endpoint_path = path if path.startswith("/") else f"/{path}"
        self._lock = threading.Lock()
        self._last_outbox_retry_at = 0.0
        self._outbox_retry_interval_sec = 5.0

    def start(self) -> None:
        if not self.enabled:
            logger.info("fall_event_reporter_disabled")
            return
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="fall-event-reporter", daemon=True)
        self._worker.start()
        logger.info("fall_event_reporter_started endpoint=%s", self._endpoint_url())

    def stop(self) -> None:
        self._stop.set()
        if self._worker and self._worker.is_alive():
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
            self._worker.join(timeout=3)

    def inspect_result(self, result: VisionResult) -> None:
        active_keys_for_camera: set[str] = set()
        has_confirmed_fall = False
        updated_objects: list[DetectedObject] = []
        for obj in result.objects:
            if not self._is_confirmed_fall(obj) or not self._has_person_evidence(obj):
                updated_objects.append(obj)
                continue
            reporter_guard_reason = self._reporter_confirm_guard_reason(obj)
            if reporter_guard_reason is not None:
                updated_objects.append(self._attach_reporter_guard_debug(obj, reporter_guard_reason))
                continue
            has_confirmed_fall = True
            key = self._cooldown_key(result, obj)
            track_id = self._object_track_id(obj)
            active_keys_for_camera.add(key)
            active_payload = self._active_alert_payload(key)
            if active_payload is not None:
                reuse_debug = self._reuse_debug_for_payload(
                    result=result,
                    obj=obj,
                    payload=active_payload,
                    reason="same_track_active_incident",
                    incident_reused=True,
                    duplicate_incident_suppressed=False,
                )
                active_payload = self._ensure_snapshot_fields(result.camera_id, track_id, active_payload)
                active_payload = self._refresh_payload_for_result(result, obj, active_payload, reuse_debug)
                self._record_active_alert(result.camera_id, key, active_payload)
                self._record_latest_alert(result.camera_id, active_payload)
                updated_objects.append(self._attach_event_metadata(obj, active_payload))
                continue
            reusable_payload, reuse_debug = self._resolve_reusable_payload(result, obj, key)
            if reusable_payload is not None:
                reusable_payload = self._ensure_snapshot_fields(result.camera_id, track_id, reusable_payload)
                reusable_payload = self._refresh_payload_for_result(result, obj, reusable_payload, reuse_debug)
                self._record_active_alert(result.camera_id, key, reusable_payload)
                self._record_latest_alert(result.camera_id, reusable_payload)
                updated_objects.append(self._attach_event_metadata(obj, reusable_payload))
                continue
            if not self._can_send(key):
                recent_payload = self._recent_alert_payload(key)
                if recent_payload is not None:
                    reuse_debug = self._reuse_debug_for_payload(
                        result=result,
                        obj=obj,
                        payload=recent_payload,
                        reason="same_track_recent_cooldown_reuse",
                        incident_reused=True,
                        duplicate_incident_suppressed=False,
                    )
                    recent_payload = self._ensure_snapshot_fields(result.camera_id, track_id, recent_payload)
                    recent_payload = self._refresh_payload_for_result(result, obj, recent_payload, reuse_debug)
                    self._record_active_alert(result.camera_id, key, recent_payload)
                    self._record_latest_alert(result.camera_id, recent_payload)
                    updated_objects.append(self._attach_event_metadata(obj, recent_payload))
                    continue
                updated_objects.append(obj)
                continue
            payload = self._build_payload(
                result,
                obj,
                incident_reuse_debug=self._default_incident_reuse_debug(result, obj),
            )
            self._record_active_alert(result.camera_id, key, payload)
            self._record_latest_alert(result.camera_id, payload)
            updated_objects.append(self._attach_event_metadata(obj, payload))
            if not self.enabled:
                self._record_poll_only(payload)
                continue
            self._record_pending(payload)
            try:
                self._queue.put_nowait(payload)
            except queue.Full:
                logger.warning("fall_event_report_queue_full camera_id=%s key=%s", result.camera_id, key)
                with self._lock:
                    self._last_sent_at.pop(key, None)
                    self._last_post_status = "queue_full"
                    self._last_error = "queue_full"
        if updated_objects and updated_objects != result.objects:
            result.objects = updated_objects
        self._clear_inactive_alerts(result.camera_id, active_keys_for_camera)
        if not has_confirmed_fall:
            self._clear_latest_alert(result.camera_id)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.2)
            except queue.Empty:
                self._retry_outbox_once()
                continue
            if payload is None:
                break
            self._post_payload(payload)

    def _retry_outbox_once(self) -> None:
        if self.alert_outbox is None or not self.alert_outbox.enabled or self.dry_run:
            return
        now = time.monotonic()
        if now - self._last_outbox_retry_at < self._outbox_retry_interval_sec:
            return
        self._last_outbox_retry_at = now
        if self._queue.qsize() >= max(1, self._queue.maxsize // 2):
            return
        for payload in self.alert_outbox.pending_payloads(limit=3):
            try:
                self._queue.put_nowait(payload)
            except queue.Full:
                return

    def _post_payload(self, payload: dict[str, Any]) -> None:
        if self.dry_run:
            self._record_dry_run(payload)
            logger.info(
                "fall_event_report_dry_run skipped_real_post target=%s event_type=%s track_id=%s incident_id=%s",
                self._endpoint_url(),
                payload.get("event_type"),
                payload.get("track_id"),
                payload.get("incident_id"),
            )
            return
        timeout = self.request_timeout_seconds()
        try:
            response = requests.post(
                self._endpoint_url(),
                json=payload,
                headers=self._alert_headers(),
                timeout=timeout,
            )
            if response.status_code >= 400:
                logger.warning(
                    "fall_event_report_failed status=%s body=%s incident_id=%s",
                    response.status_code,
                    response.text[:500],
                    payload.get("incident_id"),
                )
                self._record_post_result(payload, f"http_{response.status_code}", response.text[:500])
                return
            self._record_post_result(payload, f"http_{response.status_code}", None)
            logger.info(
                "fall_event_reported status=%s incident_id=%s alarm_response=%s",
                response.status_code,
                payload.get("incident_id"),
                response.text[:500],
            )
        except requests.RequestException as exc:
            logger.warning("fall_event_report_request_error incident_id=%s error=%s", payload.get("incident_id"), exc)
            self._record_post_result(payload, "request_error", str(exc))

    def status(self) -> dict[str, Any]:
        with self._lock:
            endpoint = f"{self._endpoint_base_url}{self._endpoint_path}"
            return {
                "enabled": self._enabled,
                "dry_run": self._dry_run,
                "running": bool(self._worker and self._worker.is_alive()),
                "endpoint": endpoint,
                "endpoint_base_url": self._endpoint_base_url,
                "endpoint_path": self._endpoint_path,
                "token_header": self.settings.main_system_alert_token_header,
                "queue_size": self._queue.qsize(),
                "cooldown_seconds": self.settings.main_system_alert_cooldown_seconds,
                "last_post_status": self._last_post_status,
                "last_incident_id": self._last_incident_id,
                "last_snapshot_url": self._last_snapshot_url,
                "last_error": self._last_error,
                "last_post_body": self._last_error,
                "last_payload": self._last_payload,
                "outbox": self.alert_outbox.status().__dict__ if self.alert_outbox is not None else None,
            }

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def dry_run(self) -> bool:
        with self._lock:
            return self._dry_run

    def update_endpoint(self, *, base_url: str, path: str, enabled: bool = True) -> dict[str, Any]:
        normalized_base = base_url.rstrip("/")
        normalized_path = path.strip() or "/video-bridge/fall-events"
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"
        with self._lock:
            self._enabled = enabled
            self._endpoint_base_url = normalized_base
            self._endpoint_path = normalized_path
            endpoint = f"{self._endpoint_base_url}{self._endpoint_path}"
        logger.info("fall_event_reporter_endpoint_updated enabled=%s endpoint=%s", enabled, endpoint)
        return self.status()

    def endpoint_url(self) -> str:
        return self._endpoint_url()

    def update_main_system_base_url(self, base_url: str) -> None:
        normalized = str(base_url or "").rstrip("/")
        if not normalized:
            return
        with self._lock:
            if normalized == self._endpoint_base_url:
                return
            self._endpoint_base_url = normalized
            self._last_error = None
        logger.info("fall_event_reporter_endpoint_updated endpoint=%s", self._endpoint_url())

    def request_timeout_seconds(self) -> float:
        return max(0.2, self.settings.main_system_alert_timeout_ms / 1000)

    def latest_alert(self, camera_id: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._latest_alert_by_camera.get(camera_id)
            return copy.deepcopy(payload) if payload is not None else None

    def polling_alert(self, camera_id: str, last_incident_id: str | None = None) -> dict[str, Any]:
        latest = self.latest_alert(camera_id)
        normalized_last_incident_id = str(last_incident_id or "").strip() or None
        if latest is None:
            return {
                "camera_id": camera_id,
                "status": "no_alert",
                "should_popup": False,
                "last_incident_id": normalized_last_incident_id,
                "incident_id": None,
                "event_timestamp": None,
                "fall_state": None,
                "risk_level": None,
                "snapshot_url": None,
                "alert": None,
            }

        incident_id = str(latest.get("incident_id") or "").strip() or None
        fall_state = str(latest.get("status") or latest.get("state") or "").strip() or None
        should_popup = bool(incident_id) and incident_id != normalized_last_incident_id
        return {
            "camera_id": camera_id,
            "status": "new_alert" if should_popup else "seen_alert",
            "should_popup": should_popup,
            "last_incident_id": normalized_last_incident_id,
            "incident_id": incident_id,
            "event_timestamp": latest.get("timestamp"),
            "fall_state": fall_state,
            "risk_level": latest.get("risk_level") or latest.get("risk"),
            "snapshot_url": latest.get("snapshot_url"),
            "alert": latest,
        }

    def _record_pending(self, payload: dict[str, Any]) -> None:
        self._update_incident_delivery_state(payload, sent_to_main=False)
        if self.alert_outbox is not None:
            self.alert_outbox.record_pending(payload)
        with self._lock:
            self._last_post_status = "queued"
            self._last_incident_id = str(payload.get("incident_id") or "")
            snapshot_url = payload.get("snapshot_url")
            self._last_snapshot_url = str(snapshot_url) if snapshot_url else None
            self._last_error = None
            self._last_payload = dict(payload)

    def _record_poll_only(self, payload: dict[str, Any]) -> None:
        self._update_incident_delivery_state(payload, sent_to_main=False)
        with self._lock:
            self._last_post_status = "poll_only"
            self._last_incident_id = str(payload.get("incident_id") or "")
            snapshot_url = payload.get("snapshot_url")
            self._last_snapshot_url = str(snapshot_url) if snapshot_url else None
            self._last_error = None
            self._last_payload = dict(payload)

    def _record_dry_run(self, payload: dict[str, Any]) -> None:
        self._update_incident_delivery_state(payload, sent_to_main=False)
        if self.alert_outbox is not None:
            self.alert_outbox.record_result(payload, "dry_run_skipped", None)
        with self._lock:
            self._last_post_status = "dry_run_skipped"
            self._last_incident_id = str(payload.get("incident_id") or "")
            snapshot_url = payload.get("snapshot_url")
            self._last_snapshot_url = str(snapshot_url) if snapshot_url else None
            self._last_error = None
            self._last_payload = dict(payload)

    def _record_post_result(self, payload: dict[str, Any], status: str, error: str | None) -> None:
        self._update_incident_delivery_state(payload, sent_to_main=status.startswith("http_2"))
        if self.alert_outbox is not None:
            self.alert_outbox.record_result(payload, status, error)
        with self._lock:
            self._last_post_status = status
            self._last_incident_id = str(payload.get("incident_id") or "")
            snapshot_url = payload.get("snapshot_url")
            self._last_snapshot_url = str(snapshot_url) if snapshot_url else None
            self._last_error = error
            self._last_payload = dict(payload)

    def _record_latest_alert(self, camera_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._latest_alert_by_camera[camera_id] = copy.deepcopy(payload)

    def _clear_latest_alert(self, camera_id: str) -> None:
        with self._lock:
            self._latest_alert_by_camera.pop(camera_id, None)

    def _has_active_alert(self, key: str) -> bool:
        with self._lock:
            return key in self._active_alerts_by_key

    def _record_active_alert(self, camera_id: str, key: str, payload: dict[str, Any]) -> None:
        with self._lock:
            stored_payload = copy.deepcopy(payload)
            self._active_alerts_by_key[key] = stored_payload
            self._recent_alerts_by_key[key] = copy.deepcopy(stored_payload)
            keys = self._active_alert_keys_by_camera.setdefault(camera_id, set())
            keys.add(key)
            self._upsert_incident_cache_locked(camera_id, key, stored_payload)

    def _active_alert_payload(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._active_alerts_by_key.get(key)
            return copy.deepcopy(payload) if payload is not None else None

    def _recent_alert_payload(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._recent_alerts_by_key.get(key)
            return copy.deepcopy(payload) if payload is not None else None

    def _clear_inactive_alerts(self, camera_id: str, active_keys_for_camera: set[str]) -> None:
        with self._lock:
            known_keys = set(self._active_alert_keys_by_camera.get(camera_id, set()))
            stale_keys = known_keys - active_keys_for_camera
            if not stale_keys:
                return
            for key in stale_keys:
                payload = self._active_alerts_by_key.pop(key, None)
                self._mark_incident_inactive_for_key_locked(key, payload)
            remaining = known_keys & active_keys_for_camera
            if remaining:
                self._active_alert_keys_by_camera[camera_id] = remaining
            else:
                self._active_alert_keys_by_camera.pop(camera_id, None)

    def _resolve_reusable_payload(
        self,
        result: VisionResult,
        obj: DetectedObject,
        key: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        current_track_id = self._object_track_id(obj)
        single_person_scene = self._single_person_scene(result)
        current_bbox = [float(value) for value in obj.bbox]
        current_spatial_key = self._incident_spatial_key(result.camera_id, obj, result.frame_width, result.frame_height)
        now = time.monotonic()
        fallback_debug = self._default_incident_reuse_debug(result, obj)
        best_payload: dict[str, Any] | None = None
        best_debug = fallback_debug
        best_score = float("-inf")

        with self._lock:
            candidate_ids = list(self._incident_ids_by_camera.get(result.camera_id, set()))
            candidates = [copy.deepcopy(self._incident_cache_by_id[incident_id]) for incident_id in candidate_ids if incident_id in self._incident_cache_by_id]

        for incident in candidates:
            previous_incident_id = str(incident.get("incident_id") or "").strip() or None
            previous_track_id = str(incident.get("last_track_id") or incident.get("primary_track_id") or "").strip() or None
            incident_payload = incident.get("last_payload")
            if previous_incident_id is None or not isinstance(incident_payload, dict):
                continue
            if str(incident.get("camera_id") or "") != result.camera_id:
                continue

            age_ms = max(0.0, (now - float(incident.get("last_seen_monotonic") or 0.0)) * 1000.0)
            if age_ms > INCIDENT_REUSE_WINDOW_MS:
                continue

            fall_state = str(incident.get("fall_state") or "").lower()
            if fall_state not in {"fallen_candidate", "fallen_confirmed", "confirmed_fall", "cooldown"}:
                continue

            previous_bboxes = self._incident_candidate_bboxes(incident)
            if not previous_bboxes:
                continue

            iou, center_distance, center_distance_ratio = self._best_bbox_similarity(current_bbox, previous_bboxes)
            spatial_key = str(incident.get("spatial_key") or "")
            spatial_match = current_spatial_key == spatial_key
            spatial_adjacent = self._spatial_keys_adjacent(current_spatial_key, spatial_key)
            same_track = previous_track_id is not None and previous_track_id == current_track_id
            track_handoff_detected = previous_track_id is not None and previous_track_id != current_track_id
            incident_active = bool(incident.get("active"))

            if same_track:
                reason = "same_track_recent_incident"
                score = 1000.0 - age_ms
            else:
                nearby_bbox = (
                    iou >= INCIDENT_REUSE_MIN_IOU
                    or center_distance_ratio <= INCIDENT_REUSE_MAX_CENTER_DISTANCE_RATIO
                    or spatial_match
                    or spatial_adjacent
                )
                fallen_hold_like = self._object_is_fallen_hold_like(obj)
                if not single_person_scene or not (nearby_bbox or (incident_active and fallen_hold_like)):
                    continue
                reason = (
                    "track_handoff_nearby_single_person_fallen_hold"
                    if nearby_bbox
                    else "track_handoff_active_single_person_fallen_hold"
                )
                score = (200.0 * iou) - age_ms - center_distance_ratio

            debug = self._incident_reuse_debug(
                current_track_id=current_track_id,
                previous_incident_id=previous_incident_id,
                previous_track_id=previous_track_id,
                incident_reused=True,
                incident_reuse_reason=reason,
                incident_reuse_age_ms=age_ms,
                incident_spatial_distance=center_distance,
                incident_iou=iou,
                single_person_scene=single_person_scene,
                track_handoff_detected=track_handoff_detected,
                duplicate_incident_suppressed=track_handoff_detected,
            )
            debug["active_incident_id"] = previous_incident_id
            if score > best_score:
                best_score = score
                best_payload = copy.deepcopy(incident_payload)
                best_debug = debug

        return best_payload, best_debug

    def _reporter_confirm_guard_reason(self, obj: DetectedObject) -> str | None:
        fall_decision = obj.fall_decision or {}
        alarm_preview = obj.alarm_preview or {}
        temporal = obj.temporal or {}
        field_debug = (
            fall_decision.get("field_rule_debug")
            if isinstance(fall_decision.get("field_rule_debug"), dict)
            else temporal.get("field_rule_debug")
        )
        if not isinstance(field_debug, dict):
            field_debug = (
                alarm_preview.get("field_rule_debug")
                if isinstance(alarm_preview.get("field_rule_debug"), dict)
                else {}
            )
        behavior = obj.behavior or {}
        behavior_state = str(
            field_debug.get("behavior_state")
            or behavior.get("behavior_state")
            or ""
        ).strip().lower()
        confirm_source = str(fall_decision.get("confirm_source") or alarm_preview.get("confirm_source") or "").strip().lower()
        low_posture = bool(field_debug.get("low_posture")) or bool(temporal.get("low_posture"))
        has_current_fall_object = bool(field_debug.get("has_current_fall_object"))
        has_temporal_confirm_evidence = bool(field_debug.get("has_temporal_confirm_evidence"))
        bbox_aspect_ratio = self._object_bbox_aspect_ratio(obj, temporal, field_debug)

        if confirm_source == "field_low_posture_recent_fall_hint":
            has_field_debug = bool(field_debug)
            if behavior_state in {"standing", "walking", "upright"} and not low_posture:
                return "reporter_upright_recovery_guard"
            if has_field_debug and not low_posture and bbox_aspect_ratio < float(self.settings.field_fall_candidate_min_aspect):
                return "reporter_upright_recovery_guard"
            if has_field_debug and not has_current_fall_object and not has_temporal_confirm_evidence:
                return "reporter_no_current_fall_evidence_guard"
        return None

    @staticmethod
    def _attach_reporter_guard_debug(obj: DetectedObject, reason: str) -> DetectedObject:
        temporal = dict(obj.temporal or {})
        event_metadata = dict(temporal.get("event_metadata") or {})
        event_metadata["reporter_guard_reason"] = reason
        temporal["event_metadata"] = event_metadata
        return obj.model_copy(update={"temporal": temporal})

    def _refresh_payload_for_result(
        self,
        result: VisionResult,
        obj: DetectedObject,
        payload: dict[str, Any],
        reuse_debug: dict[str, Any],
    ) -> dict[str, Any]:
        updated = self._build_payload(
            result,
            obj,
            incident_id=str(payload.get("incident_id") or "").strip() or None,
            incident_reuse_debug=reuse_debug,
            snapshot_url_override=payload.get("snapshot_url"),
            snapshot_path_override=payload.get("snapshot_path"),
        )
        metadata = updated.get("metadata")
        if isinstance(metadata, dict):
            event = metadata.get("event")
            if isinstance(event, dict):
                if payload.get("snapshot_url") is not None:
                    event["snapshot_url"] = payload.get("snapshot_url")
                if payload.get("snapshot_path") is not None:
                    event["snapshot_path"] = payload.get("snapshot_path")
        return updated

    def _reuse_debug_for_payload(
        self,
        *,
        result: VisionResult,
        obj: DetectedObject,
        payload: dict[str, Any],
        reason: str,
        incident_reused: bool,
        duplicate_incident_suppressed: bool,
    ) -> dict[str, Any]:
        previous_track_id = self._payload_track_id(payload)
        current_track_id = self._object_track_id(obj)
        previous_bbox = payload.get("bbox") if isinstance(payload.get("bbox"), list) else None
        current_bbox = [float(value) for value in obj.bbox]
        iou = self._iou(current_bbox, previous_bbox) if isinstance(previous_bbox, list) and len(previous_bbox) == 4 else 0.0
        distance = (
            self._center_distance(current_bbox, previous_bbox)
            if isinstance(previous_bbox, list) and len(previous_bbox) == 4
            else None
        )
        return self._incident_reuse_debug(
            current_track_id=current_track_id,
            previous_incident_id=str(payload.get("incident_id") or "").strip() or None,
            previous_track_id=previous_track_id,
            incident_reused=incident_reused,
            incident_reuse_reason=reason,
            incident_reuse_age_ms=0.0,
            incident_spatial_distance=distance,
            incident_iou=iou,
            single_person_scene=self._single_person_scene(result),
            track_handoff_detected=previous_track_id is not None and previous_track_id != current_track_id,
            duplicate_incident_suppressed=duplicate_incident_suppressed,
        )

    def _update_incident_delivery_state(self, payload: dict[str, Any], *, sent_to_main: bool) -> None:
        incident_id = str(payload.get("incident_id") or "").strip() or None
        if incident_id is None:
            return
        with self._lock:
            incident = self._incident_cache_by_id.get(incident_id)
            if incident is None:
                return
            incident["sent_to_main"] = sent_to_main

    def _upsert_incident_cache_locked(self, camera_id: str, key: str, payload: dict[str, Any]) -> None:
        incident_id = str(payload.get("incident_id") or "").strip() or None
        if incident_id is None:
            return
        track_id = self._payload_track_id(payload)
        now = time.monotonic()
        incident = self._incident_cache_by_id.get(incident_id)
        if incident is None:
            incident = {
                "incident_id": incident_id,
                "camera_id": camera_id,
                "primary_track_id": track_id,
                "track_ids": set(),
                "first_confirmed_at": payload.get("timestamp"),
                "first_confirmed_monotonic": now,
                "last_seen_at": payload.get("timestamp"),
                "last_seen_monotonic": now,
                "last_bbox": None,
                "recent_bboxes": [],
                "fall_state": str(payload.get("status") or payload.get("state") or ""),
                "confirm_sources": set(),
                "spatial_key": None,
                "cooldown_until": now + max(0.0, float(self.settings.main_system_alert_cooldown_seconds)),
                "sent_to_main": False,
                "active": True,
                "last_payload": copy.deepcopy(payload),
                "last_track_id": track_id,
            }
        if track_id is not None:
            incident["track_ids"].add(track_id)
            if not incident.get("primary_track_id"):
                incident["primary_track_id"] = track_id
        bbox = payload.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            normalized_bbox = [float(value) for value in bbox]
            incident["last_bbox"] = normalized_bbox
            recent_bboxes = list(incident.get("recent_bboxes") or [])
            recent_bboxes.append(normalized_bbox)
            incident["recent_bboxes"] = recent_bboxes[-5:]
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        confirm_source = None
        fall_decision = metadata.get("fall_decision")
        if isinstance(fall_decision, dict):
            confirm_source = fall_decision.get("confirm_source")
        if confirm_source is None:
            event = metadata.get("event")
            if isinstance(event, dict):
                confirm_source = event.get("confirm_source")
        if confirm_source:
            incident["confirm_sources"].add(str(confirm_source))
        incident["last_seen_at"] = payload.get("timestamp")
        incident["last_seen_monotonic"] = now
        incident["fall_state"] = str(payload.get("status") or payload.get("state") or incident.get("fall_state") or "")
        incident["spatial_key"] = metadata.get("incident_spatial_key") or incident.get("spatial_key")
        incident["cooldown_until"] = now + max(0.0, float(self.settings.main_system_alert_cooldown_seconds))
        incident["active"] = True
        incident["last_payload"] = copy.deepcopy(payload)
        incident["last_track_id"] = track_id
        self._incident_cache_by_id[incident_id] = incident
        self._incident_ids_by_camera.setdefault(camera_id, set()).add(incident_id)
        active_keys = self._active_keys_by_incident_id.setdefault(incident_id, set())
        active_keys.add(key)

    @staticmethod
    def _incident_candidate_bboxes(incident: dict[str, Any]) -> list[list[float]]:
        candidates: list[list[float]] = []
        recent_bboxes = incident.get("recent_bboxes")
        if isinstance(recent_bboxes, list):
            for bbox in recent_bboxes:
                if isinstance(bbox, list) and len(bbox) == 4:
                    candidates.append([float(value) for value in bbox])
        last_bbox = incident.get("last_bbox")
        if isinstance(last_bbox, list) and len(last_bbox) == 4:
            normalized_last_bbox = [float(value) for value in last_bbox]
            if normalized_last_bbox not in candidates:
                candidates.append(normalized_last_bbox)
        return candidates

    @classmethod
    def _best_bbox_similarity(cls, current_bbox: list[float], previous_bboxes: list[list[float]]) -> tuple[float, float | None, float]:
        best_iou = 0.0
        best_distance: float | None = None
        best_ratio = float("inf")
        for previous_bbox in previous_bboxes:
            iou = cls._iou(current_bbox, previous_bbox)
            distance = cls._center_distance(current_bbox, previous_bbox)
            ratio = cls._center_distance_ratio(current_bbox, previous_bbox)
            if iou > best_iou or (iou == best_iou and ratio < best_ratio):
                best_iou = iou
                best_distance = distance
                best_ratio = ratio
        return best_iou, best_distance, best_ratio

    @staticmethod
    def _parse_spatial_key(spatial_key: str) -> tuple[int, int, int, int] | None:
        parts = spatial_key.split(":")
        if len(parts) < 6:
            return None
        try:
            return int(parts[-4]), int(parts[-3]), int(parts[-2]), int(parts[-1])
        except (TypeError, ValueError):
            return None

    @classmethod
    def _spatial_keys_adjacent(cls, current_spatial_key: str, previous_spatial_key: str) -> bool:
        current = cls._parse_spatial_key(current_spatial_key)
        previous = cls._parse_spatial_key(previous_spatial_key)
        if current is None or previous is None:
            return False
        return (
            abs(current[0] - previous[0]) <= 1
            and abs(current[1] - previous[1]) <= 1
            and abs(current[2] - previous[2]) <= 1
            and abs(current[3] - previous[3]) <= 1
        )

    def _object_is_fallen_hold_like(self, obj: DetectedObject) -> bool:
        temporal = obj.temporal or {}
        field_debug = temporal.get("field_rule_debug") if isinstance(temporal.get("field_rule_debug"), dict) else {}
        behavior = obj.behavior or {}
        behavior_state = str(field_debug.get("behavior_state") or behavior.get("behavior_state") or "").strip().lower()
        low_posture = bool(field_debug.get("low_posture")) or bool(temporal.get("low_posture"))
        stillness = field_debug.get("stillness")
        if stillness is None:
            stillness = temporal.get("stillness")
        aspect_ratio = self._object_bbox_aspect_ratio(obj, temporal, field_debug if isinstance(field_debug, dict) else {})
        return (
            low_posture
            or behavior_state in {"lying", "fallen"}
            or (bool(stillness) and aspect_ratio >= float(self.settings.field_fall_candidate_min_aspect))
        )

    def _object_bbox_aspect_ratio(
        self,
        obj: DetectedObject,
        temporal: dict[str, Any],
        field_debug: dict[str, Any],
    ) -> float:
        if field_debug.get("bbox_aspect_ratio") is not None:
            try:
                return float(field_debug["bbox_aspect_ratio"])
            except (TypeError, ValueError):
                pass
        if temporal.get("bbox_aspect_ratio") is not None:
            try:
                return float(temporal["bbox_aspect_ratio"])
            except (TypeError, ValueError):
                pass
        x1, y1, x2, y2 = [float(value) for value in obj.bbox]
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        return width / height

    def _mark_incident_inactive_for_key_locked(self, key: str, payload: dict[str, Any] | None) -> None:
        incident_id = None
        if isinstance(payload, dict):
            incident_id = str(payload.get("incident_id") or "").strip() or None
        if incident_id is None:
            return
        active_keys = self._active_keys_by_incident_id.get(incident_id)
        if active_keys is None:
            return
        active_keys.discard(key)
        incident = self._incident_cache_by_id.get(incident_id)
        if incident is not None:
            incident["active"] = bool(active_keys)
            if not active_keys:
                incident["fall_state"] = "cooldown"
                incident["cooldown_until"] = time.monotonic() + max(
                    INCIDENT_REUSE_WINDOW_MS / 1000.0,
                    float(self.settings.main_system_alert_cooldown_seconds),
                )
        if not active_keys:
            self._active_keys_by_incident_id.pop(incident_id, None)

    @staticmethod
    def _single_person_scene(result: VisionResult) -> bool:
        person_count = sum(1 for item in result.objects if item.label == "person")
        return person_count <= 1

    @staticmethod
    def _object_track_id(obj: DetectedObject) -> str:
        return str(obj.track_id if obj.track_id is not None else obj.person_id or "untracked")

    @staticmethod
    def _payload_track_id(payload: dict[str, Any]) -> str | None:
        track_id = str(payload.get("track_id") or "").strip()
        return track_id or None

    def _default_incident_reuse_debug(self, result: VisionResult, obj: DetectedObject) -> dict[str, Any]:
        return self._incident_reuse_debug(
            current_track_id=self._object_track_id(obj),
            previous_incident_id=None,
            previous_track_id=None,
            incident_reused=False,
            incident_reuse_reason=None,
            incident_reuse_age_ms=None,
            incident_spatial_distance=None,
            incident_iou=0.0,
            single_person_scene=self._single_person_scene(result),
            track_handoff_detected=False,
            duplicate_incident_suppressed=False,
        )

    @staticmethod
    def _incident_reuse_debug(
        *,
        current_track_id: str,
        previous_incident_id: str | None,
        previous_track_id: str | None,
        incident_reused: bool,
        incident_reuse_reason: str | None,
        incident_reuse_age_ms: float | None,
        incident_spatial_distance: float | None,
        incident_iou: float,
        single_person_scene: bool,
        track_handoff_detected: bool,
        duplicate_incident_suppressed: bool,
    ) -> dict[str, Any]:
        return {
            "incident_reuse_checked": True,
            "incident_reused": incident_reused,
            "incident_reuse_reason": incident_reuse_reason,
            "active_incident_id": previous_incident_id,
            "previous_incident_id": previous_incident_id,
            "previous_track_id": previous_track_id,
            "current_track_id": current_track_id,
            "track_handoff_detected": track_handoff_detected,
            "incident_reuse_age_ms": None if incident_reuse_age_ms is None else round(float(incident_reuse_age_ms), 1),
            "incident_reuse_window_ms": INCIDENT_REUSE_WINDOW_MS,
            "incident_spatial_distance": None
            if incident_spatial_distance is None
            else round(float(incident_spatial_distance), 2),
            "incident_iou": round(float(incident_iou), 4),
            "single_person_scene": single_person_scene,
            "duplicate_incident_suppressed": duplicate_incident_suppressed,
        }

    @staticmethod
    def _center_distance(a: list[float], b: list[float]) -> float:
        ax1, ay1, ax2, ay2 = [float(value) for value in a]
        bx1, by1, bx2, by2 = [float(value) for value in b]
        acx = (ax1 + ax2) / 2.0
        acy = (ay1 + ay2) / 2.0
        bcx = (bx1 + bx2) / 2.0
        bcy = (by1 + by2) / 2.0
        return ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5

    @staticmethod
    def _center_distance_ratio(a: list[float], b: list[float]) -> float:
        distance = FallEventReporterService._center_distance(a, b)
        aw = max(1.0, float(a[2]) - float(a[0]))
        ah = max(1.0, float(a[3]) - float(a[1]))
        bw = max(1.0, float(b[2]) - float(b[0]))
        bh = max(1.0, float(b[3]) - float(b[1]))
        scale = max((aw**2 + ah**2) ** 0.5, (bw**2 + bh**2) ** 0.5, 1.0)
        return distance / scale

    @staticmethod
    def _iou(a: list[float], b: list[float]) -> float:
        ax1, ay1, ax2, ay2 = [float(value) for value in a]
        bx1, by1, bx2, by2 = [float(value) for value in b]
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

    @staticmethod
    def _attach_event_metadata(obj: DetectedObject, payload: dict[str, Any] | None) -> DetectedObject:
        if payload is None:
            return obj
        temporal = dict(obj.temporal or {})
        event_metadata = dict(temporal.get("event_metadata") or {})
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        event_metadata.update(
            {
                "incident_id": payload.get("incident_id"),
                "snapshot_url": payload.get("snapshot_url"),
                "snapshot_path": payload.get("snapshot_path"),
                "incident_reuse_debug": metadata.get("incident_reuse_debug"),
            }
        )
        temporal["event_metadata"] = event_metadata
        return obj.model_copy(update={"temporal": temporal})

    def _build_payload(
        self,
        result: VisionResult,
        obj: DetectedObject,
        *,
        incident_id: str | None = None,
        incident_reuse_debug: dict[str, Any] | None = None,
        snapshot_url_override: str | None = None,
        snapshot_path_override: str | None = None,
    ) -> dict[str, Any]:
        fall_decision = dict(obj.fall_decision or {})
        alarm_preview = dict(obj.alarm_preview or {})
        temporal = dict(obj.temporal or {})
        shadow = dict(temporal.get("shadow") or {}) if isinstance(temporal.get("shadow"), dict) else {}
        risk = self._normalize_risk(alarm_preview.get("risk_level") or fall_decision.get("risk_level"))
        fall_prob = self._fall_probability(obj, temporal, shadow)
        track_id = str(obj.track_id if obj.track_id is not None else obj.person_id or "untracked")
        timestamp_slug = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        incident_identity_key = self._incident_identity_key(
            result.camera_id,
            obj,
            result.frame_width,
            result.frame_height,
        )
        incident_key = self._incident_spatial_key(result.camera_id, obj, result.frame_width, result.frame_height)
        resolved_incident_id = incident_id or f"vision-fall-{self._safe_slug(incident_identity_key)}-{timestamp_slug}"
        if snapshot_url_override is not None or snapshot_path_override is not None:
            snapshot_url = snapshot_url_override
            snapshot_path = snapshot_path_override
        else:
            snapshot_url, snapshot_path = self._save_snapshot(result.camera_id, track_id, timestamp_slug)
        severity = "L3" if risk in {"high", "critical"} or fall_prob >= 0.82 else "L2"
        source = str(temporal.get("source") or temporal.get("model_source") or "")
        scores = {
            "temporal": fall_prob,
            "mock": temporal.get("mock_fall_probability"),
            "shadow_onnx_lstm": shadow.get("fall_probability"),
        }
        reuse_debug = dict(incident_reuse_debug or self._default_incident_reuse_debug(result, obj))
        return {
            "camera_id": result.camera_id,
            "stream_name": "primary",
            "source": "vision_service",
            "event_type": "fall_confirmed",
            "state": "confirmed_fall",
            "status": str(fall_decision.get("fall_state") or "fallen_confirmed"),
            "service_state": "running",
            "severity": severity,
            "risk": risk,
            "risk_level": risk,
            "fall_detected": True,
            "fall_prob": fall_prob,
            "fall_score": fall_prob,
            "track_id": track_id,
            "incident_id": resolved_incident_id,
            "bbox": [float(value) for value in obj.bbox],
            "snapshot_url": snapshot_url,
            "snapshot_path": snapshot_path,
            "timestamp": result.timestamp,
            "scores": {key: value for key, value in scores.items() if value is not None},
            "injury": {
                "level": "I3" if severity == "L3" else "I2",
                "reason": "vision_service_fallen_confirmed",
                "advice": "Please inspect the live camera view immediately and confirm the elder's condition.",
            },
            "metadata": {
                "event": {
                    "incident_id": resolved_incident_id,
                    "camera_id": result.camera_id,
                    "stream_name": "primary",
                    "event_type": "fall_confirmed",
                    "state": "confirmed_fall",
                    "status": str(fall_decision.get("fall_state") or "fallen_confirmed"),
                    "severity": severity,
                    "risk": risk,
                    "risk_level": risk,
                    "fall_score": fall_prob,
                    "fall_prob": fall_prob,
                    "track_id": track_id,
                    "snapshot_url": snapshot_url,
                    "snapshot_path": snapshot_path,
                    "injury": {
                        "level": "I3" if severity == "L3" else "I2",
                        "reason": "vision_service_fallen_confirmed",
                        "advice": "Please inspect the live camera view immediately and confirm the elder's condition.",
                    },
                    "multimodal_review": {
                        "provider": self.settings.temporal_model_provider,
                        "temporal_source": source,
                        "scores": {key: value for key, value in scores.items() if value is not None},
                    },
                    "incident_reuse_debug": reuse_debug,
                },
                "provider": self.settings.temporal_model_provider,
                "model_source": source,
                "feature_schema_hash": temporal.get("feature_schema_hash"),
                "frame_seq": result.frame_seq,
                "frame_width": result.frame_width,
                "frame_height": result.frame_height,
                "object_confidence": obj.confidence,
                "incident_identity_key": incident_identity_key,
                "incident_spatial_key": incident_key,
                "person_id": obj.person_id,
                "person_name": obj.person_name,
                "fall_decision": fall_decision,
                "alarm_preview": alarm_preview,
                "temporal": temporal,
                "incident_reuse_debug": reuse_debug,
            },
        }

    def _ensure_snapshot_fields(self, camera_id: str, track_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("snapshot_url") and payload.get("snapshot_path"):
            return payload
        timestamp_slug = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        snapshot_url, snapshot_path = self._save_snapshot(camera_id, track_id, timestamp_slug)
        if snapshot_url is None and snapshot_path is None:
            return payload
        updated = copy.deepcopy(payload)
        if snapshot_url is not None:
            updated["snapshot_url"] = snapshot_url
        if snapshot_path is not None:
            updated["snapshot_path"] = snapshot_path
        metadata = updated.get("metadata")
        if isinstance(metadata, dict):
            event = metadata.get("event")
            if isinstance(event, dict):
                if snapshot_url is not None:
                    event["snapshot_url"] = snapshot_url
                if snapshot_path is not None:
                    event["snapshot_path"] = snapshot_path
        return updated

    def _save_snapshot(self, camera_id: str, track_id: str, timestamp_slug: str) -> tuple[str | None, str | None]:
        try:
            buffer = self.source_manager.get_buffer(camera_id)
            packet = buffer.latest() if buffer else None
            if packet is None:
                logger.warning("fall_event_snapshot_missing_frame camera_id=%s", camera_id)
                return None, None
            snapshot_dir = Path(self.settings.fall_event_snapshot_dir)
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{self._safe_slug(camera_id)}_{self._safe_slug(track_id)}_{timestamp_slug}.jpg"
            path = snapshot_dir / filename
            ok = cv2.imwrite(str(path), packet.frame)
            if not ok:
                logger.warning("fall_event_snapshot_write_failed path=%s", path)
                return None, None
            base_url = self.settings.vision_service_public_base_url.rstrip("/")
            snapshot_url = (
                f"{base_url}/fall-events/snapshots/{filename}"
                if base_url
                else f"/fall-events/snapshots/{filename}"
            )
            return snapshot_url, str(path.resolve())
        except Exception as exc:
            logger.warning("fall_event_snapshot_error camera_id=%s error=%s", camera_id, exc)
            return None, None

    def _can_send(self, key: str) -> bool:
        now = time.monotonic()
        cooldown = max(0.0, float(self.settings.main_system_alert_cooldown_seconds))
        with self._lock:
            last_sent = self._last_sent_at.get(key)
            if last_sent is not None and now - last_sent < cooldown:
                return False
            self._last_sent_at[key] = now
            return True

    def _endpoint_url(self) -> str:
        with self._lock:
            return f"{self._endpoint_base_url}{self._endpoint_path}"

    def _alert_headers(self) -> dict[str, str]:
        token = str(self.settings.main_system_alert_token or "").strip()
        header_name = str(self.settings.main_system_alert_token_header or "").strip()
        if not token or not header_name:
            return {}
        return {header_name: token}

    @staticmethod
    def _is_confirmed_fall(obj: DetectedObject) -> bool:
        fall_decision = obj.fall_decision or {}
        alarm_preview = obj.alarm_preview or {}
        fall_state = str(fall_decision.get("fall_state") or fall_decision.get("state") or "").lower()
        if fall_state in {"fallen_confirmed", "confirmed_fall"}:
            return True
        confirmed = bool(alarm_preview.get("confirmed"))
        risk = str(alarm_preview.get("risk_level") or alarm_preview.get("risk") or "").lower()
        return confirmed and risk in {"high", "critical"}

    @staticmethod
    def _has_person_evidence(obj: DetectedObject) -> bool:
        fall_decision = obj.fall_decision or {}
        alarm_preview = obj.alarm_preview or {}
        for payload in (fall_decision, alarm_preview):
            if "person_evidence" in payload:
                return bool(payload.get("person_evidence"))
        return True

    @staticmethod
    def _fall_probability(obj: DetectedObject, temporal: dict[str, Any], shadow: dict[str, Any]) -> float:
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
        if values:
            return max(values)
        return 0.91

    @staticmethod
    def _normalize_risk(value: Any) -> str:
        risk = str(value or "").strip().lower()
        if risk in {"low", "medium", "high", "critical"}:
            return risk
        return "critical"

    @staticmethod
    def _cooldown_key(result: VisionResult, obj: DetectedObject) -> str:
        return FallEventReporterService._incident_identity_key(
            result.camera_id,
            obj,
            result.frame_width,
            result.frame_height,
        )

    @staticmethod
    def _incident_identity_key(camera_id: str, obj: DetectedObject, frame_width: int, frame_height: int) -> str:
        if obj.track_id is not None:
            return f"{camera_id}:track:{int(obj.track_id)}"
        person_id = str(obj.person_id or "").strip()
        if person_id:
            return f"{camera_id}:person:{person_id}"
        return FallEventReporterService._incident_spatial_key(
            camera_id,
            obj,
            frame_width,
            frame_height,
        )

    @staticmethod
    def _incident_spatial_key(camera_id: str, obj: DetectedObject, frame_width: int, frame_height: int) -> str:
        x1, y1, x2, y2 = [float(value) for value in obj.bbox]
        width = max(1.0, float(frame_width or 1))
        height = max(1.0, float(frame_height or 1))
        cx = ((x1 + x2) / 2.0) / width
        cy = ((y1 + y2) / 2.0) / height
        bw = max(0.0, (x2 - x1) / width)
        bh = max(0.0, (y2 - y1) / height)
        # Coarse cells intentionally group the same physical fall even when ByteTrack changes ids.
        return (
            f"{camera_id}:fall:"
            f"{int(max(0.0, min(0.999, cx)) * 8)}:"
            f"{int(max(0.0, min(0.999, cy)) * 6)}:"
            f"{int(max(0.0, min(0.999, bw)) * 4)}:"
            f"{int(max(0.0, min(0.999, bh)) * 4)}"
        )

    @staticmethod
    def _safe_slug(value: Any) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "unknown")).strip("._")
        return cleaned or "unknown"
