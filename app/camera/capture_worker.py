from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from app.camera.frame_buffer import FrameBuffer, FramePacket
from app.camera.frame_freshness import FreshnessThresholds, frame_freshness, normalize_camera_state
from app.camera.reconnect_policy import ReconnectPolicy
from app.camera.source_models import CameraSourceConfig, is_local_file_source, is_mock_source
from app.core.config import Settings
from app.core.logger import get_logger
from app.monitoring.metrics import FPSMeter

logger = get_logger(__name__)


@dataclass
class CaptureWorkerStatus:
    running: bool = False
    connected: bool = False
    stream_state: str = "disconnected"
    frame_seq: int = 0
    frame_width: int | None = None
    frame_height: int | None = None
    frame_age_ms: float | None = None
    last_frame_at: str | None = None
    received_at: str | None = None
    source: str = "unknown"
    source_protocol: str = "unknown"
    source_generation: int = 1
    raw_jpeg_available: bool = False
    frame_status: str = "no_frame"
    is_stale: bool = False
    safe_to_interpret_as_no_fall: bool = False
    capture_fps: float = 0.0
    reconnect_count: int = 0
    read_latency_ms: float | None = None
    read_latency_max_ms: float | None = None
    read_timeout_count: int = 0
    stale_count: int = 0
    last_read_started_at: str | None = None
    last_read_completed_at: str | None = None
    consecutive_slow_reads: int = 0
    reconnect_reason: str | None = None
    capture_backend: str = "opencv"
    capture_process_alive: bool = False
    capture_process_pid: int | None = None
    capture_process_restart_count: int = 0
    capture_process_last_frame_age_ms: float | None = None
    capture_process_last_error: str | None = None
    capture_process_last_exit_code: int | None = None
    capture_ipc_decode_errors: int = 0
    capture_ipc_dropped_frames: int = 0
    capture_output_width: int | None = None
    capture_output_height: int | None = None
    mjpeg_content_type: str | None = None
    mjpeg_parsed_frames: int = 0
    mjpeg_received_frames: int = 0
    mjpeg_published_frames: int = 0
    mjpeg_dropped_frames: int = 0
    mjpeg_receive_fps: float = 0.0
    mjpeg_publish_fps: float = 0.0
    mjpeg_inter_frame_ms: float | None = None
    mjpeg_inter_frame_max_ms: float | None = None
    mjpeg_publish_latency_ms: float | None = None
    mjpeg_publish_latency_max_ms: float | None = None
    last_error: str | None = None


class CaptureWorker:
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
        self._status = CaptureWorkerStatus()
        self._fps = FPSMeter()
        self._lock = threading.Lock()
        self._policy = ReconnectPolicy(
            initial_delay_sec=settings.reconnect_initial_delay_sec,
            max_delay_sec=settings.reconnect_max_delay_sec,
            schedule_sec=_parse_backoff_schedule(settings.reconnect_backoff_schedule_sec),
        )
        self._stale_since: float | None = None
        self._was_reconnecting = False
        self._active_capture = None
        self._active_capture_lock = threading.Lock()
        self._read_watchdog_event = threading.Event()
        self._mock_fault_mode = "normal"
        self._mock_fault_lock = threading.Lock()
        self._mock_fault_event = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"capture-{self.config.camera_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
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
            status.source_protocol = packet.source
            status.source_generation = packet.source_generation
            status.raw_jpeg_available = packet.jpeg_bytes is not None
        else:
            status.source = self.frame_buffer.source
            status.source_protocol = self.frame_buffer.source
            status.source_generation = self.frame_buffer.source_generation
        thresholds = FreshnessThresholds(
            delayed_ms=self.settings.frame_delayed_threshold_ms,
            stale_ms=self.settings.stream_stale_threshold_ms,
        )
        freshness = frame_freshness(status.frame_age_ms, thresholds)
        status.frame_status = freshness.frame_status
        status.is_stale = freshness.is_stale
        status.safe_to_interpret_as_no_fall = freshness.safe_to_interpret_as_no_fall
        status.stream_state = self._derive_stream_state(status)
        status.capture_fps = self._fps.fps
        return status

    def set_mock_fault(self, mode: str) -> str:
        if not is_mock_source(self.config.source_url):
            raise ValueError("mock fault injection is only available for mock sources")
        normalized = mode.strip().lower()
        if normalized == "resume":
            normalized = "normal"
        if normalized not in {"normal", "pause", "delay", "freeze", "stop", "decode_error"}:
            raise ValueError(f"unsupported mock fault mode: {mode}")
        with self._mock_fault_lock:
            self._mock_fault_mode = normalized
        self._mock_fault_event.set()
        if normalized == "stop":
            self._stop_event.set()
        return normalized

    def _run(self) -> None:
        with self._lock:
            self._status.running = True
            self._status.stream_state = "connecting"
            self._status.last_error = None
        if is_mock_source(self.config.source_url):
            self._run_mock_camera()
            return
        self._run_video_capture()

    def _run_video_capture(self) -> None:
        try:
            import cv2
        except Exception as exc:
            self._set_error(f"OpenCV import failed: {exc}")
            return

        is_local_file = is_local_file_source(self.config.source_url)
        while not self._stop_event.is_set():
            cap = None
            try:
                self._set_stream_state("connecting")
                self._configure_ffmpeg_capture_options()
                cap = cv2.VideoCapture(self.config.source_url)
                self._set_active_capture(cap)
                self._configure_capture_timeouts(cap)
                if not cap.isOpened():
                    if is_local_file:
                        self._mark_source_unavailable("source open failed")
                        return
                    self._set_reconnect_reason("open_failed")
                    raise RuntimeError("source open failed")
                local_replay_fps = self._local_file_replay_fps(cap) if is_local_file else None
                local_frame_interval = (1.0 / local_replay_fps) if local_replay_fps else None
                next_local_frame_at = time.monotonic()
                self._policy.reset()
                self._set_connected(False)
                self._set_stream_state("connecting")
                if self._was_reconnecting:
                    logger.info(
                        "reconnect_success camera_id=%s",
                        self.config.camera_id,
                    )
                    self._was_reconnecting = False
                logger.info(
                    "camera_connected camera_id=%s",
                    self.config.camera_id,
                )
                if local_replay_fps is not None:
                    logger.info(
                        "local_video_replay_throttle camera_id=%s fps=%.3f",
                        self.config.camera_id,
                        local_replay_fps,
                    )
                while not self._stop_event.is_set():
                    read_started = time.monotonic()
                    self._mark_read_started()
                    watchdog = self._start_read_watchdog(read_started)
                    ok, frame = cap.read()
                    self._stop_read_watchdog(watchdog)
                    read_latency_ms = (time.monotonic() - read_started) * 1000
                    self._mark_read_completed(read_latency_ms)
                    self._raise_if_slow_read_needs_reconnect(read_latency_ms)
                    if not ok or frame is None:
                        if is_local_file:
                            self._mark_source_completed()
                            return
                        self._set_reconnect_reason("read_failed")
                        raise RuntimeError("read frame failed")
                    packet = self.frame_buffer.update(frame)
                    self._notify_frame_observer(packet)
                    self._fps.tick()
                    self._stale_since = None
                    with self._lock:
                        self._status.connected = True
                        self._status.frame_seq = packet.seq
                        self._status.frame_width = packet.width
                        self._status.frame_height = packet.height
                        self._status.frame_age_ms = packet.age_ms
                        self._status.last_frame_at = packet.captured_at_iso
                        self._status.stream_state = "connected"
                        self._status.last_error = None
                    self._raise_if_stale_needs_reconnect(packet)
                    if local_frame_interval is not None:
                        next_local_frame_at += local_frame_interval
                        delay = max(0.0, next_local_frame_at - time.monotonic())
                        if delay > 0:
                            self._stop_event.wait(delay)
            except Exception as exc:
                if not self._current_reconnect_reason():
                    self._set_reconnect_reason("exception")
                self._set_connected(False)
                self._set_stream_state("reconnecting")
                self._was_reconnecting = True
                self._set_error(str(exc))
                delay = self._policy.next_delay()
                with self._lock:
                    self._status.reconnect_count += 1
                logger.warning(
                    "camera_reconnect_scheduled camera_id=%s delay_sec=%.2f error=%s",
                    self.config.camera_id,
                    delay,
                    exc,
                )
                self._stop_event.wait(delay)
            finally:
                self._set_active_capture(None)
                if cap is not None:
                    cap.release()

    def _run_mock_camera(self) -> None:
        try:
            import cv2
        except Exception as exc:
            self._set_error(f"OpenCV import failed: {exc}")
            return

        width = self.settings.mock_camera_width
        height = self.settings.mock_camera_height
        fps = max(1, self.settings.mock_camera_fps)
        frame_interval = 1.0 / fps
        t = 0
        self._set_connected(True)
        self._set_stream_state("connected")
        while not self._stop_event.is_set():
            self._mock_fault_event.clear()
            fault_mode = self._current_mock_fault_mode()
            if fault_mode == "pause":
                self._wait_mock_frame_interval(frame_interval)
                continue
            if fault_mode == "delay":
                self._wait_mock_frame_interval(max(frame_interval * 4, 0.2))
            if fault_mode == "decode_error":
                with self._lock:
                    self._status.last_error = "decode failed"
                    self._status.stream_state = "stale"
                self._wait_mock_frame_interval(frame_interval)
                continue
            if fault_mode == "freeze" and self.frame_buffer.latest() is not None:
                self._wait_mock_frame_interval(frame_interval)
                continue
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:, :] = (20, 26, 32)
            x = int((width - 180) * ((np.sin(t / 20) + 1) / 2))
            y = int(height * 0.35)
            cv2.rectangle(frame, (x, y), (x + 180, y + 300), (60, 180, 130), 3)
            cv2.putText(
                frame,
                f"mock camera {self.config.camera_id}",
                (32, 56),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (230, 240, 240),
                2,
                cv2.LINE_AA,
            )
            if self._current_mock_fault_mode() in {"pause", "freeze", "decode_error", "stop"}:
                continue
            packet = self.frame_buffer.update(frame)
            self._notify_frame_observer(packet)
            self._fps.tick()
            with self._lock:
                self._status.frame_seq = packet.seq
                self._status.frame_width = packet.width
                self._status.frame_height = packet.height
                self._status.frame_age_ms = packet.age_ms
                self._status.last_frame_at = packet.captured_at_iso
                self._status.stream_state = "connected"
                self._status.last_error = None
            t += 1
            self._wait_mock_frame_interval(frame_interval)
        with self._lock:
            self._status.running = False
            self._status.connected = False
            self._status.stream_state = "disconnected"

    def _notify_frame_observer(self, packet: FramePacket) -> None:
        if self._frame_observer is None:
            return
        try:
            self._frame_observer(packet)
        except Exception:
            logger.exception("capture_frame_observer_failed camera_id=%s", self.config.camera_id)

    def _mark_source_completed(self) -> None:
        with self._lock:
            self._status.running = False
            self._status.connected = False
            self._status.stream_state = "disconnected"
            self._status.reconnect_reason = "eof"
            self._status.last_error = None
        logger.info("camera_source_completed camera_id=%s reason=eof", self.config.camera_id)

    def _mark_source_unavailable(self, message: str) -> None:
        with self._lock:
            self._status.running = False
            self._status.connected = False
            self._status.stream_state = "disconnected"
            self._status.reconnect_reason = "open_failed"
            self._status.last_error = message
        logger.error("camera_source_unavailable camera_id=%s error=%s", self.config.camera_id, message)

    def _set_connected(self, connected: bool) -> None:
        with self._lock:
            self._status.connected = connected
            if not connected and self._status.stream_state != "reconnecting":
                self._status.stream_state = "disconnected"

    def _set_stream_state(self, stream_state: str) -> None:
        with self._lock:
            self._status.stream_state = stream_state

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._status.last_error = message
        logger.error("camera_error camera_id=%s error=%s", self.config.camera_id, message)

    def _set_reconnect_reason(self, reason: str) -> None:
        with self._lock:
            self._status.reconnect_reason = reason

    def _current_reconnect_reason(self) -> str | None:
        with self._lock:
            return self._status.reconnect_reason

    def _derive_stream_state(self, status: CaptureWorkerStatus) -> str:
        if (
            not status.running
            and not status.connected
            and status.reconnect_reason == "eof"
            and status.stream_state == "disconnected"
        ):
            return "disconnected"
        return normalize_camera_state(
            running=status.running,
            connected=status.connected,
            internal_state=status.stream_state,
            frame_status=status.frame_status,
            last_error=status.last_error,
            reconnect_reason=status.reconnect_reason,
        )

    def _current_mock_fault_mode(self) -> str:
        with self._mock_fault_lock:
            return self._mock_fault_mode

    def _wait_mock_frame_interval(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while not self._stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if self._mock_fault_event.wait(min(remaining, 0.05)):
                return

    def _raise_if_stale_needs_reconnect(self, packet) -> None:
        age_ms = packet.age_ms
        if age_ms <= self.settings.stream_stale_threshold_ms:
            self._stale_since = None
            return

        now = time.monotonic()
        if self._stale_since is None:
            self._stale_since = now
            self._set_stream_state("stale")
            with self._lock:
                self._status.stale_count += 1
            logger.warning(
                "stale_detected camera_id=%s frame_age_ms=%.2f threshold_ms=%s",
                self.config.camera_id,
                age_ms,
                self.settings.stream_stale_threshold_ms,
            )
            return

        stale_duration_ms = (now - self._stale_since) * 1000
        if stale_duration_ms > self.settings.stream_stale_reconnect_after_ms:
            self._set_reconnect_reason("stale_frame")
            logger.warning(
                "watchdog_reconnect camera_id=%s frame_age_ms=%.2f stale_duration_ms=%.2f",
                self.config.camera_id,
                age_ms,
                stale_duration_ms,
            )
            raise RuntimeError("stale watchdog triggered reconnect")

    def _configure_capture_timeouts(self, cap) -> None:
        try:
            import cv2

            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.settings.stream_stale_threshold_ms)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.settings.stream_stale_threshold_ms)
            if self.settings.opencv_capture_buffersize > 0:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, self.settings.opencv_capture_buffersize)
        except Exception:
            logger.debug(
                "capture_timeout_config_unsupported camera_id=%s",
                self.config.camera_id,
            )

    def _configure_ffmpeg_capture_options(self) -> None:
        options = self.settings.opencv_ffmpeg_capture_options.strip()
        if not options:
            return
        previous = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
        if previous == options:
            return
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = options
        logger.info(
            "opencv_ffmpeg_capture_options_set camera_id=%s options=%s",
            self.config.camera_id,
            options,
        )

    def _set_active_capture(self, cap) -> None:
        with self._active_capture_lock:
            self._active_capture = cap

    def _start_read_watchdog(self, started: float) -> threading.Thread | None:
        threshold_ms = self.settings.capture_read_stale_ms
        if threshold_ms <= 0 or not self.settings.capture_read_watchdog_release_enabled:
            return None
        self._read_watchdog_event.clear()
        watchdog = threading.Thread(
            target=self._read_watchdog,
            args=(started, threshold_ms),
            name=f"capture-read-watchdog-{self.config.camera_id}",
            daemon=True,
        )
        watchdog.start()
        return watchdog

    def _stop_read_watchdog(self, watchdog: threading.Thread | None) -> None:
        self._read_watchdog_event.set()
        if watchdog and watchdog.is_alive():
            watchdog.join(timeout=0.05)

    def _read_watchdog(self, started: float, threshold_ms: int) -> None:
        if self._read_watchdog_event.wait(threshold_ms / 1000):
            return
        elapsed_ms = (time.monotonic() - started) * 1000
        self._set_reconnect_reason("read_watchdog")
        with self._lock:
            self._status.read_timeout_count += 1
            self._status.consecutive_slow_reads += 1
        logger.warning(
            "capture_read_watchdog_release camera_id=%s elapsed_ms=%.2f threshold_ms=%s",
            self.config.camera_id,
            elapsed_ms,
            threshold_ms,
        )
        with self._active_capture_lock:
            cap = self._active_capture
        if cap is not None:
            try:
                cap.release()
            except Exception as exc:
                logger.debug(
                    "capture_read_watchdog_release_failed camera_id=%s error=%s",
                    self.config.camera_id,
                    exc,
                )

    @staticmethod
    def _local_file_replay_fps(cap) -> float:
        try:
            import cv2

            raw_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        except Exception:
            raw_fps = 0.0
        if raw_fps <= 0.0 or raw_fps > 240.0:
            return 10.0
        return raw_fps

    def _mark_read_started(self) -> None:
        with self._lock:
            self._status.last_read_started_at = datetime.now(timezone.utc).isoformat()

    def _mark_read_completed(self, latency_ms: float) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._status.read_latency_ms = round(latency_ms, 2)
            self._status.read_latency_max_ms = round(
                max(latency_ms, self._status.read_latency_max_ms or 0.0),
                2,
            )
            self._status.last_read_completed_at = now
            if latency_ms >= self.settings.capture_read_warn_ms:
                self._status.read_timeout_count += 1
                self._status.consecutive_slow_reads += 1
                consecutive = self._status.consecutive_slow_reads
            else:
                self._status.consecutive_slow_reads = 0
                consecutive = 0
        if latency_ms >= self.settings.capture_read_warn_ms:
            logger.warning(
                "capture_slow_read camera_id=%s latency_ms=%.2f consecutive=%s",
                self.config.camera_id,
                latency_ms,
                consecutive,
            )

    def _raise_if_slow_read_needs_reconnect(self, latency_ms: float) -> None:
        with self._lock:
            consecutive = self._status.consecutive_slow_reads
        if latency_ms >= self.settings.capture_read_stale_ms:
            self._set_reconnect_reason("slow_read")
            raise RuntimeError(f"slow read triggered reconnect: {latency_ms:.2f}ms")
        if (
            self.settings.capture_force_reopen_after_slow_reads > 0
            and consecutive >= self.settings.capture_force_reopen_after_slow_reads
        ):
            self._set_reconnect_reason("slow_read_sequence")
            raise RuntimeError(f"consecutive slow reads triggered reconnect: {consecutive}")


def _parse_backoff_schedule(value: str) -> tuple[float, ...]:
    parts: list[float] = []
    for raw in (value or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = float(raw)
        except ValueError:
            return ()
        if parsed <= 0:
            return ()
        parts.append(parsed)
    return tuple(parts)
