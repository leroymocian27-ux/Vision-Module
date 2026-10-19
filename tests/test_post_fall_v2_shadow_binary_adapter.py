from __future__ import annotations

import json
import queue
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.camera.frame_buffer import FrameBuffer
from app.post_fall_v2.fall_binary_classifier_service import FallBinaryClassifierService
from app.post_fall_v2.fall_binary_shadow_service import FallBinaryShadowService, _CameraShadowState
from app.post_fall_v2.fall_shadow_evidence_service import FallShadowEvidenceService
from app.post_fall_v2.frame_sampler_service import FrameSamplerService
from app.post_fall_v2.schemas import (
    FULL_FRAME_TRAIN_MATCHED,
    BinaryFallResult,
    InputInfo,
    ModelInfo,
    PerformanceInfo,
    SampledFrame,
    ThresholdInfo,
    monotonic_to_utc_iso,
)


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx"
MODEL_SHA256 = "e9871cdb4687055fb5d934dd994c2ad883adac0c2acab375c240f8e005ee04cc"
AUDIT_ROOT = ROOT.parent / "_uploaded_binary_model_audit_20260810_01" / "dog"
FALL_SAMPLE = AUDIT_ROOT / "data/Fall/go2_fall_batch50_3min_20260731_210528_01_20260731_210537_372.jpg"
NOFALL_SAMPLE = AUDIT_ROOT / "data/noFall/go2_01_20260731_201522_156.jpg"


def sampled(frame: np.ndarray, seq: int = 1) -> SampledFrame:
    now = time.monotonic()
    height, width = frame.shape[:2]
    return SampledFrame(
        camera_id="camera_01",
        frame_id=f"camera_01_test_{seq:04d}",
        frame_seq=seq,
        captured_at=monotonic_to_utc_iso(now),
        sampled_at=monotonic_to_utc_iso(now),
        captured_monotonic=now,
        sampled_monotonic=now,
        source_width=int(width),
        source_height=int(height),
        source_generation=1,
        frame=frame,
    )


def read_image_bgr(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def test_frame_sampler_time_based_duplicate_and_stale() -> None:
    buffer = FrameBuffer("camera_01")
    packet = buffer.update(np.zeros((32, 48, 3), dtype=np.uint8))
    sampler = FrameSamplerService(sample_fps=2.0, max_frame_age_ms=1000)

    first = sampler.try_sample(packet, now=10.0)
    second = sampler.try_sample(packet, now=10.6)

    assert first.sampled is not None
    assert second.sampled is None
    assert second.reason == "duplicate_frame"

    old_packet = buffer.update(np.zeros((32, 48, 3), dtype=np.uint8))
    stale = sampler.try_sample(old_packet, now=time.monotonic() + 2.0)
    assert stale.sampled is None
    assert stale.reason == "stale_frame"


def test_classifier_load_hash_and_real_samples() -> None:
    pytest.importorskip("onnxruntime")
    if not FALL_SAMPLE.exists() or not NOFALL_SAMPLE.exists():
        pytest.skip("uploaded Fall/noFall audit samples are not available")
    classifier = FallBinaryClassifierService(
        model_path=MODEL,
        expected_sha256=MODEL_SHA256,
        threshold=0.3979087471961975,
        input_policy=FULL_FRAME_TRAIN_MATCHED,
    )
    fall_frame = read_image_bgr(FALL_SAMPLE)
    nofall_frame = read_image_bgr(NOFALL_SAMPLE)
    assert fall_frame is not None
    assert nofall_frame is not None

    fall_result = classifier.infer(sampled(fall_frame, seq=1))
    nofall_result = classifier.infer(sampled(nofall_frame, seq=2))

    assert classifier.loaded is True
    assert classifier.model_sha256 == MODEL_SHA256
    assert classifier.provider is not None
    assert fall_result.valid is True
    assert nofall_result.valid is True
    assert 0.0 <= fall_result.fall_probability <= 1.0
    assert 0.0 <= nofall_result.fall_probability <= 1.0
    assert fall_result.fall_probability > 0.3979087471961975
    assert nofall_result.fall_probability < 0.3979087471961975
    assert fall_result.shadow_candidate_hint is True
    assert nofall_result.shadow_candidate_hint is False
    assert fall_result.threshold.production_validated is False


def test_classifier_rejects_bad_hash_and_invalid_frame() -> None:
    with pytest.raises(Exception, match="sha256 mismatch"):
        FallBinaryClassifierService(
            model_path=MODEL,
            expected_sha256="0" * 64,
            threshold=0.3979087471961975,
            input_policy=FULL_FRAME_TRAIN_MATCHED,
        )
    pytest.importorskip("onnxruntime")
    classifier = FallBinaryClassifierService(
        model_path=MODEL,
        expected_sha256=MODEL_SHA256,
        threshold=0.3979087471961975,
        input_policy=FULL_FRAME_TRAIN_MATCHED,
    )
    result = classifier.infer(sampled(np.zeros((32, 48), dtype=np.uint8)))

    assert result.valid is False
    assert result.error_code == "BINARY_INFERENCE_ERROR"


def test_evidence_recorder_jsonl_and_directory_failure(tmp_path: Path) -> None:
    recorder = FallShadowEvidenceService(output_dir=tmp_path, save_metadata=True)
    frame = np.zeros((64, 96, 3), dtype=np.uint8)
    result = BinaryFallResult(
        frame_id="camera_01_test_0001",
        camera_id="camera_01",
        captured_at="2026-08-10T00:00:00.000+00:00",
        sampled_at="2026-08-10T00:00:00.000+00:00",
        inferred_at="2026-08-10T00:00:00.010+00:00",
        prediction="noFall",
        class_index=0,
        fall_probability=0.01,
        nofall_probability=0.99,
        shadow_candidate_hint=False,
        threshold=ThresholdInfo(value=0.3979087471961975),
        model=ModelInfo(name="efficientnet_b0_post_fall", format="onnx", sha256=MODEL_SHA256, provider="CPUExecutionProvider"),
        input=InputInfo(policy=FULL_FRAME_TRAIN_MATCHED, source_width=96, source_height=64, model_width=224, model_height=224),
        performance=PerformanceInfo(queue_delay_ms=1.0, preprocess_ms=2.0, inference_ms=3.0, total_ms=6.0),
        valid=True,
    )

    recorder.write(result, sampled(frame))

    path = tmp_path / "shadow_camera_01.jsonl"
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["frame_id"] == result.frame_id
    assert payload["human_label"] is None
    assert payload["scenario_label"] is None
    assert recorder.records_written == 1

    blocking_file = tmp_path / "not_a_dir"
    blocking_file.write_text("x", encoding="utf-8")
    bad_recorder = FallShadowEvidenceService(output_dir=blocking_file, save_metadata=True)
    bad_recorder.write(result, sampled(frame))
    assert bad_recorder.write_errors == 1
    assert bad_recorder.last_error


def test_shadow_queue_latest_wins(tmp_path: Path) -> None:
    settings = shadow_settings(tmp_path, enabled=False)
    service = FallBinaryShadowService(settings=settings, source_manager=SimpleNamespace())
    frame_queue: queue.Queue[SampledFrame] = queue.Queue(maxsize=2)
    stop_event = SimpleNamespace(set=lambda: None)
    dummy_thread = SimpleNamespace(is_alive=lambda: False, join=lambda timeout=None: None)
    state = _CameraShadowState(
        sampler_thread=dummy_thread,
        worker_thread=dummy_thread,
        stop_event=stop_event,
        queue=frame_queue,
        sampler=FrameSamplerService(sample_fps=2, max_frame_age_ms=1000),
    )
    service._states["camera_01"] = state
    for seq in range(1, 5):
        service._put_latest("camera_01", frame_queue, sampled(np.zeros((8, 8, 3), dtype=np.uint8), seq=seq))

    remaining = [frame_queue.get_nowait().frame_seq for _ in range(frame_queue.qsize())]
    assert remaining == [3, 4]
    assert state.frames_dropped == 2


def test_shadow_disabled_and_model_failure_are_isolated(tmp_path: Path) -> None:
    disabled = FallBinaryShadowService(settings=shadow_settings(tmp_path, enabled=False), source_manager=SimpleNamespace())
    disabled.start_for_camera("camera_01")
    assert disabled.status("camera_01")["enabled"] is False
    assert disabled.status("camera_01")["state"] == "disabled"

    bad = FallBinaryShadowService(
        settings=shadow_settings(tmp_path, enabled=True, model_path=str(tmp_path / "missing.onnx")),
        source_manager=SimpleNamespace(),
    )
    bad.start_for_camera("camera_01")
    status = bad.status("camera_01")
    assert status["enabled"] is True
    assert status["state"] == "unavailable"
    assert status["model_loaded"] is False


def shadow_settings(tmp_path: Path, *, enabled: bool, model_path: str | None = None):
    return SimpleNamespace(
        post_fall_v2_shadow_enabled=enabled,
        post_fall_v2_input_policy=FULL_FRAME_TRAIN_MATCHED,
        post_fall_v2_binary_model_path=model_path or str(MODEL),
        post_fall_v2_binary_model_sha256=MODEL_SHA256,
        post_fall_v2_binary_candidate_threshold=0.3979087471961975,
        post_fall_v2_binary_onnx_providers="CPUExecutionProvider",
        post_fall_v2_shadow_output_dir=str(tmp_path),
        post_fall_v2_shadow_save_results=True,
        post_fall_v2_shadow_save_frames=False,
        post_fall_v2_shadow_save_frame_probability_threshold=0.3,
        post_fall_v2_shadow_save_max_frames_per_minute=6,
        post_fall_v2_shadow_queue_size=2,
        post_fall_v2_shadow_sample_fps=2.0,
        post_fall_v2_shadow_max_frame_age_ms=1000,
    )
