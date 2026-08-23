from __future__ import annotations

import threading

from app.camera.source_manager import CameraSourceManager
from app.core.config import Settings
from app.core.logger import get_logger
from app.services.identity_binding_service import IdentityBindingService
from app.detection.realtime_result_store import RealtimeResultStore

logger = get_logger(__name__)


class IdentityBindingWorkerService:
    """Low-frequency identity worker kept off the tracking hot path."""

    def __init__(
        self,
        settings: Settings,
        source_manager: CameraSourceManager,
        realtime_store: RealtimeResultStore,
        identity_binding_service: IdentityBindingService,
    ) -> None:
        self.settings = settings
        self.source_manager = source_manager
        self.realtime_store = realtime_store
        self.identity_binding_service = identity_binding_service
        self._workers: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._last_error: dict[str, str | None] = {}
        self._lock = threading.Lock()

    def start_for_camera(self, camera_id: str) -> None:
        if not self.settings.enable_identity_binding or not self.settings.identity_binding_async:
            return
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing and existing.is_alive():
                return
            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._run_loop,
                args=(camera_id, stop_event),
                name=f"identity-binding-worker-{camera_id}",
                daemon=True,
            )
            self._stops[camera_id] = stop_event
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

    def last_error(self, camera_id: str) -> str | None:
        with self._lock:
            return self._last_error.get(camera_id)

    def _run_loop(self, camera_id: str, stop_event: threading.Event) -> None:
        interval = 1 / max(self.settings.identity_binding_worker_fps, 0.1)
        logger.info("identity_binding_worker_started camera_id=%s", camera_id)
        while not stop_event.is_set():
            try:
                self._tick(camera_id)
                with self._lock:
                    self._last_error[camera_id] = None
            except Exception as exc:
                logger.exception("identity_binding_worker_error camera_id=%s", camera_id)
                with self._lock:
                    self._last_error[camera_id] = str(exc)
            stop_event.wait(interval)
        logger.info("identity_binding_worker_stopped camera_id=%s", camera_id)

    def _tick(self, camera_id: str) -> None:
        tracking = self.realtime_store.latest_tracking(camera_id)
        if tracking is None or not tracking.objects:
            self.identity_binding_service.refresh_health()
            return
        buffer = self.source_manager.get_buffer(camera_id)
        packet = buffer.latest() if buffer else None
        if packet is None:
            self.identity_binding_service.refresh_health()
            return
        self.identity_binding_service.process_candidates(
            camera_id=camera_id,
            frame=packet.frame,
            objects=tracking.objects,
        )
