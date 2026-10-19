from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.camera.source_manager import CameraSourceManager
from app.camera.source_models import CameraSourceConfig
from app.core.config import Settings
from app.detection.realtime_result_store import RealtimeResultStore
from app.events.qwen_keyframe import QwenKeyframeAnalyzer
from app.post_fall_v2.post_fall_runtime_service import PostFallV2RuntimeService
from app.post_fall_v2.qwen_fall_analyzer import PFV2QwenFallAnalyzer
from app.post_fall_v2.test_archive_service import PostFallTestArchiveService
from app.post_fall_v2.vlm_review_service import VLMReviewService
from app.streaming.result_channel_manager import ResultChannelManager

VIDEO_DIR = Path(r"C:\Users\YANG\Desktop\视频")
OUTPUT_ROOT = PROJECT_ROOT.parent / "event" / "video_batch_tests"
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
OLLAMA_ENDPOINT = "http://127.0.0.1:11434/api/chat"
_DLL_DIRECTORY_HANDLES: list[object] = []


def preload_torch_cuda_dlls() -> None:
    if not hasattr(os, "add_dll_directory"):
        return
    try:
        import torch
    except Exception:
        return
    torch_lib = Path(torch.__file__).resolve().parent / "lib"
    if torch_lib.is_dir():
        _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(torch_lib)))


def main() -> int:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = OUTPUT_ROOT / f"video_batch_test_{timestamp}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    videos = scan_videos(VIDEO_DIR)
    if not videos:
        raise SystemExit(f"No videos found in {VIDEO_DIR}")

    preflight = build_preflight(batch_dir, videos)
    write_json(batch_dir / "run_manifest.json", preflight)

    video_results: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for index, video_path in enumerate(videos, start=1):
        print(f"[{index}/{len(videos)}] start {video_path.name}", flush=True)
        result = run_one_video(index, video_path, batch_dir, preflight)
        video_results.append(result)
        summary_rows.append(result["summary_row"])
        print(
            f"[{index}/{len(videos)}] done {video_path.name} "
            f"event={result['fall_event'].get('event_created')} "
            f"qwen={result['qwen'].get('verdict')} "
            f"alarm={result['final_result']['alarm']['should_alarm']}",
            flush=True,
        )

    summary = build_summary(batch_dir, preflight, video_results)
    write_json(batch_dir / "summary.json", summary)
    write_csv(batch_dir / "summary.csv", summary_rows)
    write_json(batch_dir / "performance_summary.json", build_performance_summary(video_results))
    write_markdown_report(batch_dir / "TEST_REPORT.md", video_results)

    print(
        json.dumps(
            {
                "batch_dir": str(batch_dir),
                "video_count": len(video_results),
                "summary_json": str(batch_dir / "summary.json"),
                "report_md": str(batch_dir / "TEST_REPORT.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def run_one_video(index: int, video_path: Path, batch_dir: Path, preflight: dict[str, Any]) -> dict[str, Any]:
    video_slug = safe_slug(video_path.stem)
    video_dir = batch_dir / f"{index:03d}_{video_slug}"
    keyframes_dir = video_dir / "keyframes"
    video_dir.mkdir(parents=True, exist_ok=True)
    keyframes_dir.mkdir(parents=True, exist_ok=True)

    metadata = inspect_video(video_path)
    settings = build_batch_settings(batch_dir)
    source_manager = CameraSourceManager(settings)
    realtime_store = RealtimeResultStore()
    result_channels = ResultChannelManager()
    test_archive = PostFallTestArchiveService(
        str(batch_dir),
        drain_timeout_seconds=settings.test_drain_timeout_seconds,
    )
    qwen_transport = QwenTransportRecorder()
    qwen_analyzer = QwenKeyframeAnalyzer(
        endpoint_url=settings.post_fall_v2_qwen_base_url,
        model_name=settings.post_fall_v2_qwen_model,
        timeout_seconds=settings.post_fall_v2_qwen_timeout_seconds,
        num_ctx=settings.post_fall_v2_qwen_num_ctx,
        temperature=settings.post_fall_v2_qwen_temperature,
        context_retry_enabled=settings.post_fall_v2_qwen_context_retry_enabled,
        transport=qwen_transport,
    )
    vlm = VLMReviewService(
        enabled=settings.post_fall_v2_vlm_enabled,
        timeout_seconds=settings.post_fall_v2_qwen_timeout_seconds,
        queue_capacity=settings.post_fall_v2_qwen_queue_capacity,
    )
    runtime = PostFallV2RuntimeService(
        settings=settings,
        source_manager=source_manager,
        realtime_store=realtime_store,
        result_channels=result_channels,
        vlm_review_service=vlm,
        test_archive_service=test_archive,
        manual_control_enabled=False,
    )
    vlm.analyzer = PFV2QwenFallAnalyzer(
        analyzer=qwen_analyzer,
        image_provider=runtime.qwen_images_for_incident,
    )

    camera_id = f"batch_{index:03d}"
    test_archive.start_test(max(300, int(metadata["duration_sec"] + 240)))
    failure: dict[str, Any] | None = None
    try:
        runtime.start_for_camera(camera_id)
        source_manager.start_source(CameraSourceConfig(camera_id=camera_id, source_url=str(video_path.resolve())))
        wait_for_settlement(runtime, source_manager, camera_id, timeout_seconds=max(600.0, metadata["duration_sec"] * 4 + 180))
    except Exception as exc:
        failure = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        try:
            runtime.stop_all()
        except Exception:
            pass
        try:
            source_manager.stop_all()
        except Exception:
            pass
        try:
            test_archive.stop_test()
        except Exception:
            pass

    archive_status = test_archive.status()
    session_dir = Path(archive_status.session_dir) if archive_status.session_dir else None
    session_events = load_json(session_dir / "events.json") if session_dir and (session_dir / "events.json").exists() else []
    binary_rows = load_csv_rows(session_dir / "binary_predictions.csv") if session_dir and (session_dir / "binary_predictions.csv").exists() else []

    primary_record = next(
        (
            item
            for item in reversed(session_events)
            if (item.get("qwen_analysis") or {}).get("analysis_status") == "completed"
        ),
        None,
    )
    if primary_record is None and session_events:
        primary_record = session_events[0]
    binary_results = build_binary_results(binary_rows, video_path, metadata)
    binary_summary = build_binary_summary(binary_results, archive_status, metadata, failure)
    fall_event_result = build_fall_event_result(session_events, video_path, binary_summary)
    qwen_result = build_qwen_result(primary_record, qwen_transport, qwen_analyzer, video_path)
    final_result = build_final_result(
        video_path=video_path,
        metadata=metadata,
        binary_summary=binary_summary,
        fall_event_result=fall_event_result,
        qwen_result=qwen_result,
        archive_status=asdict(archive_status),
        preflight=preflight,
        failure=failure,
    )

    write_json(
        video_dir / "source_info.json",
        {
            "video": metadata,
            "settings": extract_relevant_settings(settings),
            "batch": {
                "index": index,
                "camera_id": camera_id,
                "session_dir": str(session_dir) if session_dir else None,
            },
            "preflight": {
                "binary_model": preflight["binary_model"],
                "ollama": preflight["ollama"],
            },
        },
    )
    write_jsonl(video_dir / "binary_results.jsonl", binary_results)
    write_json(video_dir / "binary_summary.json", binary_summary)
    write_json(video_dir / "fall_event.json", fall_event_result)
    write_json(video_dir / "qwen_review.json", qwen_result["qwen_review"])
    write_text(video_dir / "qwen_raw_response.txt", qwen_result["raw_response_text"])
    write_json(video_dir / "final_result.json", final_result)
    write_json(video_dir / "performance.json", final_result.get("performance") or {})
    copy_keyframes(batch_dir, video_dir / "keyframes", fall_event_result)

    if len(session_events) > 1:
        write_json(video_dir / "events.json", session_events)
        write_json(video_dir / "qwen_reviews.json", [record.get("qwen_analysis") for record in session_events if record.get("qwen_analysis")])

    summary_row = {
        "video": video_path.name,
        "duration_sec": round(float(metadata["duration_sec"] or 0.0), 3),
        "fps": metadata["fps"],
        "sampled_frames": binary_summary["sampled_frames"],
        "fall_frames": binary_summary["fall_frames"],
        "non_fall_frames": binary_summary["non_fall_frames"],
        "unknown_frames": binary_summary["unknown_frames"],
        "fall_event": "YES" if fall_event_result.get("event_created") else "NO",
        "qwen_called": "YES" if qwen_result.get("qwen_requested") else "NO",
        "qwen_verdict": qwen_result.get("verdict") or "-",
        "qwen_elapsed_ms": qwen_result.get("elapsed_ms"),
        "high_risk_fall": qwen_result.get("high_risk_fall"),
        "safety_outcome": (final_result.get("safety") or {}).get("safety_outcome"),
        "active_provider": final_result["binary"].get("provider"),
        "provider_degraded": final_result["binary"].get("provider_degraded"),
        "final_alarm": "YES" if final_result["alarm"]["should_alarm"] else "NO",
        "result_dir": str(video_dir),
    }

    return {
        "video_name": video_path.name,
        "video_path": str(video_path),
        "result_dir": str(video_dir),
        "metadata": metadata,
        "binary_summary": binary_summary,
        "fall_event": fall_event_result,
        "qwen": qwen_result,
        "final_result": final_result,
        "summary_row": summary_row,
        "archive_status": asdict(archive_status),
        "failure": failure,
    }


def build_batch_settings(batch_dir: Path) -> Settings:
    base = Settings()
    return replace(
        base,
        pipeline_mode="post_fall_v2",
        post_fall_v2_enabled=True,
        post_fall_v2_vlm_enabled=True,
        post_fall_v2_qwen_enabled=True,
        post_fall_v2_qwen_provider="qwen_keyframe",
        post_fall_v2_qwen_model=base.post_fall_v2_qwen_model,
        post_fall_v2_qwen_base_url=OLLAMA_ENDPOINT,
        post_fall_v2_qwen_timeout_seconds=max(5.0, float(base.post_fall_v2_qwen_timeout_seconds)),
        post_fall_v2_keyframe_post_collection_enabled=True,
        post_fall_v2_event_buffer_seconds=max(8.0, float(base.post_fall_v2_event_buffer_seconds)),
        post_fall_v2_binary_preload=True,
        post_fall_v2_binary_onnx_providers="CUDAExecutionProvider,CPUExecutionProvider",
        post_fall_v2_binary_model_path=base.post_fall_v2_binary_model_path,
        post_fall_v2_model_path=base.post_fall_v2_model_path,
        post_fall_v2_sample_fps=float(base.post_fall_v2_sample_fps),
        post_fall_v2_window_size=int(base.post_fall_v2_window_size),
        post_fall_v2_min_positive_frames=int(base.post_fall_v2_min_positive_frames),
        post_fall_v2_min_consecutive_frames=int(base.post_fall_v2_min_consecutive_frames),
        post_fall_v2_candidate_min_ms=int(base.post_fall_v2_candidate_min_ms),
        post_fall_v2_recovery_min_ms=int(base.post_fall_v2_recovery_min_ms),
        post_fall_v2_cooldown_ms=int(base.post_fall_v2_cooldown_ms),
        post_fall_v2_binary_threshold=float(base.post_fall_v2_binary_threshold),
        post_fall_v2_qwen_num_ctx=int(base.post_fall_v2_qwen_num_ctx),
        post_fall_v2_qwen_temperature=float(base.post_fall_v2_qwen_temperature),
        post_fall_v2_qwen_context_retry_enabled=bool(base.post_fall_v2_qwen_context_retry_enabled),
        post_fall_v2_qwen_queue_capacity=int(base.post_fall_v2_qwen_queue_capacity),
        post_fall_v2_qwen_max_images=int(base.post_fall_v2_qwen_max_images),
        post_fall_v2_qwen_max_image_bytes=int(base.post_fall_v2_qwen_max_image_bytes),
        post_fall_v2_qwen_image_max_edge=int(base.post_fall_v2_qwen_image_max_edge),
        post_fall_v2_qwen_jpeg_quality=int(base.post_fall_v2_qwen_jpeg_quality),
        post_fall_v2_qwen_evidence_dir=str(batch_dir / "qwen_evidence"),
        post_fall_v2_binary_evidence_dir=str(batch_dir / "binary_evidence"),
        post_fall_v2_evidence_export_enabled=False,
        post_fall_v2_input_mode="full_frame",
        follow_target_enabled=False,
        capture_backend="subprocess_pyav",
        capture_process_write_fps=60,
        capture_process_output_height=720,
        event_pipeline_enabled=False,
        event_delivery_enabled=False,
        main_system_alert_enabled=False,
        test_event_root=str(batch_dir),
        test_drain_timeout_seconds=max(120.0, float(base.test_drain_timeout_seconds)),
    )


def build_preflight(batch_dir: Path, videos: list[Path]) -> dict[str, Any]:
    python_info = {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "onnxruntime": None,
        "providers": [],
    }
    try:
        import onnxruntime as ort

        python_info["onnxruntime"] = ort.__version__
        python_info["providers"] = list(ort.get_available_providers())
    except Exception as exc:
        python_info["onnxruntime_error"] = str(exc)

    settings = Settings()
    return {
        "created_at": utc_now_iso(),
        "batch_dir": str(batch_dir),
        "video_dir": str(VIDEO_DIR),
        "video_count": len(videos),
        "python": python_info,
        "binary_model": inspect_binary_model(settings),
        "ollama": inspect_ollama(),
        "env": extract_relevant_settings(settings),
        "videos": [inspect_video(path) for path in videos],
        "notes": [
            "follow_target receiver is disabled in the batch harness because UDP port 8766 is already occupied on this machine; the formal binary path still uses full_frame input mode and is not gated by follow-target data.",
            "capture_process_write_fps is raised only to speed up offline replay; sample_fps, threshold, window and Qwen model remain the formal configuration.",
        ],
    }


def inspect_ollama() -> dict[str, Any]:
    try:
        response = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models", []) if isinstance(payload, dict) else []
        return {
            "endpoint": "http://127.0.0.1:11434",
            "api": OLLAMA_ENDPOINT,
            "ok": True,
            "http_status": response.status_code,
            "model_names": [str(item.get("name")) for item in models if isinstance(item, dict)],
            "models": models,
        }
    except Exception as exc:
        return {
            "endpoint": "http://127.0.0.1:11434",
            "api": OLLAMA_ENDPOINT,
            "ok": False,
            "error": str(exc),
        }


def inspect_binary_model(settings: Settings) -> dict[str, Any]:
    model_path = resolve_model_path(settings.post_fall_v2_binary_model_path)
    info: dict[str, Any] = {
        "path": str(model_path),
        "exists": model_path.is_file(),
        "expected_sha256": settings.post_fall_v2_binary_model_sha256,
        "requested_providers": [part.strip() for part in settings.post_fall_v2_binary_onnx_providers.split(",") if part.strip()],
    }
    if model_path.is_file():
        info["sha256"] = sha256_file(model_path)
    try:
        preload_torch_cuda_dlls()
        import onnxruntime as ort

        info["available_providers"] = list(ort.get_available_providers())
        if model_path.is_file():
            session = ort.InferenceSession(str(model_path), providers=info["requested_providers"])
            info["active_providers"] = list(session.get_providers())
            info["loaded"] = True
            if info["requested_providers"] and info["active_providers"] and info["active_providers"][0] != info["requested_providers"][0]:
                info["provider_degraded"] = True
                info["provider_warning"] = "requested first provider is not active"
            else:
                info["provider_degraded"] = False
    except Exception as exc:
        info["load_error"] = str(exc)
    return info


def inspect_video(path: Path) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(path))
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        width = float(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0.0)
        height = float(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0.0)
        return {
            "file_name": path.name,
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else None,
            "opened": cap.isOpened(),
            "fps": fps,
            "frame_count": int(frame_count),
            "width": int(width),
            "height": int(height),
            "duration_sec": round(frame_count / fps, 3) if fps > 0 else None,
        }
    finally:
        cap.release()


def wait_for_settlement(
    runtime: PostFallV2RuntimeService,
    source_manager: CameraSourceManager,
    camera_id: str,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    last_event_count = -1
    stable_ticks = 0
    while time.monotonic() < deadline:
        status = runtime.status(camera_id)
        worker_status = source_manager.worker_status(camera_id)
        running = bool(worker_status and worker_status.running)
        vlm_active = int(status.get("vlm_active_count") or 0)
        keyframes_active = int(status.get("keyframe_collection_active_count") or 0)
        event_count = int(status.get("event_count") or 0)
        if not running and vlm_active == 0 and keyframes_active == 0:
            if event_count == last_event_count:
                stable_ticks += 1
            else:
                last_event_count = event_count
                stable_ticks = 0
            if stable_ticks >= 5:
                return
        else:
            stable_ticks = 0
            last_event_count = event_count
        time.sleep(0.2)
    raise TimeoutError("runtime did not settle before timeout")


def build_binary_results(rows: list[dict[str, str]], video_path: Path, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    fps = float(metadata["fps"] or 0.0) or 1.0
    results: list[dict[str, Any]] = []
    for sample_index, row in enumerate(rows, start=1):
        frame_seq = to_int(row.get("frame_seq")) or 0
        source_frame_index = max(0, frame_seq - 1)
        source_timestamp_ms = round(source_frame_index * 1000.0 / fps)
        results.append(
            {
                "video_name": video_path.name,
                "video_path": str(video_path),
                "sample_index": sample_index,
                "source_frame_index": source_frame_index,
                "source_timestamp_ms": source_timestamp_ms,
                "frame_seq": frame_seq,
                "frame_id": row.get("frame_id"),
                "binary_label": row.get("decision_label"),
                "fall_probability": to_float(row.get("fall_probability")),
                "non_fall_probability": to_float(row.get("non_fall_probability")),
                "threshold": to_float(row.get("threshold")),
                "provider": row.get("provider"),
                "frame_age_ms": to_float(row.get("frame_age_ms")),
                "queue_delay_ms": to_float(row.get("queue_delay_ms")),
                "inference_ms": to_float(row.get("inference_ms")),
                "total_ms": to_float(row.get("total_ms")),
                "aggregate_state": row.get("aggregate_state"),
                "window_size": to_int(row.get("window_size")),
                "positive_count": to_int(row.get("positive_count")),
                "consecutive_positive_count": to_int(row.get("consecutive_positive_count")),
                "candidate_duration_ms": to_int(row.get("candidate_duration_ms")),
                "incident_id": row.get("incident_id"),
                "event_created": parse_bool(row.get("event_created")),
                "reason": row.get("reason"),
                "inference_at": row.get("inference_at"),
            }
        )
    return results


def build_binary_summary(
    binary_results: list[dict[str, Any]],
    archive_status: dict[str, Any] | Any,
    metadata: dict[str, Any],
    failure: dict[str, Any] | None,
) -> dict[str, Any]:
    fall_probs = [float(row["fall_probability"]) for row in binary_results if row.get("fall_probability") is not None]
    labels = [str(row.get("binary_label") or "UNKNOWN") for row in binary_results]
    inference_ms = [float(row["inference_ms"]) for row in binary_results if row.get("inference_ms") is not None]
    queue_delay_ms = [float(row["queue_delay_ms"]) for row in binary_results if row.get("queue_delay_ms") is not None]
    frame_age_ms = [float(row["frame_age_ms"]) for row in binary_results if row.get("frame_age_ms") is not None]
    return {
        "enabled": True,
        "sample_fps": 3.0,
        "source_fps": metadata["fps"],
        "source_duration_sec": metadata["duration_sec"],
        "source_frame_count": metadata["frame_count"],
        "sampled_frames": len(binary_results),
        "processed_frames": len(binary_results),
        "fall_frames": sum(1 for label in labels if label == "FALL"),
        "non_fall_frames": sum(1 for label in labels if label == "NON_FALL"),
        "unknown_frames": sum(1 for label in labels if label == "UNKNOWN"),
        "max_fall_probability": max(fall_probs) if fall_probs else None,
        "mean_fall_probability": round(sum(fall_probs) / len(fall_probs), 6) if fall_probs else None,
        "max_consecutive_fall": max_consecutive(labels, "FALL"),
        "provider": first_non_empty((row.get("provider") for row in binary_results), None),
        "inference_ms": stats_summary(inference_ms),
        "queue_delay_ms": stats_summary(queue_delay_ms),
        "local_frame_age_ms": stats_summary(frame_age_ms),
        "failure": failure,
        "archive_status": archive_status if isinstance(archive_status, dict) else asdict(archive_status),
    }


def build_fall_event_result(
    session_events: list[dict[str, Any]],
    video_path: Path,
    binary_summary: dict[str, Any],
) -> dict[str, Any]:
    if not session_events:
        return {
            "event_created": False,
            "reason": "no_fall_event",
            "video_name": video_path.name,
        }
    primary = session_events[0]
    return {
        "event_created": True,
        "event_count": len(session_events),
        "primary_event_id": primary.get("incident_id"),
        "video_name": video_path.name,
        "archive_record": primary,
        "event": primary.get("event") or {},
        "qwen_analysis": primary.get("qwen_analysis") or {},
        "all_events": session_events,
        "binary_summary": binary_summary,
        "qwen_verdict": (primary.get("qwen_analysis") or {}).get("fall_verdict"),
    }


def build_qwen_result(
    primary_record: dict[str, Any] | None,
    qwen_transport: "QwenTransportRecorder",
    qwen_analyzer: QwenKeyframeAnalyzer,
    video_path: Path,
) -> dict[str, Any]:
    if primary_record is None:
        return {
            "qwen_requested": False,
            "qwen_started": False,
            "qwen_completed": False,
            "qwen_failed": False,
            "model": qwen_analyzer.model_name,
            "endpoint": qwen_analyzer.endpoint_url,
            "verdict": None,
            "confidence": None,
            "analysis_status": None,
            "summary": None,
            "elapsed_ms": None,
            "high_risk_fall": None,
            "error_message": None,
            "qwen_start_frames_received": None,
            "qwen_end_frames_received": None,
            "frames_received_during_qwen": None,
            "raw_response_text": "",
            "qwen_review": {
                "qwen_requested": False,
                "reason": "no_fall_event",
                "video_name": video_path.name,
            },
            "transport_calls": [],
        }

    event_payload = primary_record.get("event") or {}
    qwen_analysis = primary_record.get("qwen_analysis") or {}
    qwen_requested = bool(primary_record.get("qwen_bucket") or qwen_analysis or event_payload.get("vlm_status") not in {None, "disabled"})
    raw_text = qwen_transport.raw_text()
    qwen_review = {
        "qwen_requested": qwen_requested,
        "video_name": video_path.name,
        "incident_id": primary_record.get("incident_id"),
        "camera_id": primary_record.get("camera_id"),
        "fall_verdict": qwen_analysis.get("fall_verdict"),
        "analysis_status": qwen_analysis.get("analysis_status"),
        "elapsed_ms": qwen_analysis.get("latency_ms") or primary_record.get("qwen_elapsed_ms"),
        "high_risk_fall": qwen_analysis.get("high_risk_fall"),
        "error_message": qwen_analysis.get("error_message"),
        "qwen_start_frames_received": qwen_analysis.get("qwen_start_frames_received"),
        "qwen_end_frames_received": qwen_analysis.get("qwen_end_frames_received"),
        "frames_received_during_qwen": qwen_analysis.get("frames_received_during_qwen"),
        "qwen_analysis": qwen_analysis,
        "event": event_payload,
        "archive_record": primary_record,
        "transport_calls": qwen_transport.calls,
        "raw_response_text": raw_text,
    }
    return {
        "qwen_requested": qwen_requested,
        "qwen_started": bool(qwen_transport.calls),
        "qwen_completed": qwen_analysis.get("analysis_status") == "completed",
        "qwen_failed": qwen_analysis.get("analysis_status") in {"failed", "timeout", "parse_failed"},
        "model": qwen_analysis.get("model_name") or qwen_analyzer.model_name,
        "endpoint": qwen_analyzer.endpoint_url,
        "verdict": qwen_analysis.get("fall_verdict"),
        "confidence": qwen_analysis.get("confidence"),
        "analysis_status": qwen_analysis.get("analysis_status"),
        "summary": qwen_analysis.get("summary"),
        "elapsed_ms": qwen_analysis.get("latency_ms") or primary_record.get("qwen_elapsed_ms"),
        "high_risk_fall": qwen_analysis.get("high_risk_fall"),
        "error_message": qwen_analysis.get("error_message"),
        "qwen_start_frames_received": qwen_analysis.get("qwen_start_frames_received"),
        "qwen_end_frames_received": qwen_analysis.get("qwen_end_frames_received"),
        "frames_received_during_qwen": qwen_analysis.get("frames_received_during_qwen"),
        "raw_response_text": raw_text,
        "qwen_review": qwen_review,
        "transport_calls": qwen_transport.calls,
    }


def build_final_result(
    *,
    video_path: Path,
    metadata: dict[str, Any],
    binary_summary: dict[str, Any],
    fall_event_result: dict[str, Any],
    qwen_result: dict[str, Any],
    archive_status: dict[str, Any],
    preflight: dict[str, Any],
    failure: dict[str, Any] | None,
) -> dict[str, Any]:
    event_created = bool(fall_event_result.get("event_created"))
    event_payload = fall_event_result.get("event") or {}
    safety = event_payload.get("safety_decision") or {}
    qwen_review = qwen_result.get("qwen_review") or {}
    qwen_analysis = qwen_review.get("qwen_analysis") or {}
    qwen_alarm = _qwen_review_requires_alert(qwen_analysis)
    should_alarm = bool(event_created and (str(safety.get("outcome") or "").lower() == "alert" or qwen_alarm))
    alarm_reason = str(safety.get("reason") or ("no_event" if not event_created else "qwen_not_confirmed"))
    if qwen_alarm and alarm_reason in {"semantic_review_pending", "qwen_not_confirmed"}:
        alarm_reason = "persistent_ground_abnormality_requires_alert"
    binary_model = preflight.get("binary_model") if isinstance(preflight, dict) else {}
    binary_active_providers = list(binary_model.get("active_providers") or [])
    binary_requested_providers = list(binary_model.get("requested_providers") or [])
    binary_available_providers = list(binary_model.get("available_providers") or [])
    binary_provider_warning = binary_model.get("load_error")
    binary_provider_degraded = bool(binary_model.get("loaded")) and bool(binary_active_providers) and (
        binary_requested_providers and binary_active_providers[0] != binary_requested_providers[0]
    )
    report_binary_provider = first_non_empty(binary_active_providers, binary_summary.get("provider"))
    return {
        "video": {
            "file_name": video_path.name,
            "path": str(video_path),
            "duration_sec": metadata["duration_sec"],
            "fps": metadata["fps"],
            "resolution": f'{metadata["width"]}x{metadata["height"]}',
            "frame_count": metadata["frame_count"],
        },
        "binary": {
            "enabled": True,
            "model": preflight["binary_model"]["path"],
            "provider": report_binary_provider,
            "requested_providers": binary_requested_providers,
            "active_providers": binary_active_providers,
            "available_providers": binary_available_providers,
            "provider_degraded": binary_provider_degraded,
            "provider_warning": binary_provider_warning,
            "sample_fps": binary_summary.get("sample_fps"),
            "sampled_frames": binary_summary.get("sampled_frames"),
            "processed_frames": binary_summary.get("processed_frames"),
            "fall_frames": binary_summary.get("fall_frames"),
            "non_fall_frames": binary_summary.get("non_fall_frames"),
            "unknown_frames": binary_summary.get("unknown_frames"),
            "max_fall_probability": binary_summary.get("max_fall_probability"),
            "mean_fall_probability": binary_summary.get("mean_fall_probability"),
            "max_consecutive_fall": binary_summary.get("max_consecutive_fall"),
        },
        "temporal": {
            "event_created": event_created,
            "event_count": fall_event_result.get("event_count", 0),
            "event_id": fall_event_result.get("primary_event_id"),
            "reason": None if event_created else fall_event_result.get("reason"),
        },
        "qwen": {
            "enabled": True,
            "requested": qwen_result.get("qwen_requested"),
            "started": qwen_result.get("qwen_started"),
            "completed": qwen_result.get("qwen_completed"),
            "failed": qwen_result.get("qwen_failed"),
            "model": qwen_result.get("model"),
            "endpoint": qwen_result.get("endpoint"),
            "verdict": qwen_result.get("verdict"),
            "confidence": qwen_result.get("confidence"),
            "analysis_status": qwen_result.get("analysis_status"),
            "summary": qwen_result.get("summary"),
            "elapsed_ms": qwen_result.get("elapsed_ms"),
            "high_risk_fall": qwen_result.get("high_risk_fall"),
            "error_message": qwen_result.get("error_message"),
            "qwen_start_frames_received": qwen_result.get("qwen_start_frames_received"),
            "qwen_end_frames_received": qwen_result.get("qwen_end_frames_received"),
            "frames_received_during_qwen": qwen_result.get("frames_received_during_qwen"),
            "transport_calls": qwen_result.get("transport_calls", []),
        },
        "safety": {
            "high_risk_fall": qwen_analysis.get("high_risk_fall"),
            "safety_outcome": safety.get("outcome"),
            "safety_path": safety.get("path"),
            "safety_reason": safety.get("reason"),
            "observation_elapsed_ms": safety.get("observation_elapsed_ms"),
        },
        "alarm": {
            "should_alarm": should_alarm,
            "reason": alarm_reason,
        },
        "artifacts": {
            "binary_results": "binary_results.jsonl",
            "binary_summary": "binary_summary.json",
            "fall_event": "fall_event.json",
            "qwen_review": "qwen_review.json",
            "qwen_raw_response": "qwen_raw_response.txt",
            "final_result": "final_result.json",
        },
        "failure": failure,
        "archive_status": archive_status,
        "preflight_ref": {
            "binary_model": preflight["binary_model"]["path"],
            "ollama": preflight["ollama"].get("api"),
        },
    }


def _qwen_review_requires_alert(qwen_analysis: dict[str, Any]) -> bool:
    if not isinstance(qwen_analysis, dict):
        return False
    verdict = str(qwen_analysis.get("fall_verdict") or "").strip().lower()
    if verdict == "confirmed_fall":
        high_risk = str(qwen_analysis.get("high_risk_fall") or "").strip() in {"1", "true", "yes"}
        return high_risk
    if verdict != "unclear":
        return False
    if str(qwen_analysis.get("analysis_status") or "").strip().lower() != "completed":
        return False
    posture_state = str(qwen_analysis.get("posture_state") or "").strip().lower()
    persistent_ground_state = str(qwen_analysis.get("persistent_ground_state") or "").strip().lower()
    if posture_state not in {"lying", "ground_low", "fallen", "on_ground"}:
        return False
    if persistent_ground_state != "observed":
        return False
    if qwen_analysis.get("intentional_action_evidence") is True:
        return False
    if qwen_analysis.get("recovery_observed") is True:
        return False
    return True


def copy_keyframes(batch_dir: Path, keyframes_dir: Path, fall_event_result: dict[str, Any]) -> None:
    keyframes_dir.mkdir(parents=True, exist_ok=True)
    if not fall_event_result.get("event_created"):
        write_json(
            keyframes_dir / "manifest.json",
            {
                "event_created": False,
                "reason": fall_event_result.get("reason"),
            },
        )
        return

    archive_record = fall_event_result.get("archive_record") or {}
    primary_event_id = str(archive_record.get("incident_id") or fall_event_result.get("primary_event_id") or "")
    qwen_bucket = str(archive_record.get("qwen_bucket") or "review")
    qwen_dir = batch_dir / "qwen" / qwen_bucket / primary_event_id
    binary_dir = batch_dir / "binary-classification" / "full" / primary_event_id
    source_dir = qwen_dir if qwen_dir.exists() else binary_dir if binary_dir.exists() else None
    files: list[str] = []
    if source_dir is not None:
        for file_path in sorted(source_dir.iterdir()):
            if file_path.is_file() and file_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                shutil.copy2(file_path, keyframes_dir / file_path.name)
                files.append(file_path.name)
    write_json(
        keyframes_dir / "manifest.json",
        {
            "event_created": True,
            "primary_event_id": primary_event_id,
            "qwen_bucket": qwen_bucket if qwen_dir.exists() else None,
            "source_dir": str(source_dir) if source_dir else None,
            "files": files,
        },
    )


def build_summary(batch_dir: Path, preflight: dict[str, Any], video_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "created_at": utc_now_iso(),
        "batch_dir": str(batch_dir),
        "video_count": len(video_results),
        "videos": [
            {
                "video_name": item["video_name"],
                "result_dir": item["result_dir"],
                "event_created": item["fall_event"].get("event_created"),
                "qwen_verdict": item["qwen"].get("verdict"),
                "alarm": item["final_result"]["alarm"]["should_alarm"],
            }
            for item in video_results
        ],
        "preflight": preflight,
    }


def build_performance_summary(video_results: list[dict[str, Any]]) -> dict[str, Any]:
    binary_inference: list[float] = []
    binary_queue_delay: list[float] = []
    local_frame_age: list[float] = []
    qwen_elapsed: list[float] = []
    for item in video_results:
        binary = item.get("binary_summary") or {}
        qwen = item.get("qwen") or {}
        binary_inference.extend(_stat_values(binary.get("inference_ms")))
        binary_queue_delay.extend(_stat_values(binary.get("queue_delay_ms")))
        local_frame_age.extend(_stat_values(binary.get("local_frame_age_ms")))
        elapsed = to_float(qwen.get("elapsed_ms"))
        if elapsed is not None:
            qwen_elapsed.append(elapsed)
    return {
        "binary_inference_ms": stats_summary(binary_inference),
        "binary_queue_delay_ms": stats_summary(binary_queue_delay),
        "local_frame_age_ms": stats_summary(local_frame_age),
        "qwen_elapsed_ms": stats_summary(qwen_elapsed),
    }


def write_markdown_report(path: Path, video_results: list[dict[str, Any]]) -> None:
    lines = [
        "# Video Batch Test Report",
        "",
        "| 视频 | 时长 | 抽帧 | FALL帧 | NON_FALL帧 | UNKNOWN | FallEvent | Qwen调用 | Qwen Verdict | Qwen耗时ms | Safety | 最终告警 | 结果目录 |",
        "| -- | --: | --: | --: | --: | --: | -- | -- | -- | --: | -- | -- | -- |",
    ]
    for item in video_results:
        meta = item["metadata"]
        binary = item["binary_summary"]
        qwen = item["qwen"]
        final_result = item["final_result"]
        lines.append(
            "| {video} | {duration:.2f} | {sampled} | {fall} | {non_fall} | {unknown} | {event} | {called} | {verdict} | {elapsed} | {safety} | {alarm} | {dir} |".format(
                video=item["video_name"],
                duration=float(meta["duration_sec"] or 0.0),
                sampled=binary["sampled_frames"],
                fall=binary["fall_frames"],
                non_fall=binary["non_fall_frames"],
                unknown=binary["unknown_frames"],
                event="YES" if item["fall_event"].get("event_created") else "NO",
                called="YES" if qwen.get("qwen_requested") else "NO",
                verdict=qwen.get("verdict") or "-",
                elapsed=qwen.get("elapsed_ms") or "-",
                safety=(final_result.get("safety") or {}).get("safety_outcome") or "-",
                alarm="YES" if final_result["alarm"]["should_alarm"] else "NO",
                dir=item["result_dir"],
            )
        )
    lines.extend(["", "## Details", ""])
    for item in video_results:
        lines.extend(
            [
                f"## {item['video_name']}",
                "",
                f"- result_dir: `{item['result_dir']}`",
                f"- event_created: `{item['fall_event'].get('event_created')}`",
                f"- qwen_verdict: `{item['qwen'].get('verdict')}`",
                f"- final_alarm: `{item['final_result']['alarm']['should_alarm']}`",
                f"- final_result: `{Path(item['result_dir']) / 'final_result.json'}`",
                "",
            ]
        )
    write_text(path, "\n".join(lines) + "\n")


class QwenTransportRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        started = time.perf_counter()
        response = requests.post(OLLAMA_ENDPOINT, json=payload, timeout=timeout)
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        entry = {
            "request_index": len(self.calls) + 1,
            "http_status": response.status_code,
            "elapsed_ms": elapsed_ms,
            "ok": response.ok,
            "raw_response_text": response.text,
        }
        self.calls.append(entry)
        if response.status_code >= 400:
            raise requests.HTTPError(f"HTTP {response.status_code}: {response.text}", response=response)
        try:
            return response.json()
        except Exception as exc:
            raise ValueError(f"invalid JSON from Ollama: {exc}") from exc

    def raw_text(self) -> str:
        return "\n\n".join(
            f"--- call {entry['request_index']} status={entry['http_status']} elapsed_ms={entry['elapsed_ms']} ---\n{entry['raw_response_text']}"
            for entry in self.calls
        )


def build_preflight(batch_dir: Path, videos: list[Path]) -> dict[str, Any]:
    python_info = {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "onnxruntime": None,
        "providers": [],
    }
    try:
        import onnxruntime as ort

        python_info["onnxruntime"] = ort.__version__
        python_info["providers"] = list(ort.get_available_providers())
    except Exception as exc:
        python_info["onnxruntime_error"] = str(exc)

    settings = Settings()
    return {
        "created_at": utc_now_iso(),
        "batch_dir": str(batch_dir),
        "video_dir": str(VIDEO_DIR),
        "video_count": len(videos),
        "python": python_info,
        "binary_model": inspect_binary_model(settings),
        "ollama": inspect_ollama(),
        "env": extract_relevant_settings(settings),
        "videos": [inspect_video(path) for path in videos],
        "notes": [
            "follow_target receiver is disabled in the batch harness because UDP port 8766 is already occupied on this machine; the formal binary path still uses full_frame input mode and is not gated by follow-target data.",
            "capture_process_write_fps is raised only to speed up offline replay; sample_fps, threshold, window and Qwen model remain the formal configuration.",
        ],
    }


def inspect_ollama() -> dict[str, Any]:
    try:
        response = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models", []) if isinstance(payload, dict) else []
        return {
            "endpoint": "http://127.0.0.1:11434",
            "api": OLLAMA_ENDPOINT,
            "ok": True,
            "http_status": response.status_code,
            "model_names": [str(item.get("name")) for item in models if isinstance(item, dict)],
            "models": models,
        }
    except Exception as exc:
        return {
            "endpoint": "http://127.0.0.1:11434",
            "api": OLLAMA_ENDPOINT,
            "ok": False,
            "error": str(exc),
        }


def inspect_binary_model(settings: Settings) -> dict[str, Any]:
    model_path = resolve_model_path(settings.post_fall_v2_binary_model_path)
    info: dict[str, Any] = {
        "path": str(model_path),
        "exists": model_path.is_file(),
        "expected_sha256": settings.post_fall_v2_binary_model_sha256,
        "requested_providers": [part.strip() for part in settings.post_fall_v2_binary_onnx_providers.split(",") if part.strip()],
    }
    if model_path.is_file():
        info["sha256"] = sha256_file(model_path)
    try:
        preload_torch_cuda_dlls()
        import onnxruntime as ort

        info["available_providers"] = list(ort.get_available_providers())
        if model_path.is_file():
            session = ort.InferenceSession(str(model_path), providers=info["requested_providers"])
            info["active_providers"] = list(session.get_providers())
            info["loaded"] = True
            if info["requested_providers"] and info["active_providers"] and info["active_providers"][0] != info["requested_providers"][0]:
                info["provider_degraded"] = True
                info["provider_warning"] = "requested first provider is not active"
            else:
                info["provider_degraded"] = False
    except Exception as exc:
        info["load_error"] = str(exc)
    return info


def inspect_video(path: Path) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(path))
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        width = float(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0.0)
        height = float(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0.0)
        return {
            "file_name": path.name,
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else None,
            "opened": cap.isOpened(),
            "fps": fps,
            "frame_count": int(frame_count),
            "width": int(width),
            "height": int(height),
            "duration_sec": round(frame_count / fps, 3) if fps > 0 else None,
        }
    finally:
        cap.release()


def wait_for_settlement(
    runtime: PostFallV2RuntimeService,
    source_manager: CameraSourceManager,
    camera_id: str,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    last_event_count = -1
    stable_ticks = 0
    while time.monotonic() < deadline:
        status = runtime.status(camera_id)
        worker_status = source_manager.worker_status(camera_id)
        running = bool(worker_status and worker_status.running)
        vlm_active = int(status.get("vlm_active_count") or 0)
        keyframes_active = int(status.get("keyframe_collection_active_count") or 0)
        event_count = int(status.get("event_count") or 0)
        if not running and vlm_active == 0 and keyframes_active == 0:
            if event_count == last_event_count:
                stable_ticks += 1
            else:
                last_event_count = event_count
                stable_ticks = 0
            if stable_ticks >= 5:
                return
        else:
            stable_ticks = 0
            last_event_count = event_count
        time.sleep(0.2)
    raise TimeoutError("runtime did not settle before timeout")


def build_binary_results(rows: list[dict[str, str]], video_path: Path, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    fps = float(metadata["fps"] or 0.0) or 1.0
    results: list[dict[str, Any]] = []
    for sample_index, row in enumerate(rows, start=1):
        frame_seq = to_int(row.get("frame_seq")) or 0
        source_frame_index = max(0, frame_seq - 1)
        source_timestamp_ms = round(source_frame_index * 1000.0 / fps)
        results.append(
            {
                "video_name": video_path.name,
                "video_path": str(video_path),
                "sample_index": sample_index,
                "source_frame_index": source_frame_index,
                "source_timestamp_ms": source_timestamp_ms,
                "frame_seq": frame_seq,
                "frame_id": row.get("frame_id"),
                "binary_label": row.get("decision_label"),
                "fall_probability": to_float(row.get("fall_probability")),
                "non_fall_probability": to_float(row.get("non_fall_probability")),
                "threshold": to_float(row.get("threshold")),
                "provider": row.get("provider"),
                "frame_age_ms": to_float(row.get("frame_age_ms")),
                "queue_delay_ms": to_float(row.get("queue_delay_ms")),
                "inference_ms": to_float(row.get("inference_ms")),
                "total_ms": to_float(row.get("total_ms")),
                "aggregate_state": row.get("aggregate_state"),
                "window_size": to_int(row.get("window_size")),
                "positive_count": to_int(row.get("positive_count")),
                "consecutive_positive_count": to_int(row.get("consecutive_positive_count")),
                "candidate_duration_ms": to_int(row.get("candidate_duration_ms")),
                "incident_id": row.get("incident_id"),
                "event_created": parse_bool(row.get("event_created")),
                "reason": row.get("reason"),
                "inference_at": row.get("inference_at"),
            }
        )
    return results


def build_binary_summary(
    binary_results: list[dict[str, Any]],
    archive_status: dict[str, Any] | Any,
    metadata: dict[str, Any],
    failure: dict[str, Any] | None,
) -> dict[str, Any]:
    fall_probs = [float(row["fall_probability"]) for row in binary_results if row.get("fall_probability") is not None]
    labels = [str(row.get("binary_label") or "UNKNOWN") for row in binary_results]
    inference_ms = [float(row["inference_ms"]) for row in binary_results if row.get("inference_ms") is not None]
    queue_delay_ms = [float(row["queue_delay_ms"]) for row in binary_results if row.get("queue_delay_ms") is not None]
    frame_age_ms = [float(row["frame_age_ms"]) for row in binary_results if row.get("frame_age_ms") is not None]
    return {
        "enabled": True,
        "sample_fps": 3.0,
        "source_fps": metadata["fps"],
        "source_duration_sec": metadata["duration_sec"],
        "source_frame_count": metadata["frame_count"],
        "sampled_frames": len(binary_results),
        "processed_frames": len(binary_results),
        "fall_frames": sum(1 for label in labels if label == "FALL"),
        "non_fall_frames": sum(1 for label in labels if label == "NON_FALL"),
        "unknown_frames": sum(1 for label in labels if label == "UNKNOWN"),
        "max_fall_probability": max(fall_probs) if fall_probs else None,
        "mean_fall_probability": round(sum(fall_probs) / len(fall_probs), 6) if fall_probs else None,
        "max_consecutive_fall": max_consecutive(labels, "FALL"),
        "provider": first_non_empty((row.get("provider") for row in binary_results), None),
        "inference_ms": stats_summary(inference_ms),
        "queue_delay_ms": stats_summary(queue_delay_ms),
        "local_frame_age_ms": stats_summary(frame_age_ms),
        "failure": failure,
        "archive_status": archive_status if isinstance(archive_status, dict) else asdict(archive_status),
    }


def build_fall_event_result(
    session_events: list[dict[str, Any]],
    video_path: Path,
    binary_summary: dict[str, Any],
) -> dict[str, Any]:
    if not session_events:
        return {
            "event_created": False,
            "reason": "no_fall_event",
            "video_name": video_path.name,
        }
    primary = session_events[0]
    return {
        "event_created": True,
        "event_count": len(session_events),
        "primary_event_id": primary.get("incident_id"),
        "video_name": video_path.name,
        "archive_record": primary,
        "event": primary.get("event") or {},
        "qwen_analysis": primary.get("qwen_analysis") or {},
        "all_events": session_events,
        "binary_summary": binary_summary,
        "qwen_verdict": (primary.get("qwen_analysis") or {}).get("fall_verdict"),
    }


def build_qwen_result(
    primary_record: dict[str, Any] | None,
    qwen_transport: "QwenTransportRecorder",
    qwen_analyzer: QwenKeyframeAnalyzer,
    video_path: Path,
) -> dict[str, Any]:
    if primary_record is None:
        return {
            "qwen_requested": False,
            "qwen_started": False,
            "qwen_completed": False,
            "qwen_failed": False,
            "model": qwen_analyzer.model_name,
            "endpoint": qwen_analyzer.endpoint_url,
            "verdict": None,
            "confidence": None,
            "analysis_status": None,
            "summary": None,
            "elapsed_ms": None,
            "high_risk_fall": None,
            "error_message": None,
            "qwen_start_frames_received": None,
            "qwen_end_frames_received": None,
            "frames_received_during_qwen": None,
            "raw_response_text": "",
            "qwen_review": {
                "qwen_requested": False,
                "reason": "no_fall_event",
                "video_name": video_path.name,
            },
            "transport_calls": [],
        }

    event_payload = primary_record.get("event") or {}
    qwen_analysis = primary_record.get("qwen_analysis") or {}
    qwen_requested = bool(primary_record.get("qwen_bucket") or qwen_analysis or event_payload.get("vlm_status") not in {None, "disabled"})
    raw_text = qwen_transport.raw_text()
    qwen_review = {
        "qwen_requested": qwen_requested,
        "video_name": video_path.name,
        "incident_id": primary_record.get("incident_id"),
        "camera_id": primary_record.get("camera_id"),
        "fall_verdict": qwen_analysis.get("fall_verdict"),
        "analysis_status": qwen_analysis.get("analysis_status"),
        "elapsed_ms": qwen_analysis.get("latency_ms") or primary_record.get("qwen_elapsed_ms"),
        "high_risk_fall": qwen_analysis.get("high_risk_fall"),
        "error_message": qwen_analysis.get("error_message"),
        "qwen_start_frames_received": qwen_analysis.get("qwen_start_frames_received"),
        "qwen_end_frames_received": qwen_analysis.get("qwen_end_frames_received"),
        "frames_received_during_qwen": qwen_analysis.get("frames_received_during_qwen"),
        "qwen_analysis": qwen_analysis,
        "event": event_payload,
        "archive_record": primary_record,
        "transport_calls": qwen_transport.calls,
        "raw_response_text": raw_text,
    }
    return {
        "qwen_requested": qwen_requested,
        "qwen_started": bool(qwen_transport.calls),
        "qwen_completed": qwen_analysis.get("analysis_status") == "completed",
        "qwen_failed": qwen_analysis.get("analysis_status") in {"failed", "timeout", "parse_failed"},
        "model": qwen_analysis.get("model_name") or qwen_analyzer.model_name,
        "endpoint": qwen_analyzer.endpoint_url,
        "verdict": qwen_analysis.get("fall_verdict"),
        "confidence": qwen_analysis.get("confidence"),
        "analysis_status": qwen_analysis.get("analysis_status"),
        "summary": qwen_analysis.get("summary"),
        "elapsed_ms": qwen_analysis.get("latency_ms") or primary_record.get("qwen_elapsed_ms"),
        "high_risk_fall": qwen_analysis.get("high_risk_fall"),
        "error_message": qwen_analysis.get("error_message"),
        "qwen_start_frames_received": qwen_analysis.get("qwen_start_frames_received"),
        "qwen_end_frames_received": qwen_analysis.get("qwen_end_frames_received"),
        "frames_received_during_qwen": qwen_analysis.get("frames_received_during_qwen"),
        "raw_response_text": raw_text,
        "qwen_review": qwen_review,
        "transport_calls": qwen_transport.calls,
    }


def build_final_result(
    *,
    video_path: Path,
    metadata: dict[str, Any],
    binary_summary: dict[str, Any],
    fall_event_result: dict[str, Any],
    qwen_result: dict[str, Any],
    archive_status: dict[str, Any],
    preflight: dict[str, Any],
    failure: dict[str, Any] | None,
) -> dict[str, Any]:
    event_created = bool(fall_event_result.get("event_created"))
    event_payload = fall_event_result.get("event") or {}
    safety = event_payload.get("safety_decision") or {}
    qwen_review = qwen_result.get("qwen_review") or {}
    qwen_analysis = qwen_review.get("qwen_analysis") or {}
    qwen_alarm = _qwen_review_requires_alert(qwen_analysis)
    should_alarm = bool(event_created and (str(safety.get("outcome") or "").lower() == "alert" or qwen_alarm))
    alarm_reason = str(safety.get("reason") or ("no_event" if not event_created else "qwen_not_confirmed"))
    if qwen_alarm and alarm_reason in {"semantic_review_pending", "qwen_not_confirmed"}:
        alarm_reason = "persistent_ground_abnormality_requires_alert"
    return {
        "video": {
            "file_name": video_path.name,
            "path": str(video_path),
            "duration_sec": metadata["duration_sec"],
            "fps": metadata["fps"],
            "resolution": f'{metadata["width"]}x{metadata["height"]}',
            "frame_count": metadata["frame_count"],
        },
        "binary": {
            "enabled": True,
            "model": preflight["binary_model"]["path"],
            "provider": binary_summary.get("provider"),
            "sample_fps": binary_summary.get("sample_fps"),
            "sampled_frames": binary_summary.get("sampled_frames"),
            "processed_frames": binary_summary.get("processed_frames"),
            "fall_frames": binary_summary.get("fall_frames"),
            "non_fall_frames": binary_summary.get("non_fall_frames"),
            "unknown_frames": binary_summary.get("unknown_frames"),
            "max_fall_probability": binary_summary.get("max_fall_probability"),
            "mean_fall_probability": binary_summary.get("mean_fall_probability"),
            "max_consecutive_fall": binary_summary.get("max_consecutive_fall"),
        },
        "temporal": {
            "event_created": event_created,
            "event_count": fall_event_result.get("event_count", 0),
            "event_id": fall_event_result.get("primary_event_id"),
            "reason": None if event_created else fall_event_result.get("reason"),
        },
        "qwen": {
            "enabled": True,
            "requested": qwen_result.get("qwen_requested"),
            "started": qwen_result.get("qwen_started"),
            "completed": qwen_result.get("qwen_completed"),
            "failed": qwen_result.get("qwen_failed"),
            "model": qwen_result.get("model"),
            "endpoint": qwen_result.get("endpoint"),
            "verdict": qwen_result.get("verdict"),
            "confidence": qwen_result.get("confidence"),
            "analysis_status": qwen_result.get("analysis_status"),
            "summary": qwen_result.get("summary"),
            "transport_calls": qwen_result.get("transport_calls", []),
        },
        "alarm": {
            "should_alarm": should_alarm,
            "reason": alarm_reason,
        },
        "artifacts": {
            "binary_results": "binary_results.jsonl",
            "binary_summary": "binary_summary.json",
            "fall_event": "fall_event.json",
            "qwen_review": "qwen_review.json",
            "qwen_raw_response": "qwen_raw_response.txt",
            "final_result": "final_result.json",
        },
        "failure": failure,
        "archive_status": archive_status,
        "preflight_ref": {
            "binary_model": preflight["binary_model"]["path"],
            "ollama": preflight["ollama"].get("api"),
        },
    }


def copy_keyframes(batch_dir: Path, keyframes_dir: Path, fall_event_result: dict[str, Any]) -> None:
    keyframes_dir.mkdir(parents=True, exist_ok=True)
    if not fall_event_result.get("event_created"):
        write_json(
            keyframes_dir / "manifest.json",
            {
                "event_created": False,
                "reason": fall_event_result.get("reason"),
            },
        )
        return

    archive_record = fall_event_result.get("archive_record") or {}
    primary_event_id = str(archive_record.get("incident_id") or fall_event_result.get("primary_event_id") or "")
    qwen_bucket = str(archive_record.get("qwen_bucket") or "review")
    qwen_dir = batch_dir / "qwen" / qwen_bucket / primary_event_id
    binary_dir = batch_dir / "binary-classification" / "full" / primary_event_id
    source_dir = qwen_dir if qwen_dir.exists() else binary_dir if binary_dir.exists() else None
    files: list[str] = []
    if source_dir is not None:
        for file_path in sorted(source_dir.iterdir()):
            if file_path.is_file() and file_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                shutil.copy2(file_path, keyframes_dir / file_path.name)
                files.append(file_path.name)
    write_json(
        keyframes_dir / "manifest.json",
        {
            "event_created": True,
            "primary_event_id": primary_event_id,
            "qwen_bucket": qwen_bucket if qwen_dir.exists() else None,
            "source_dir": str(source_dir) if source_dir else None,
            "files": files,
        },
    )


def build_summary(batch_dir: Path, preflight: dict[str, Any], video_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "created_at": utc_now_iso(),
        "batch_dir": str(batch_dir),
        "video_count": len(video_results),
        "videos": [
            {
                "video_name": item["video_name"],
                "result_dir": item["result_dir"],
                "event_created": item["fall_event"].get("event_created"),
                "qwen_verdict": item["qwen"].get("verdict"),
                "alarm": item["final_result"]["alarm"]["should_alarm"],
            }
            for item in video_results
        ],
        "preflight": preflight,
    }


def build_performance_summary(video_results: list[dict[str, Any]]) -> dict[str, Any]:
    binary_inference: list[float] = []
    binary_queue_delay: list[float] = []
    local_frame_age: list[float] = []
    qwen_elapsed: list[float] = []
    for item in video_results:
        binary = item.get("binary_summary") or {}
        qwen = item.get("qwen") or {}
        binary_inference.extend(_stat_values(binary.get("inference_ms")))
        binary_queue_delay.extend(_stat_values(binary.get("queue_delay_ms")))
        local_frame_age.extend(_stat_values(binary.get("local_frame_age_ms")))
        elapsed = to_float(qwen.get("elapsed_ms"))
        if elapsed is not None:
            qwen_elapsed.append(elapsed)
    return {
        "binary_inference_ms": stats_summary(binary_inference),
        "binary_queue_delay_ms": stats_summary(binary_queue_delay),
        "local_frame_age_ms": stats_summary(local_frame_age),
        "qwen_elapsed_ms": stats_summary(qwen_elapsed),
    }


def write_markdown_report(path: Path, video_results: list[dict[str, Any]]) -> None:
    lines = [
        "# Video Batch Test Report",
        "",
        "| 视频 | 时长 | 抽帧 | FALL帧 | NON_FALL帧 | UNKNOWN | FallEvent | Qwen调用 | Qwen Verdict | Qwen耗时ms | Safety | 最终告警 | 结果目录 |",
        "| -- | --: | --: | --: | --: | --: | -- | -- | -- | --: | -- | -- | -- |",
    ]
    for item in video_results:
        meta = item["metadata"]
        binary = item["binary_summary"]
        qwen = item["qwen"]
        final_result = item["final_result"]
        lines.append(
            "| {video} | {duration:.2f} | {sampled} | {fall} | {non_fall} | {unknown} | {event} | {called} | {verdict} | {elapsed} | {safety} | {alarm} | {dir} |".format(
                video=item["video_name"],
                duration=float(meta["duration_sec"] or 0.0),
                sampled=binary["sampled_frames"],
                fall=binary["fall_frames"],
                non_fall=binary["non_fall_frames"],
                unknown=binary["unknown_frames"],
                event="YES" if item["fall_event"].get("event_created") else "NO",
                called="YES" if qwen.get("qwen_requested") else "NO",
                verdict=qwen.get("verdict") or "-",
                elapsed=qwen.get("elapsed_ms") or "-",
                safety=(final_result.get("safety") or {}).get("safety_outcome") or "-",
                alarm="YES" if final_result["alarm"]["should_alarm"] else "NO",
                dir=item["result_dir"],
            )
        )
    lines.extend(["", "## Details", ""])
    for item in video_results:
        lines.extend(
            [
                f"## {item['video_name']}",
                "",
                f"- result_dir: `{item['result_dir']}`",
                f"- event_created: `{item['fall_event'].get('event_created')}`",
                f"- qwen_verdict: `{item['qwen'].get('verdict')}`",
                f"- final_alarm: `{item['final_result']['alarm']['should_alarm']}`",
                f"- final_result: `{Path(item['result_dir']) / 'final_result.json'}`",
                "",
            ]
        )
    write_text(path, "\n".join(lines) + "\n")


def extract_relevant_settings(settings: Settings) -> dict[str, Any]:
    return {
        "pipeline_mode": settings.pipeline_mode,
        "post_fall_v2_enabled": settings.post_fall_v2_enabled,
        "post_fall_v2_input_mode": settings.post_fall_v2_input_mode,
        "post_fall_v2_sample_fps": settings.post_fall_v2_sample_fps,
        "post_fall_v2_binary_threshold": settings.post_fall_v2_binary_threshold,
        "post_fall_v2_window_size": settings.post_fall_v2_window_size,
        "post_fall_v2_min_positive_frames": settings.post_fall_v2_min_positive_frames,
        "post_fall_v2_min_consecutive_frames": settings.post_fall_v2_min_consecutive_frames,
        "post_fall_v2_qwen_model": settings.post_fall_v2_qwen_model,
        "post_fall_v2_qwen_base_url": settings.post_fall_v2_qwen_base_url,
        "post_fall_v2_qwen_timeout_seconds": settings.post_fall_v2_qwen_timeout_seconds,
        "post_fall_v2_binary_model_path": settings.post_fall_v2_binary_model_path,
        "post_fall_v2_binary_onnx_providers": settings.post_fall_v2_binary_onnx_providers,
        "follow_target_enabled": settings.follow_target_enabled,
        "capture_backend": settings.capture_backend,
        "capture_process_write_fps": settings.capture_process_write_fps,
        "test_event_root": settings.test_event_root,
    }


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for row in rows:
            handle.write(json.dumps(jsonable(row), ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        write_text(path, "")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def jsonable(value: Any) -> Any:
    if hasattr(value, "to_record"):
        return value.to_record()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return value


def resolve_model_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_videos(video_dir: Path) -> list[Path]:
    return sorted(path for path in video_dir.iterdir() if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS)


def safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in value)
    cleaned = cleaned.strip("._")
    return cleaned or "video"


def to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def first_non_empty(values: Any, default: Any = None) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def max_consecutive(labels: list[str], target: str) -> int:
    best = current = 0
    for label in labels:
        if label == target:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def stats_summary(values: list[float]) -> dict[str, Any]:
    cleaned = sorted(float(value) for value in values if value is not None)
    if not cleaned:
        return {"count": 0, "avg": None, "p50": None, "p95": None, "max": None}
    return {
        "count": len(cleaned),
        "avg": round(sum(cleaned) / len(cleaned), 3),
        "p50": round(percentile(cleaned, 0.50), 3),
        "p95": round(percentile(cleaned, 0.95), 3),
        "max": round(max(cleaned), 3),
    }


def percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * max(0.0, min(1.0, fraction))
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _stat_values(summary: Any) -> list[float]:
    if isinstance(summary, dict):
        values = [
            to_float(summary.get("avg")),
            to_float(summary.get("p50")),
            to_float(summary.get("p95")),
            to_float(summary.get("max")),
        ]
        return [value for value in values if value is not None]
    value = to_float(summary)
    return [value] if value is not None else []


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def build_summary(batch_dir: Path, preflight: dict[str, Any], video_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "created_at": utc_now_iso(),
        "batch_dir": str(batch_dir),
        "video_count": len(video_results),
        "videos": [
            {
                "video_name": item["video_name"],
                "result_dir": item["result_dir"],
                "event_created": item["fall_event"].get("event_created"),
                "qwen_verdict": item["qwen"].get("verdict"),
                "alarm": item["final_result"]["alarm"]["should_alarm"],
            }
            for item in video_results
        ],
        "preflight": preflight,
    }


class QwenTransportRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        started = time.perf_counter()
        response = requests.post(OLLAMA_ENDPOINT, json=payload, timeout=timeout)
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        entry = {
            "request_index": len(self.calls) + 1,
            "http_status": response.status_code,
            "elapsed_ms": elapsed_ms,
            "ok": response.ok,
            "raw_response_text": response.text,
        }
        self.calls.append(entry)
        if response.status_code >= 400:
            raise requests.HTTPError(f"HTTP {response.status_code}: {response.text}", response=response)
        try:
            return response.json()
        except Exception as exc:
            raise ValueError(f"invalid JSON from Ollama: {exc}") from exc

    def raw_text(self) -> str:
        return "\n\n".join(
            f"--- call {entry['request_index']} status={entry['http_status']} elapsed_ms={entry['elapsed_ms']} ---\n{entry['raw_response_text']}"
            for entry in self.calls
        )


def build_final_result(
    *,
    video_path: Path,
    metadata: dict[str, Any],
    binary_summary: dict[str, Any],
    fall_event_result: dict[str, Any],
    qwen_result: dict[str, Any],
    archive_status: dict[str, Any],
    preflight: dict[str, Any],
    failure: dict[str, Any] | None,
) -> dict[str, Any]:
    event_created = bool(fall_event_result.get("event_created"))
    event_payload = fall_event_result.get("event") or {}
    safety = event_payload.get("safety_decision") or {}
    qwen_review = qwen_result.get("qwen_review") or {}
    qwen_analysis = qwen_review.get("qwen_analysis") or {}
    binary_model = preflight.get("binary_model") if isinstance(preflight, dict) else {}
    binary_active_providers = list(binary_model.get("active_providers") or [])
    binary_requested_providers = list(binary_model.get("requested_providers") or [])
    binary_available_providers = list(binary_model.get("available_providers") or [])
    binary_provider_warning = binary_model.get("load_error")
    binary_provider_degraded = bool(binary_requested_providers) and bool(binary_active_providers) and (
        binary_active_providers[0] != binary_requested_providers[0]
    )
    report_binary_provider = first_non_empty(binary_active_providers, binary_summary.get("provider"))
    return {
        "video": {
            "file_name": video_path.name,
            "path": str(video_path),
            "duration_sec": metadata["duration_sec"],
            "fps": metadata["fps"],
            "resolution": f'{metadata["width"]}x{metadata["height"]}',
            "frame_count": metadata["frame_count"],
        },
        "binary": {
            "enabled": True,
            "model": preflight["binary_model"]["path"],
            "provider": report_binary_provider,
            "requested_providers": binary_requested_providers,
            "active_providers": binary_active_providers,
            "available_providers": binary_available_providers,
            "provider_degraded": binary_provider_degraded,
            "provider_warning": binary_provider_warning,
            "sample_fps": binary_summary.get("sample_fps"),
            "sampled_frames": binary_summary.get("sampled_frames"),
            "processed_frames": binary_summary.get("processed_frames"),
            "fall_frames": binary_summary.get("fall_frames"),
            "non_fall_frames": binary_summary.get("non_fall_frames"),
            "unknown_frames": binary_summary.get("unknown_frames"),
            "max_fall_probability": binary_summary.get("max_fall_probability"),
            "mean_fall_probability": binary_summary.get("mean_fall_probability"),
            "max_consecutive_fall": binary_summary.get("max_consecutive_fall"),
        },
        "temporal": {
            "event_created": event_created,
            "event_count": fall_event_result.get("event_count", 0),
            "event_id": fall_event_result.get("primary_event_id"),
            "reason": None if event_created else fall_event_result.get("reason"),
        },
        "qwen": {
            "enabled": True,
            "requested": bool(qwen_result.get("qwen_requested")),
            "started": bool(qwen_result.get("qwen_started")),
            "completed": bool(qwen_result.get("qwen_completed")),
            "failed": bool(qwen_result.get("qwen_failed")),
            "model": qwen_result.get("model"),
            "endpoint": qwen_result.get("endpoint"),
            "verdict": qwen_result.get("verdict"),
            "confidence": qwen_result.get("confidence"),
            "analysis_status": qwen_result.get("analysis_status"),
            "summary": qwen_result.get("summary"),
            "elapsed_ms": qwen_result.get("elapsed_ms"),
            "high_risk_fall": qwen_result.get("high_risk_fall"),
            "error_message": qwen_result.get("error_message"),
            "qwen_start_frames_received": qwen_result.get("qwen_start_frames_received"),
            "qwen_end_frames_received": qwen_result.get("qwen_end_frames_received"),
            "frames_received_during_qwen": qwen_result.get("frames_received_during_qwen"),
        },
        "safety": {
            "high_risk_fall": qwen_analysis.get("high_risk_fall"),
            "safety_outcome": safety.get("outcome"),
            "safety_path": safety.get("path"),
            "safety_reason": safety.get("reason"),
            "observation_elapsed_ms": safety.get("observation_elapsed_ms"),
        },
        "alarm": {
            "should_alarm": bool(event_created and str(safety.get("outcome") or "").lower() == "alert"),
            "reason": str(safety.get("reason") or ("no_event" if not event_created else "qwen_not_confirmed")),
        },
        "performance": {
            "binary_inference_ms": binary_summary.get("inference_ms"),
            "binary_queue_delay_ms": binary_summary.get("queue_delay_ms"),
            "local_frame_age_ms": binary_summary.get("local_frame_age_ms"),
            "qwen_elapsed_ms": qwen_result.get("elapsed_ms"),
            "frames_received_during_qwen": qwen_result.get("frames_received_during_qwen"),
            "resource": (archive_status or {}).get("latest_performance"),
        },
        "artifacts": {
            "binary_results": "binary_results.jsonl",
            "binary_summary": "binary_summary.json",
            "fall_event": "fall_event.json",
            "qwen_review": "qwen_review.json",
            "qwen_raw_response": "qwen_raw_response.txt",
            "final_result": "final_result.json",
        },
        "failure": failure,
        "archive_status": archive_status,
        "preflight_ref": {
            "binary_model": preflight["binary_model"]["path"],
            "ollama": (preflight.get("ollama") or {}).get("api"),
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
