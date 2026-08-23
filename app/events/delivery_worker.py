from __future__ import annotations

import threading
from typing import Any

from app.core.config import Settings
from app.core.logger import get_logger
from app.events.delivery import DeliveryOutbox

logger = get_logger(__name__)


class DeliveryWorker:
    """Lightweight optional retry worker for DeliveryOutbox.

    The worker is intentionally not wired into the realtime path by default.
    """

    def __init__(self, settings: Settings, outbox: DeliveryOutbox) -> None:
        self.settings = settings
        self.outbox = outbox
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.event_delivery_enabled and self.settings.event_delivery_worker_enabled)

    def start(self) -> None:
        if not self.enabled:
            logger.info("event_delivery_worker_disabled")
            return
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="event-delivery-worker", daemon=True)
        self._worker.start()
        logger.info("event_delivery_worker_started")

    def stop(self) -> None:
        self._stop.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=3)

    def process_once(self, worker_id: str = "event-delivery-worker") -> Any | None:
        if not self.enabled:
            return None
        try:
            record = self.outbox.claim_next(worker_id, self.settings.event_delivery_claim_ttl_seconds)
            if record is None:
                return None
            return self.outbox.deliver(record.delivery_id)
        except Exception as exc:
            logger.warning("event_delivery_worker_process_failed error=%s", exc)
            return None

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": bool(self._worker and self._worker.is_alive()),
            "interval_seconds": self.settings.event_delivery_worker_interval_seconds,
            "claim_ttl_seconds": self.settings.event_delivery_claim_ttl_seconds,
        }

    def _run(self) -> None:
        interval = max(0.1, float(self.settings.event_delivery_worker_interval_seconds))
        while not self._stop.wait(interval):
            self.process_once()
        logger.info("event_delivery_worker_stopped")
