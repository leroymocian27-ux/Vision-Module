from __future__ import annotations

import socket
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from app.camera.capture_worker import CaptureWorkerStatus
from app.camera.frame_buffer import FrameBuffer, FramePacket
from app.camera.frame_freshness import FreshnessThresholds, frame_freshness, normalize_camera_state
from app.camera.mjpeg_parser import extract_jpeg_frames, jpeg_dimensions
from app.camera.source_models import CameraSourceConfig
from app.core.config import Settings
from app.core.logger import get_logger
from app.monitoring.metrics import FPSMeter

logger = get_logger(__name__)


@dataclass
class MJPEGStreamStatus:
    content_type: str | None = None
    reconnect_initial_sec: float = 0.5
    reconnect_max_sec: float = 5.0
    last_chunk_bytes: int = 0
    parsed_frames: int = 0
    received_frames: int = 0
    published_frames: int = 0
    dropped_frames: int = 0
    inter_frame_ms: float | None = None
    inter_frame_max_ms: float | None = None
    publish_latency_ms: float | None = None
    publish_latency_max_ms: float | None = None


class MJPEGStreamWorker:
    """Low-latency HTTP MJPEG worker that stores latest raw JPEG bytes."""

    def __init__(
        self,
        config: CameraSourceConfig,
        frame_buffer: FrameBuffer,
        settings: Settings,
        frame_observer: Callable[[FramePacket], None] | None = None,
    ) -> None:
        self.config = config
        self.frame_buffer = frame_buffer
        self.settings = settings
        self._frame_observer = frame_observer
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = CaptureWorkerStatus(capture_backend="mjpeg_http")
        self._mjpeg_status = MJPEGStreamStatus(
            reconnect_initial_sec=settings.mjpeg_reconnect_initial_sec,
            reconnect_max_sec=settings.mjpeg_reconnect_max_sec,
        )
        self._fps = FPSMeter()
        self._receive_fps = FPSMeter()
        self._lock = threading.Lock()
        self._latest_condition = threading.Condition()
        self._latest_jpeg: tuple[int, bytes, float] | None = None
        self._network_seq = 0
        self._publisher_thread: threading.Thread | None = None
        self._last_received_at: float | None = None
        self._reconnect_delay = max(0.05, float(settings.mjpeg_reconnect_initial_sec))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"capture-mjpeg-{self.config.camera_id}",
            daemon=True,
        )
        self._publisher_thread = threading.Thread(
            target=self._publish_loop,
            name=f"capture-mjpeg-publisher-{self.config.camera_id}",
            daemon=True,
        )
        self._publisher_thread.start()
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._latest_condition:
            self._latest_condition.notify_all()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(1.0, float(self.settings.mjpeg_read_timeout_sec) + 0.5))
        if self._publisher_thread and self._publisher_thread.is_alive():
            self._publisher_thread.join(timeout=1.0)
        with self._lock:
            self._status.running = False
            self._status.connected = False
            self._status.stream_state = "disconnected"

    def status(self) -> CaptureWorkerStatus:
        packet = self.frame_buffer.latest()
        with self._lock:
            status = CaptureWorkerStatus(**self._status.__dict__)
        if packet:
            status.frame_seq = packet.seq
            status.frame_width = packet.width
            status.frame_height = packet.height
            status.frame_age_ms = packet.age_ms
            status.last_frame_at = packet.captured_at_iso
            status.received_at = packet.received_at_iso
            status.source = packet.source
            status.source_protocol = "mjpeg"
            status.source_generation = packet.source_generation
            status.raw_jpeg_available = packet.jpeg_bytes is not None
        else:
            status.source = self.frame_buffer.source
            status.source_protocol = "mjpeg"
            status.source_generation = self.frame_buffer.source_generation
        thresholds = FreshnessThresholds(
            delayed_ms=self.settings.frame_delayed_threshold_ms,
            stale_ms=self.settings.mjpeg_stale_frame_ms,
        )
        freshness = frame_freshness(status.frame_age_ms, thresholds)
        status.frame_status = freshness.frame_status
        status.is_stale = freshness.is_stale
        status.safe_to_interpret_as_no_fall = freshness.safe_to_interpret_as_no_fall
        status.stream_state = normalize_camera_state(
            running=status.running,
            connected=status.connected,
            internal_state=status.stream_state,
            frame_status=status.frame_status,
            last_error=status.last_error,
            reconnect_reason=status.reconnect_reason,
        )
        status.capture_fps = self._fps.fps
        status.mjpeg_content_type = self._mjpeg_status.content_type
        status.mjpeg_parsed_frames = self._mjpeg_status.parsed_frames
        status.mjpeg_received_frames = self._mjpeg_status.received_frames
        status.mjpeg_published_frames = self._mjpeg_status.published_frames
        status.mjpeg_dropped_frames = self._mjpeg_status.dropped_frames
        status.mjpeg_receive_fps = self._receive_fps.fps
        status.mjpeg_publish_fps = self._fps.fps
        status.mjpeg_inter_frame_ms = self._mjpeg_status.inter_frame_ms
        status.mjpeg_inter_frame_max_ms = self._mjpeg_status.inter_frame_max_ms
        status.mjpeg_publish_latency_ms = self._mjpeg_status.publish_latency_ms
        status.mjpeg_publish_latency_max_ms = self._mjpeg_status.publish_latency_max_ms
        return status

    def _run(self) -> None:
        with self._lock:
            self._status.running = True
            self._status.stream_state = "connecting"
            self._status.last_error = None
            self._status.reconnect_reason = None
        while not self._stop_event.is_set():
            try:
                self._read_stream_once()
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                self._schedule_reconnect(str(exc))
        with self._lock:
            self._status.running = False
            self._status.connected = False
            self._status.stream_state = "disconnected"

    def _read_stream_once(self) -> None:
        request = urllib.request.Request(
            self.config.source_url,
            headers={"User-Agent": "camera-service-mjpeg/1.0", "Accept": "multipart/x-mixed-replace,image/jpeg,*/*"},
        )
        with self._lock:
            self._status.stream_state = "connecting"
            self._status.reconnect_reason = None
        started = time.monotonic()
        with urllib.request.urlopen(
            request,
            timeout=max(0.1, float(self.settings.mjpeg_connect_timeout_sec)),
        ) as response:
            _set_response_timeout(response, max(0.1, float(self.settings.mjpeg_read_timeout_sec)))
            content_type = response.headers.get("Content-Type")
            with self._lock:
                self._mjpeg_status.content_type = content_type
                self._status.last_read_started_at = _utc_now_iso()
            self._reconnect_delay = max(0.05, float(self.settings.mjpeg_reconnect_initial_sec))
            logger.info(
                "mjpeg_connected camera_id=%s content_type=%s open_ms=%.2f",
                self.config.camera_id,
                content_type,
                (time.monotonic() - started) * 1000,
            )
            buffer = b""
            last_complete_frame_at = time.monotonic()
            while not self._stop_event.is_set():
                read_started = time.monotonic()
                try:
                    chunk = response.read(max(1024, int(self.settings.mjpeg_chunk_bytes)))
                except socket.timeout as exc:
                    with self._lock:
                        self._status.read_timeout_count += 1
                        self._status.consecutive_slow_reads += 1
                    raise TimeoutError("mjpeg read timeout") from exc
                read_latency_ms = (time.monotonic() - read_started) * 1000
                if not chunk:
                    raise EOFError("mjpeg stream closed")
                with self._lock:
                    self._status.last_read_started_at = _utc_now_iso()
                    self._status.read_latency_ms = round(read_latency_ms, 2)
                    self._status.read_latency_max_ms = round(
                        max(read_latency_ms, self._status.read_latency_max_ms or 0.0),
                        2,
                    )
                    self._status.last_read_completed_at = _utc_now_iso()
                    self._status.consecutive_slow_reads = 0
                    self._mjpeg_status.last_chunk_bytes = len(chunk)
                buffer += chunk
                frames, buffer = extract_jpeg_frames(buffer, max_buffer_bytes=self.settings.mjpeg_max_buffer_bytes)
                if frames:
                    last_complete_frame_at = time.monotonic()
                    for jpeg in frames:
                        self._queue_jpeg(jpeg)
                else:
                    self._raise_if_complete_frame_stale(last_complete_frame_at)

    def _queue_jpeg(self, jpeg_bytes: bytes) -> None:
        now = time.monotonic()
        with self._lock:
            if self._last_received_at is not None:
                interval_ms = (now - self._last_received_at) * 1000
                self._mjpeg_status.inter_frame_ms = round(interval_ms, 2)
                self._mjpeg_status.inter_frame_max_ms = round(
                    max(interval_ms, self._mjpeg_status.inter_frame_max_ms or 0.0),
                    2,
                )
            self._last_received_at = now
            self._network_seq += 1
            compressed_seq = self._network_seq
            self._mjpeg_status.received_frames += 1
            self._mjpeg_status.parsed_frames = self._mjpeg_status.received_frames
            self._receive_fps.tick()
        with self._latest_condition:
            if self._latest_jpeg is not None:
                with self._lock:
                    self._mjpeg_status.dropped_frames += 1
                    self._status.capture_ipc_dropped_frames += 1
            self._latest_jpeg = (compressed_seq, jpeg_bytes, now)
            self._latest_condition.notify()

    def _publish_loop(self) -> None:
        while not self._stop_event.is_set():
            item = self._pop_latest_jpeg()
            if item is None:
                continue
            compressed_seq, jpeg_bytes, received_at = item
            self._publish_jpeg(jpeg_bytes, compressed_seq=compressed_seq, received_at=received_at)

    def _pop_latest_jpeg(self) -> tuple[int, bytes, float] | None:
        with self._latest_condition:
            while self._latest_jpeg is None and not self._stop_event.is_set():
                self._latest_condition.wait(timeout=0.25)
            if self._latest_jpeg is None:
                return None
            item = self._latest_jpeg
            self._latest_jpeg = None
            return item

    def _publish_jpeg(self, jpeg_bytes: bytes, *, compressed_seq: int | None = None, received_at: float | None = None) -> None:
        started = time.monotonic()
        width, height = jpeg_dimensions(jpeg_bytes)
        packet = self.frame_buffer.update_jpeg(
            jpeg_bytes,
            width=width,
            height=height,
            captured_at=received_at,
            received_at=received_at,
        )
        self._notify_frame_observer(packet)
        self._fps.tick()
        publish_latency_ms = (time.monotonic() - started) * 1000
        with self._lock:
            self._status.connected = True
            self._status.stream_state = "connected"
            self._status.frame_seq = packet.seq
            self._status.frame_width = packet.width
            self._status.frame_height = packet.height
            self._status.frame_age_ms = packet.age_ms
            self._status.last_frame_at = packet.captured_at_iso
            self._status.received_at = packet.received_at_iso
            self._status.last_error = None
            self._status.reconnect_reason = None
            self._mjpeg_status.published_frames += 1
            self._mjpeg_status.publish_latency_ms = round(publish_latency_ms, 2)
            self._mjpeg_status.publish_latency_max_ms = round(
                max(publish_latency_ms, self._mjpeg_status.publish_latency_max_ms or 0.0),
                2,
            )

    def _notify_frame_observer(self, packet: FramePacket) -> None:
        if self._frame_observer is None:
            return
        try:
            self._frame_observer(packet)
        except Exception:
            logger.exception("capture_frame_observer_failed camera_id=%s", self.config.camera_id)

    def _raise_if_complete_frame_stale(self, last_complete_frame_at: float) -> None:
        stale_ms = max(
            1.0,
            float(self.settings.mjpeg_stale_frame_ms),
            float(self.settings.mjpeg_read_timeout_sec) * 1000.0,
        )
        elapsed_ms = (time.monotonic() - last_complete_frame_at) * 1000
        if elapsed_ms <= stale_ms:
            return
        message = f"complete frame stale for {elapsed_ms:.0f}ms"
        with self._lock:
            self._status.stale_count += 1
            self._status.read_timeout_count += 1
            self._status.consecutive_slow_reads += 1
            self._status.stream_state = "stale"
            self._status.reconnect_reason = "mjpeg_complete_frame_stale"
            self._status.last_error = message
        raise TimeoutError(message)

    def _schedule_reconnect(self, message: str) -> None:
        delay = min(float(self.settings.mjpeg_reconnect_max_sec), self._reconnect_delay)
        with self._lock:
            self._status.connected = False
            self._status.stream_state = "reconnecting"
            self._status.reconnect_reason = "mjpeg_reconnect"
            self._status.reconnect_count += 1
            self._status.last_error = message
        logger.warning(
            "mjpeg_reconnect_scheduled camera_id=%s delay_sec=%.2f error=%s",
            self.config.camera_id,
            delay,
            message,
        )
        self._stop_event.wait(delay)
        self._reconnect_delay = min(float(self.settings.mjpeg_reconnect_max_sec), max(delay * 2, delay + 0.1))


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _set_response_timeout(response, timeout_sec: float) -> None:
    try:
        sock = response.fp.raw._sock
        sock.settimeout(timeout_sec)
    except Exception:
        return
