from __future__ import annotations

import queue
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.camera.source_manager import CameraSourceManager
from app.core.config import Settings
from app.core.logger import get_logger
from app.post_fall_v2.fall_binary_classifier_service import FallBinaryClassifierService
from app.post_fall_v2.fall_shadow_evidence_service import FallShadowEvidenceService
from app.post_fall_v2.frame_sampler_service import FrameSamplerService
from app.post_fall_v2.schemas import FULL_FRAME_TRAIN_MATCHED, SampledFrame

logger = get_logger(__name__)


@dataclass
class ShadowBinaryStatus:
    camera_id: str | None
    enabled: bool
    running: bool
    state: str
    model_loaded: bool
    model_hash_verified: bool
    model_sha256: str | None
    provider: str | None
    sample_fps: float
    input_policy: str
    queue_depth: int
    frames_sampled: int
    frames_processed: int
    frames_dropped: int
    frames_invalid: int
    last_frame_id: str | None
    last_probability: float | None
    last_inference_ms: float | None
    last_total_ms: float | None
    records_written: int
    last_error: str | None


@dataclass
class _CameraShadowState:
    sampler_thread: threading.Thread
    worker_thread: threading.Thread
    stop_event: threading.Event
    queue: queue.Queue[SampledFrame]
    sampler: FrameSamplerService
    frames_sampled: int = 0
    frames_processed: int = 0
    frames_dropped: int = 0
    frames_invalid: int = 0
    last_frame_id: str | None = None
    last_probability: float | None = None
    last_inference_ms: float | None = None
    last_total_ms: float | None = None
    last_error: str | None = None


class FallBinaryShadowService:
    def __init__(self, *, settings: Settings, source_manager: CameraSourceManager) -> None:
        self.settings = settings
        self.source_manager = source_manager
        self.enabled = bool(settings.post_fall_v2_shadow_enabled)
        self.input_policy = settings.post_fall_v2_input_policy
        self._classifier: FallBinaryClassifierService | None = None
        self._recorder = FallShadowEvidenceService(
            output_dir=settings.post_fall_v2_shadow_output_dir,
            save_metadata=settings.post_fall_v2_shadow_save_results,
            save_frames=settings.post_fall_v2_shadow_save_frames,
            save_frame_probability_threshold=settings.post_fall_v2_shadow_save_frame_probability_threshold,
            save_max_frames_per_minute=settings.post_fall_v2_shadow_save_max_frames_per_minute,
        )
        self._states: dict[str, _CameraShadowState] = {}
        self._lock = threading.Lock()
        self._startup_error: str | None = None
        if self.enabled:
            self._load_classifier_safely()

    def _load_classifier_safely(self) -> None:
        if self.input_policy != FULL_FRAME_TRAIN_MATCHED:
            self._startup_error = f"unsupported input policy for P2 shadow: {self.input_policy}"
            logger.error("post_fall_v2_shadow_unavailable reason=%s", self._startup_error)
            return
        try:
            self._classifier = FallBinaryClassifierService(
                model_path=self._resolve_path(self.settings.post_fall_v2_binary_model_path),
                expected_sha256=self.settings.post_fall_v2_binary_model_sha256,
                threshold=self.settings.post_fall_v2_binary_candidate_threshold,
                input_policy=self.input_policy,
                providers=[
                    part.strip()
                    for part in self.settings.post_fall_v2_binary_onnx_providers.split(",")
                    if part.strip()
                ],
            )
            self._startup_error = None
        except Exception as exc:
            self._classifier = None
            self._startup_error = str(exc)
            logger.exception("post_fall_v2_shadow_classifier_load_failed")

    def start_for_camera(self, camera_id: str) -> None:
        if not self.enabled or self._classifier is None:
            return
        with self._lock:
            existing = self._states.get(camera_id)
            if existing and existing.worker_thread.is_alive():
                return
            stop_event = threading.Event()
            frame_queue: queue.Queue[SampledFrame] = queue.Queue(
                maxsize=max(1, int(self.settings.post_fall_v2_shadow_queue_size))
            )
            sampler = FrameSamplerService(
                sample_fps=self.settings.post_fall_v2_shadow_sample_fps,
                max_frame_age_ms=self.settings.post_fall_v2_shadow_max_frame_age_ms,
            )
            state = _CameraShadowState(
                sampler_thread=threading.Thread(
                    target=self._sample_loop,
                    args=(camera_id, stop_event, frame_queue, sampler),
                    name=f"post-fall-v2-shadow-sampler-{camera_id}",
                    daemon=True,
                ),
                worker_thread=threading.Thread(
                    target=self._worker_loop,
                    args=(camera_id, stop_event, frame_queue),
                    name=f"post-fall-v2-shadow-worker-{camera_id}",
                    daemon=True,
                ),
                stop_event=stop_event,
                queue=frame_queue,
                sampler=sampler,
            )
            self._states[camera_id] = state
            state.sampler_thread.start()
            state.worker_thread.start()
            logger.info("post_fall_v2_shadow_started camera_id=%s", camera_id)

    def stop_for_camera(self, camera_id: str) -> None:
        with self._lock:
            state = self._states.pop(camera_id, None)
        if state is None:
            return
        state.stop_event.set()
        for worker in (state.sampler_thread, state.worker_thread):
            if worker.is_alive():
                worker.join(timeout=3)
        logger.info("post_fall_v2_shadow_stopped camera_id=%s", camera_id)

    def stop_all(self) -> None:
        for camera_id in list(self._states.keys()):
            self.stop_for_camera(camera_id)

    def status(self, camera_id: str | None = None) -> dict:
        with self._lock:
            selected = self._states.get(camera_id) if camera_id else next(iter(self._states.values()), None)
            selected_camera_id = camera_id or (next(iter(self._states.keys()), None) if self._states else None)
        running = bool(selected and selected.worker_thread.is_alive() and selected.sampler_thread.is_alive())
        classifier = self._classifier
        model_hash_verified = bool(
            classifier
            and classifier.model_sha256
            and classifier.model_sha256.lower() == self.settings.post_fall_v2_binary_model_sha256.lower()
        )
        state = "disabled"
        last_error = self._startup_error or self._recorder.last_error
        if self.enabled:
            if classifier is None:
                state = "unavailable"
            elif not running and selected_camera_id is not None:
                state = "stopped"
            elif last_error:
                state = "degraded"
            elif running:
                state = "healthy"
            else:
                state = "idle"
        status = ShadowBinaryStatus(
            camera_id=selected_camera_id,
            enabled=self.enabled,
            running=running,
            state=state,
            model_loaded=bool(classifier and classifier.loaded),
            model_hash_verified=model_hash_verified,
            model_sha256=classifier.model_sha256 if classifier else None,
            provider=classifier.provider if classifier else None,
            sample_fps=self.settings.post_fall_v2_shadow_sample_fps,
            input_policy=self.input_policy,
            queue_depth=selected.queue.qsize() if selected else 0,
            frames_sampled=selected.frames_sampled if selected else 0,
            frames_processed=selected.frames_processed if selected else 0,
            frames_dropped=selected.frames_dropped if selected else 0,
            frames_invalid=selected.frames_invalid if selected else 0,
            last_frame_id=selected.last_frame_id if selected else None,
            last_probability=selected.last_probability if selected else None,
            last_inference_ms=selected.last_inference_ms if selected else None,
            last_total_ms=selected.last_total_ms if selected else None,
            records_written=self._recorder.records_written,
            last_error=last_error,
        )
        return asdict(status)

    def _sample_loop(
        self,
        camera_id: str,
        stop_event: threading.Event,
        frame_queue: queue.Queue[SampledFrame],
        sampler: FrameSamplerService,
    ) -> None:
        tick_interval = min(0.05, 1.0 / max(self.settings.post_fall_v2_shadow_sample_fps * 4, 1.0))
        while not stop_event.is_set():
            try:
                buffer = self.source_manager.get_buffer(camera_id)
                decision = sampler.try_sample(buffer.latest() if buffer else None)
                if decision.sampled is not None:
                    self._put_latest(camera_id, frame_queue, decision.sampled)
            except Exception as exc:
                self._set_error(camera_id, str(exc))
                logger.exception("post_fall_v2_shadow_sampler_error camera_id=%s", camera_id)
            stop_event.wait(tick_interval)

    def _worker_loop(
        self,
        camera_id: str,
        stop_event: threading.Event,
        frame_queue: queue.Queue[SampledFrame],
    ) -> None:
        while not stop_event.is_set():
            try:
                sampled = frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                classifier = self._classifier
                if classifier is None:
                    self._set_error(camera_id, "classifier unavailable")
                    continue
                result = classifier.infer(sampled)
                self._recorder.write(result, sampled)
                with self._lock:
                    state = self._states.get(camera_id)
                    if state:
                        state.frames_processed += 1
                        state.last_frame_id = result.frame_id
                        state.last_probability = result.fall_probability
                        state.last_inference_ms = result.performance.inference_ms
                        state.last_total_ms = result.performance.total_ms
                        if not result.valid:
                            state.frames_invalid += 1
                            state.last_error = result.error_message
                        else:
                            state.last_error = None
            except Exception as exc:
                self._set_error(camera_id, str(exc))
                logger.exception("post_fall_v2_shadow_worker_error camera_id=%s", camera_id)

    def _put_latest(self, camera_id: str, frame_queue: queue.Queue[SampledFrame], sampled: SampledFrame) -> None:
        dropped = 0
        while frame_queue.full():
            try:
                frame_queue.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        try:
            frame_queue.put_nowait(sampled)
        except queue.Full:
            dropped += 1
        with self._lock:
            state = self._states.get(camera_id)
            if state:
                state.frames_sampled += 1
                state.frames_dropped += dropped

    def _set_error(self, camera_id: str, message: str) -> None:
        with self._lock:
            state = self._states.get(camera_id)
            if state:
                state.last_error = message

    @staticmethod
    def _resolve_path(path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return Path(__file__).resolve().parents[2] / candidate

