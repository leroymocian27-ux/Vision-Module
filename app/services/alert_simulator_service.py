from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import requests

from app.core.logger import get_logger
from app.schemas.common import utc_now_iso

logger = get_logger(__name__)


class AlertSimulatorService:
    def __init__(self, reporter) -> None:
        self.reporter = reporter
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._interval_seconds = 2.0
        self._camera_id = "camera_01"
        self._track_id = "smoke-track"
        self._fall_prob = 0.91
        self._sent_count = 0
        self._last_status: str | None = None
        self._last_error: str | None = None
        self._last_sent_at: str | None = None
        self._last_payload: dict[str, Any] | None = None

    def start(
        self,
        *,
        interval_seconds: float,
        camera_id: str,
        track_id: str,
        fall_prob: float,
    ) -> dict[str, Any]:
        self.stop()
        with self._lock:
            self._interval_seconds = interval_seconds
            self._camera_id = camera_id
            self._track_id = track_id
            self._fall_prob = fall_prob
            self._sent_count = 0
            self._last_status = "starting"
            self._last_error = None
            self._last_sent_at = None
            self._last_payload = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="alert-simulator", daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self._thread = None
        with self._lock:
            if self._last_status == "starting":
                self._last_status = "stopped"
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "interval_seconds": self._interval_seconds,
                "target_url": self.reporter.endpoint_url(),
                "camera_id": self._camera_id,
                "track_id": self._track_id,
                "sent_count": self._sent_count,
                "last_status": self._last_status,
                "last_error": self._last_error,
                "last_sent_at": self._last_sent_at,
                "last_payload": dict(self._last_payload) if self._last_payload is not None else None,
            }

    def send_once(
        self,
        *,
        target_ip: str | None = None,
        base_url: str | None = None,
        event_id: str | None = None,
        camera_id: str,
        track_id: str,
        fall_prob: float,
    ) -> dict[str, Any]:
        try:
            target_url = self._manual_target_url(target_ip=target_ip, base_url=base_url)
        except ValueError as exc:
            sent_at = utc_now_iso()
            return {
                "ok": False,
                "target_url": "",
                "status_code": None,
                "response_body": None,
                "error": str(exc),
                "sent_at": sent_at,
                "incident_id": "",
            }
        self._apply_manual_endpoint(target_ip=target_ip, base_url=base_url)
        payload = self._build_payload(camera_id=camera_id, track_id=track_id, fall_prob=fall_prob, incident_id=event_id)
        sent_at = utc_now_iso()
        delivery_result = self.reporter.send_external_alert_once(payload)
        delivery = delivery_result.get("delivery") if isinstance(delivery_result.get("delivery"), dict) else {}
        status_code = delivery.get("last_http_status")
        ack = delivery.get("ack") if isinstance(delivery.get("ack"), dict) else None
        response_body = json.dumps(ack, ensure_ascii=False, sort_keys=True) if ack is not None else None
        error = delivery.get("last_error")
        ok = str(delivery.get("status") or "").strip() == "delivered"
        logger.info("alert_simulator_send_once status=%s url=%s event_id=%s", delivery.get("status"), target_url, payload.get("event_id"))
        with self._lock:
            self._sent_count += 1
            self._last_status = str(delivery.get("status") or ("http_" + str(status_code) if status_code is not None else "request_error"))
            self._last_error = error
            self._last_sent_at = sent_at
            self._last_payload = dict(payload)
        return {
            "ok": ok,
            "target_url": target_url,
            "status_code": status_code,
            "response_body": response_body,
            "error": error,
            "sent_at": sent_at,
            "incident_id": str(payload["incident_id"]),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            payload = self._build_payload(
                camera_id=self._camera_id,
                track_id=self._track_id,
                fall_prob=self._fall_prob,
            )
            try:
                response = requests.post(
                    self.reporter.endpoint_url(),
                    json=payload,
                    headers=self._alert_headers(),
                    timeout=self.reporter.request_timeout_seconds(),
                )
                status = f"http_{response.status_code}"
                error = None if response.status_code < 400 else response.text[:500]
                logger.info("alert_simulator_posted status=%s url=%s", response.status_code, self.reporter.endpoint_url())
            except requests.RequestException as exc:
                status = "request_error"
                error = str(exc)
                logger.warning("alert_simulator_request_error url=%s error=%s", self.reporter.endpoint_url(), exc)
            with self._lock:
                self._sent_count += 1
                self._last_status = status
                self._last_error = error
                self._last_sent_at = utc_now_iso()
                self._last_payload = dict(payload)
            self._stop.wait(self._interval_seconds)

    def _build_payload(self, *, camera_id: str, track_id: str, fall_prob: float, incident_id: str | None = None) -> dict[str, Any]:
        timestamp = utc_now_iso()
        normalized_incident_id = str(incident_id or "").strip()
        if not normalized_incident_id:
            normalized_incident_id = (
                f"vision-fall-smoke-{camera_id}-{track_id}-"
                f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-{uuid4().hex[:8]}"
            )
        probability = max(0.0, min(1.0, float(fall_prob)))
        legacy_payload = {
            "camera_id": camera_id,
            "stream_name": "primary",
            "source": "vision_service_simulator",
            "event_type": "fall_confirmed",
            "state": "confirmed_fall",
            "status": "fallen_confirmed",
            "service_state": "running",
            "severity": "L3",
            "risk": "critical",
            "risk_level": "critical",
            "fall_detected": True,
            "fall_prob": probability,
            "fall_score": probability,
            "track_id": track_id,
            "incident_id": normalized_incident_id,
            "bbox": [80.0, 60.0, 380.0, 330.0],
            "snapshot_url": None,
            "snapshot_path": None,
            "timestamp": timestamp,
            "scores": {
                "temporal": probability,
                "simulator": 1.0,
            },
            "injury": {
                "level": "I3",
                "reason": "vision_service_simulator",
                "advice": "Simulated fall event for LAN connectivity verification.",
            },
            "metadata": {
                "event": {
                    "incident_id": normalized_incident_id,
                    "camera_id": camera_id,
                    "stream_name": "primary",
                    "event_type": "fall_confirmed",
                    "state": "confirmed_fall",
                    "status": "fallen_confirmed",
                    "severity": "L3",
                    "risk": "critical",
                    "risk_level": "critical",
                    "fall_score": probability,
                    "fall_prob": probability,
                    "track_id": track_id,
                    "snapshot_url": None,
                    "snapshot_path": None,
                    "injury": {
                        "level": "I3",
                        "reason": "vision_service_simulator",
                        "advice": "Simulated fall event for LAN connectivity verification.",
                    },
                    "multimodal_review": {
                        "provider": "simulator",
                        "temporal_source": "simulator",
                        "scores": {
                            "temporal": probability,
                            "simulator": 1.0,
                        },
                    },
                },
                "trigger": "vision_service_alert_simulator",
                "provider": "simulator",
            },
        }
        return {
            "schema_version": "1.0",
            "event_id": normalized_incident_id,
            "incident_id": normalized_incident_id,
            "source": "camera-service",
            "camera_id": camera_id,
            "track_id": track_id,
            "event_time": timestamp,
            "sent_at": timestamp,
            "alert_type": "fall",
            "alert_level": "high",
            "safety_outcome": "alert",
            "fall_verdict": "confirmed_fall",
            "confidence": probability,
            "summary": "Simulated fall alert for LAN integration verification.",
            "recommended_action": "emergency_alert",
            "analysis_status": "completed",
            "binary_result": {"fall_probability": probability, "source": "simulator"},
            "qwen_review": {
                "analysis_status": "completed",
                "fall_verdict": "confirmed_fall",
                "high_risk_fall": 1,
                "recommended_action": "emergency_alert",
                "summary": "Simulated fall alert for LAN integration verification.",
                "confidence": probability,
            },
            "evidence": [{"type": "simulator", "track_id": track_id}],
            "test_event": True,
            "legacy_payload": legacy_payload,
        }

    def _manual_target_url(self, *, target_ip: str | None = None, base_url: str | None = None) -> str:
        settings = self.reporter.settings
        alert_path = str(getattr(settings, "main_system_alert_path", "") or "").strip()
        legacy_path = str(getattr(settings, "main_system_fall_event_path", "") or "").strip()
        default_path = "/api/integrations/fall-detection/alerts"
        path = legacy_path if legacy_path and legacy_path != alert_path and legacy_path != default_path else (alert_path or legacy_path or default_path)
        if path and not path.startswith("/"):
            path = f"/{path}"
        if base_url:
            return f"{base_url.strip().rstrip('/')}{path}"
        if target_ip:
            return f"http://{target_ip.strip()}:{settings.main_system_default_port}{path}"
        endpoint = self.reporter.endpoint_url()
        if not endpoint:
            raise ValueError("target_ip, base_url, or configured MAIN_SYSTEM_BASE_URL is required")
        return endpoint

    def _apply_manual_endpoint(self, *, target_ip: str | None = None, base_url: str | None = None) -> None:
        if base_url:
            self.reporter.update_endpoint(
                base_url=base_url.strip().rstrip("/"),
                path=self.reporter.status().get("endpoint_path") or "/api/integrations/fall-detection/alerts",
                enabled=True,
                start_worker=False,
            )
            return
        if target_ip:
            self.reporter.update_endpoint(
                base_url=f"http://{target_ip.strip()}:{self.reporter.settings.main_system_default_port}",
                path=self.reporter.status().get("endpoint_path") or "/api/integrations/fall-detection/alerts",
                enabled=True,
                start_worker=False,
            )

    def _alert_headers(self) -> dict[str, str]:
        settings = self.reporter.settings
        token = str(settings.main_system_alert_token or "").strip()
        header_name = str(settings.main_system_alert_token_header or "").strip()
        if not token or not header_name:
            return {}
        return {header_name: token}
