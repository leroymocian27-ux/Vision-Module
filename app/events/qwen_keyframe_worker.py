from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Callable

from app.events.archive import EventArchive
from app.events.qwen_keyframe import (
    QwenKeyframeAnalyzer,
    QwenKeyframeError,
    QwenKeyframeInvalidOutput,
    QwenKeyframeNonChineseOutput,
    QwenKeyframeTimeout,
)
from app.events.schemas import EventOutboxRecord, QwenKeyframeAdvisory, event_now_iso


class QwenKeyframeWorker:
    """Single-concurrency image sidecar that never runs on the realtime path."""

    def __init__(
        self,
        *,
        analyzer: QwenKeyframeAnalyzer,
        archive: EventArchive,
        max_images: int,
        max_image_bytes: int,
        update: Callable[[str, QwenKeyframeAdvisory], None],
        max_pending_events: int = 2,
    ) -> None:
        self.analyzer = analyzer
        self.archive = archive
        self.max_images = max(1, int(max_images))
        self.max_image_bytes = max(1024, int(max_image_bytes))
        self.max_pending_events = max(1, int(max_pending_events))
        self._update = update
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qwen-keyframe")
        self._lock = threading.Lock()
        self._futures: dict[str, Future[None]] = {}
        self._stopped = False

    def schedule(self, record: EventOutboxRecord) -> bool:
        if not record.archive_path or record.evidence_package is None:
            return False
        with self._lock:
            if self._stopped or record.incident_id in self._futures:
                return False
            if len(self._futures) >= self.max_pending_events:
                return False
            previous = record.qwen_advisory
            if previous is not None and previous.analysis_status in {"pending", "processing", "completed"}:
                return False
            pending = QwenKeyframeAdvisory(
                analysis_status="pending",
                provider="ollama_qwen",
                model_name=self.analyzer.model_name,
            )
            self._update(record.incident_id, pending)
            future = self._executor.submit(self._run, record.incident_id, record.archive_path, record.evidence_package, record.event_semantics)
            self._futures[record.incident_id] = future
            future.add_done_callback(lambda _: self._clear(record.incident_id))
            return True

    def status(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "running": not self._stopped,
                "queued_or_running": len(self._futures),
                "max_pending_events": self.max_pending_events,
            }

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            futures = tuple(self._futures.values())
        for future in futures:
            future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, incident_id: str, archive_path: str, evidence, semantics) -> None:
        self._update(incident_id, QwenKeyframeAdvisory(
            analysis_status="processing", provider="ollama_qwen", model_name=self.analyzer.model_name,
        ))
        try:
            images, missing = self.archive.read_qwen_keyframe_images(
                archive_path,
                evidence,
                max_images=self.max_images,
                max_image_bytes=self.max_image_bytes,
            )
            advisory = self.analyzer.analyze(semantics=semantics, images=images, missing_reasons=missing)
        except QwenKeyframeTimeout:
            advisory = self._failure("degraded", "qwen_timeout")
        except QwenKeyframeNonChineseOutput:
            advisory = self._failure("degraded", "qwen_non_chinese_output")
        except QwenKeyframeInvalidOutput:
            advisory = self._failure("degraded", "qwen_invalid_json")
        except QwenKeyframeError:
            advisory = self._failure("degraded", "qwen_unavailable")
        except Exception:
            advisory = self._failure("failed", "qwen_worker_failed")
        self._update(incident_id, advisory)
        self.archive.write_qwen_advisory(archive_path, advisory)

    def _failure(self, status: str, error_code: str) -> QwenKeyframeAdvisory:
        return QwenKeyframeAdvisory(
            analysis_status=status,  # type: ignore[arg-type]
            provider="ollama_qwen",
            model_name=self.analyzer.model_name,
            error_code=error_code,
            completed_at=event_now_iso(),
        )

    def _clear(self, incident_id: str) -> None:
        with self._lock:
            self._futures.pop(incident_id, None)
