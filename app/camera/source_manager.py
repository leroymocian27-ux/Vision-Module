from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from app.camera.capture_worker import CaptureWorker, CaptureWorkerStatus
from app.camera.frame_buffer import FrameBuffer, FramePacket
from app.camera.mjpeg_stream_worker import MJPEGStreamWorker
from app.camera.source_models import CameraSourceConfig, is_local_file_source, is_mjpeg_source, is_mock_source, is_rtsp_source
from app.camera.subprocess_capture_worker import SubprocessCaptureWorker
from app.core.config import Settings


@dataclass
class CameraRuntime:
    config: CameraSourceConfig
    frame_buffer: FrameBuffer
    worker: CaptureWorker | SubprocessCaptureWorker | MJPEGStreamWorker


class CameraSourceManager:
    def __init__(self, settings: Settings, frame_observer: Callable[[FramePacket], None] | None = None) -> None:
        self.settings = settings
        self._frame_observer = frame_observer
        self._runtimes: dict[str, CameraRuntime] = {}
        self._source_generations: dict[str, int] = {}
        self._lock = threading.Lock()

    def start_source(self, config: CameraSourceConfig) -> tuple[CameraRuntime, bool]:
        with self._lock:
            existing = self._runtimes.get(config.camera_id)
            if existing:
                if not existing.worker.status().running:
                    self._runtimes.pop(config.camera_id, None)
                    try:
                        existing.worker.stop()
                    except Exception:
                        pass
                    existing = None
            if existing:
                if existing.config.source_url != config.source_url:
                    raise ValueError(
                        f"camera {config.camera_id} is already running with another source"
                    )
                return existing, False
            generation = self._source_generations.get(config.camera_id, 0) + 1
            self._source_generations[config.camera_id] = generation
            buffer = FrameBuffer(
                config.camera_id,
                source=_source_kind(config.source_url),
                source_generation=generation,
            )
            worker = self._create_worker(config, buffer)
            runtime = CameraRuntime(config=config, frame_buffer=buffer, worker=worker)
            self._runtimes[config.camera_id] = runtime
            worker.start()
            return runtime, True

    def stop_source(self, camera_id: str) -> bool:
        with self._lock:
            runtime = self._runtimes.pop(camera_id, None)
        if not runtime:
            return False
        runtime.worker.stop()
        return True

    def get_runtime(self, camera_id: str) -> CameraRuntime | None:
        with self._lock:
            return self._runtimes.get(camera_id)

    def get_buffer(self, camera_id: str) -> FrameBuffer | None:
        runtime = self.get_runtime(camera_id)
        return runtime.frame_buffer if runtime else None

    def get_main_buffer(self, camera_id: str) -> FrameBuffer | None:
        return self.get_buffer(camera_id)

    def get_analysis_buffer(self, camera_id: str) -> FrameBuffer | None:
        return self.get_buffer(camera_id)

    def display_state(self, camera_id: str) -> tuple[str, bool]:
        runtime = self.get_runtime(camera_id)
        if runtime is None:
            return "none", False
        return "single", False

    def list_runtimes(self) -> list[CameraRuntime]:
        with self._lock:
            return list(self._runtimes.values())

    def worker_status(self, camera_id: str) -> CaptureWorkerStatus | None:
        runtime = self.get_runtime(camera_id)
        return runtime.worker.status() if runtime else None

    def set_mock_fault(self, camera_id: str, mode: str) -> str:
        runtime = self.get_runtime(camera_id)
        if runtime is None:
            raise ValueError(f"camera is not running: {camera_id}")
        worker = runtime.worker
        if not hasattr(worker, "set_mock_fault"):
            raise ValueError("mock fault injection is unavailable for this worker")
        return worker.set_mock_fault(mode)  # type: ignore[attr-defined]

    def stop_all(self) -> None:
        for runtime in self.list_runtimes():
            runtime.worker.stop()
        with self._lock:
            self._runtimes.clear()

    def _create_worker(
        self,
        config: CameraSourceConfig,
        buffer: FrameBuffer,
    ) -> CaptureWorker | SubprocessCaptureWorker | MJPEGStreamWorker:
        if is_mjpeg_source(config.source_url):
            return MJPEGStreamWorker(config, buffer, self.settings, self._frame_observer)
        if is_local_file_source(config.source_url):
            return CaptureWorker(config, buffer, self.settings, self._frame_observer)
        if (
            self.settings.capture_backend in {"subprocess_opencv", "subprocess_pyav"}
            and not config.source_url.startswith("mock://")
        ):
            return SubprocessCaptureWorker(config, buffer, self.settings, self._frame_observer)
        return CaptureWorker(config, buffer, self.settings, self._frame_observer)


def _source_kind(source_url: str | None) -> str:
    if is_mock_source(source_url):
        return "mock"
    if is_rtsp_source(source_url):
        return "rtsp"
    if is_mjpeg_source(source_url):
        return "mjpeg"
    if is_local_file_source(source_url):
        return "file"
    return "unknown"
