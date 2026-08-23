from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.camera.source_manager import CameraSourceManager
from app.camera.source_models import CameraSourceConfig
from app.core.config import Settings
from app.detection.realtime_result_store import RealtimeResultStore
from app.events.pipeline import EventPipelineService
from app.post_fall_v2.post_fall_runtime_service import PostFallV2RuntimeService
from app.post_fall_v2.qwen_fall_analyzer import PFV2QwenFallAnalyzer
from app.post_fall_v2.vlm_review_service import VLMReviewService
from app.streaming.result_channel_manager import ResultChannelManager


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a local video through the PFV2 binary, collector, and local-Qwen enrichment chain."
    )
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--camera-id", default="pfv2_replay")
    parser.add_argument("--model", default="qwen-vision-cn:latest")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not args.video.is_file():
        return _emit({"status": "FAIL", "reason": "video_not_found"}, args.output)

    settings = replace(
        Settings(),
        pipeline_mode="post_fall_v2",
        post_fall_v2_enabled=True,
        post_fall_v2_vlm_enabled=True,
        post_fall_v2_qwen_enabled=True,
        post_fall_v2_qwen_provider="qwen_keyframe",
        post_fall_v2_qwen_model=args.model,
        post_fall_v2_qwen_base_url=args.endpoint,
        post_fall_v2_qwen_timeout_seconds=max(1.0, float(args.timeout)),
        post_fall_v2_keyframe_post_collection_enabled=True,
        post_fall_v2_event_buffer_seconds=max(8.0, Settings().post_fall_v2_event_buffer_seconds),
        event_pipeline_enabled=False,
        event_delivery_enabled=False,
        main_system_alert_enabled=False,
        qwen_media_input_enabled=True,
        qwen_media_privacy_approved=True,
    )
    source_manager = CameraSourceManager(settings)
    realtime_store = RealtimeResultStore()
    result_channels = ResultChannelManager()
    event_pipeline = EventPipelineService(settings)
    vlm = VLMReviewService(
        enabled=True,
        timeout_seconds=settings.post_fall_v2_qwen_timeout_seconds,
    )
    runtime = PostFallV2RuntimeService(
        settings=settings,
        source_manager=source_manager,
        realtime_store=realtime_store,
        result_channels=result_channels,
        event_pipeline=event_pipeline,
        vlm_review_service=vlm,
    )
    vlm.analyzer = PFV2QwenFallAnalyzer.from_config(
        endpoint_url=settings.post_fall_v2_qwen_base_url,
        model_name=settings.post_fall_v2_qwen_model,
        timeout_seconds=settings.post_fall_v2_qwen_timeout_seconds,
        image_provider=runtime.qwen_images_for_incident,
    )

    try:
        source_manager.start_source(CameraSourceConfig(camera_id=args.camera_id, source_url=str(args.video.resolve())))
        runtime.start_for_camera(args.camera_id)
        event = _wait_for_terminal_event(runtime, args.timeout)
        runtime_status = runtime.status(args.camera_id)
        result = realtime_store.latest_published(args.camera_id)
        report = {
            "status": _status_for(event),
            "source_type": "local_replay",
            "video_name": args.video.name,
            "binary_results_count": runtime_status["frames_processed"],
            "confirmed_event_count": len(runtime.events()),
            "incident_ids": [item.incident_id for item in runtime.events()],
            "event": _event_record(event),
            "vision_result": _vision_record(result),
            "outbox_incident_ids": [record.incident_id for record in event_pipeline.outbox.records()],
            "target_camera_rtsp": "NOT_RUN",
            "production_threshold": "NOT_VERIFIED",
            "qwen_parse_diagnostic": _qwen_parse_diagnostic(vlm.analyzer),
        }
    except Exception as exc:
        report = {
            "status": "FAIL",
            "source_type": "local_replay",
            "video_name": args.video.name,
            "reason": type(exc).__name__,
        }
    finally:
        runtime.stop_all()
        source_manager.stop_all()
        event_pipeline.stop()
    return _emit(report, args.output)


def _wait_for_terminal_event(runtime: PostFallV2RuntimeService, timeout_seconds: float):
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    event = None
    while time.monotonic() < deadline:
        events = runtime.events()
        if events:
            event = events[-1]
            if event.vlm_status in {"completed", "failed", "timeout", "parse_failed"}:
                return event
        time.sleep(0.05)
    return event


def _status_for(event) -> str:
    if event is None:
        return "FAIL"
    if event.vlm_status == "completed" and event.keyframes is not None and event.keyframes.status == "ready":
        return "PASS"
    if event.vlm_status in {"failed", "timeout", "parse_failed"}:
        return "PARTIAL"
    return "PARTIAL"


def _event_record(event) -> dict | None:
    if event is None:
        return None
    keyframes = event.keyframes
    return {
        "incident_id": event.incident_id,
        "fall_state": event.state,
        "vlm_status": event.vlm_status,
        "qwen_model": event.vlm_analysis.model_name if event.vlm_analysis else None,
        "qwen_latency_ms": event.vlm_analysis.latency_ms if event.vlm_analysis else None,
        "qwen_confidence": event.vlm_analysis.confidence if event.vlm_analysis else None,
        "qwen_summary": event.vlm_analysis.summary if event.vlm_analysis else None,
        "keyframe_status": keyframes.status if keyframes else None,
        "requested_offsets_ms": keyframes.requested_offsets_ms if keyframes else [],
        "resolved_offsets_ms": keyframes.resolved_offsets_ms if keyframes else [],
        "missing_offsets_ms": keyframes.missing_offsets_ms if keyframes else [],
        "keyframes": [
            {
                "offset_ms": item.offset_ms,
                "actual_offset_ms": item.actual_offset_ms,
                "timing_error_ms": item.timing_error_ms,
                "available": bool(item.frame_id),
                "missing_reason": item.missing_reason,
            }
            for item in (keyframes.frames if keyframes else [])
        ],
    }


def _vision_record(result) -> dict | None:
    if result is None or not result.objects:
        return None
    decision = result.objects[0].fall_decision or {}
    return {
        "pipeline": result.detector.get("pipeline"),
        "binary_label": result.detector.get("binary_label"),
        "fall_probability": result.detector.get("fall_probability"),
        "incident_id": decision.get("incident_id"),
        "keyframe_status": decision.get("keyframe_status"),
        "vlm_status": decision.get("vlm_status"),
        "vlm_summary": decision.get("vlm_summary"),
    }


def _qwen_parse_diagnostic(analyzer) -> dict | None:
    keyframe_analyzer = getattr(analyzer, "analyzer", None)
    diagnostic = getattr(keyframe_analyzer, "last_post_fall_diagnostic", None)
    return diagnostic if isinstance(diagnostic, dict) else None


def _emit(report: dict, output: Path | None) -> int:
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
