from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "A": {
        "pose_worker_fps": 2.0,
        "pose_result_ttl_ms": 500,
        "pose_max_frame_age_ms": 500,
        "pose_max_tracking_frame_delta": 2,
    },
    "B": {
        "pose_worker_fps": 3.0,
        "pose_result_ttl_ms": 800,
        "pose_max_frame_age_ms": 800,
        "pose_max_tracking_frame_delta": 2,
    },
    "C": {
        "pose_worker_fps": 3.0,
        "pose_result_ttl_ms": 1000,
        "pose_max_frame_age_ms": 800,
        "pose_max_tracking_frame_delta": 3,
    },
}

BLOCKING_STALE_REASONS = (
    "pose_frame_stale",
    "pose_frame_stale_detection_lag",
    "pose_frame_stale_capture_stale",
    "pose_frame_stale_capture_disconnected",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay a local video through detection/tracking/pose worker/publisher for pose runtime profile A/B.",
    )
    parser.add_argument("--video", default="datasets/ur_fall/videos/fall-01.mp4")
    parser.add_argument("--camera-id", default="pose_replay")
    parser.add_argument("--output", default="evaluations/pose_runtime_replay_profiles_20260705.json")
    parser.add_argument("--profiles", default="A,B,C", help="Comma-separated default profiles or custom name:key=value,...")
    parser.add_argument("--provider", default=None, help="Optional pose provider override.")
    parser.add_argument("--device", default=None, help="Optional detector/pose device override, for example cpu or cuda:0.")
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--max-sampled-frames", type=int, default=20)
    parser.add_argument("--replay-fps", type=float, default=0.0, help="Pace sampled frames like runtime video. 0 means as fast as possible.")
    parser.add_argument("--detection-age-offset-ms", type=float, default=0.0)
    parser.add_argument("--tracking-lag-frames", type=int, default=0)
    parser.add_argument("--publish-delay-ms", type=float, default=0.0)
    args = parser.parse_args()

    from app.core.config import get_settings

    base_settings = get_settings()
    if args.device:
        base_settings = replace_devices(base_settings, args.device)
    if args.provider:
        base_settings = replace(base_settings, pose_provider=args.provider)

    profiles = parse_profiles(args.profiles)
    results = []
    for profile_name, overrides in profiles:
        settings = replace(base_settings, **overrides)
        results.append(
            replay_profile(
                settings=settings,
                profile_name=profile_name,
                video_path=ROOT / args.video,
                camera_id=f"{args.camera_id}_{profile_name}",
                frame_stride=args.frame_stride,
                max_sampled_frames=args.max_sampled_frames,
                replay_fps=args.replay_fps,
                detection_age_offset_ms=args.detection_age_offset_ms,
                tracking_lag_frames=args.tracking_lag_frames,
                publish_delay_ms=args.publish_delay_ms,
            )
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "video": str((ROOT / args.video).resolve()),
        "base_pose_provider": base_settings.pose_provider,
        "device_override": args.device,
        "provider_override": args.provider,
        "replay_controls": {
            "frame_stride": args.frame_stride,
            "max_sampled_frames": args.max_sampled_frames,
            "replay_fps": args.replay_fps,
            "detection_age_offset_ms": args.detection_age_offset_ms,
            "tracking_lag_frames": args.tracking_lag_frames,
            "publish_delay_ms": args.publish_delay_ms,
        },
        "profiles": results,
        "recommendation": recommend_profile(results),
    }
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"profiles": summarize_for_stdout(results), "recommendation": report["recommendation"]}, ensure_ascii=False, indent=2))
    return 0


def replay_profile(
    *,
    settings,
    profile_name: str,
    video_path: Path,
    camera_id: str,
    frame_stride: int,
    max_sampled_frames: int,
    replay_fps: float,
    detection_age_offset_ms: float,
    tracking_lag_frames: int,
    publish_delay_ms: float,
) -> dict[str, Any]:
    from app.detection.object_detector import YoloPersonDetector
    from app.detection.realtime_result_store import DetectionSnapshot, ObjectSnapshot, RealtimeResultStore
    from app.pose.placeholders import pose_has_visible_keypoints
    from app.schemas.common import utc_now_iso
    from app.services.pose_service import PoseService
    from app.services.pose_worker_service import PoseWorkerService
    from app.services.result_publisher_service import ResultPublisherService
    from app.services.tracking_service import TrackingService
    from app.streaming.result_channel_manager import ResultChannelManager

    detector = YoloPersonDetector(settings)
    tracker = TrackingService(settings)
    pose_service = PoseService(settings)
    store = RealtimeResultStore()
    worker = PoseWorkerService(settings, source_manager=None, realtime_store=store, pose_service=pose_service)
    publisher = ResultPublisherService(settings, store, ResultChannelManager())

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {
            "profile_name": profile_name,
            "error": f"could not open video: {video_path}",
            "gate": runtime_gate(0.0, 0.0, {}, 0.0),
        }

    sampled_frames = 0
    frame_index = 0
    published_frames = 0
    published_pose_available_frames = 0
    detection_person_frames = 0
    tracking_person_frames = 0
    frame_latencies_ms: list[float] = []
    publish_pose_quality_counts: Counter[str] = Counter()
    started = time.perf_counter()
    try:
        while sampled_frames < max_sampled_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % max(1, frame_stride) != 0:
                frame_index += 1
                continue

            frame_started = time.perf_counter()
            timestamp = utc_now_iso()
            frame_height, frame_width = frame.shape[:2]
            detections = detector.detect(frame)
            if any(item.label == "person" for item in detections):
                detection_person_frames += 1
            tracked = tracker.enrich(camera_id, detections, frame=frame)
            if any(item.label == "person" and item.track_id is not None for item in tracked):
                tracking_person_frames += 1

            monotonic_at = time.monotonic() - max(0.0, detection_age_offset_ms) / 1000
            store.update_detection(
                DetectionSnapshot(
                    camera_id=camera_id,
                    frame_seq=frame_index,
                    frame_width=frame_width,
                    frame_height=frame_height,
                    timestamp=timestamp,
                    monotonic_at=monotonic_at,
                    frame=frame,
                    objects=detections,
                    detector={"source": "replay_pose_runtime_profiles"},
                )
            )
            store.update_tracking(
                ObjectSnapshot(
                    camera_id=camera_id,
                    frame_seq=frame_index - max(0, tracking_lag_frames),
                    frame_width=frame_width,
                    frame_height=frame_height,
                    timestamp=timestamp,
                    monotonic_at=monotonic_at,
                    objects=tracked,
                )
            )
            worker._tick(camera_id)
            if publish_delay_ms > 0:
                time.sleep(publish_delay_ms / 1000)
            result = publisher._build_result(camera_id)
            if result is not None:
                published_frames += 1
                if any(pose_has_visible_keypoints(item.pose if isinstance(item.pose, dict) else None) for item in result.objects):
                    published_pose_available_frames += 1
                for item in result.objects:
                    pose = item.pose if isinstance(item.pose, dict) else None
                    if pose is not None:
                        publish_pose_quality_counts[str(pose.get("pose_quality_level") or "unknown")] += 1
            frame_latencies_ms.append((time.perf_counter() - frame_started) * 1000)
            sampled_frames += 1
            frame_index += 1
            if replay_fps > 0:
                target_interval = 1 / max(replay_fps, 0.1)
                elapsed = time.perf_counter() - frame_started
                if elapsed < target_interval:
                    time.sleep(target_interval - elapsed)
    finally:
        cap.release()

    pose_status = pose_service.status(camera_id)
    published_pose_ratio = (
        round(published_pose_available_frames / published_frames, 4)
        if published_frames
        else 0.0
    )
    skip_reasons = dict(pose_status.skip_reasons)
    avg_frame_ms = round(statistics.mean(frame_latencies_ms), 2) if frame_latencies_ms else 0.0
    elapsed_seconds = round(time.perf_counter() - started, 3)
    return {
        "profile_name": profile_name,
        "settings": {
            "pose_provider": settings.pose_provider,
            "pose_model_path": active_pose_model_path(settings, settings.pose_provider),
            "pose_worker_fps": settings.pose_worker_fps,
            "pose_fps": settings.pose_fps,
            "pose_result_ttl_ms": settings.pose_result_ttl_ms,
            "pose_max_frame_age_ms": settings.pose_max_frame_age_ms,
            "pose_max_tracking_frame_delta": settings.pose_max_tracking_frame_delta,
            "pose_skip_when_inference_busy": settings.pose_skip_when_inference_busy,
        },
        "sampled_frames": sampled_frames,
        "detection_person_frames": detection_person_frames,
        "tracking_person_frames": tracking_person_frames,
        "published_frames": published_frames,
        "published_pose_available_frames": published_pose_available_frames,
        "published_pose_available_ratio": published_pose_ratio,
        "worker_tick_count": pose_status.worker_tick_count,
        "inference_attempt_count": pose_status.inference_attempt_count,
        "inference_success_count": pose_status.inference_success_count,
        "pose_target_object_count": pose_status.pose_target_object_count,
        "pose_attached_object_count": pose_status.pose_attached_object_count,
        "pose_valid_rate": pose_status.pose_valid_rate,
        "inference_success_rate": pose_status.inference_success_rate,
        "last_inference_latency_ms": pose_status.last_inference_latency_ms,
        "skip_reasons": skip_reasons,
        "published_pose_quality_counts": dict(publish_pose_quality_counts),
        "avg_frame_process_ms": avg_frame_ms,
        "elapsed_seconds": elapsed_seconds,
        "gate": runtime_gate(
            pose_status.pose_valid_rate,
            published_pose_ratio,
            skip_reasons,
            pose_status.skipped_due_to_busy,
        ),
    }


def parse_profiles(value: str) -> list[tuple[str, dict[str, Any]]]:
    profiles: list[tuple[str, dict[str, Any]]] = []
    raw_items = value.split(";") if ":" in value else value.split(",")
    for raw_item in raw_items:
        item = raw_item.strip()
        if not item:
            continue
        if ":" not in item:
            name = item.strip()
            profiles.append((name, dict(DEFAULT_PROFILES.get(name, {}))))
            continue
        name, raw_overrides = item.split(":", 1)
        overrides: dict[str, Any] = {}
        for pair in raw_overrides.split(","):
            if not pair.strip():
                continue
            key, raw_value = pair.split("=", 1)
            overrides[key.strip()] = coerce_profile_value(raw_value.strip())
        profiles.append((name.strip(), overrides))
    return profiles or [(name, dict(overrides)) for name, overrides in DEFAULT_PROFILES.items()]


def coerce_profile_value(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def runtime_gate(
    pose_valid_rate: float,
    published_pose_available_ratio: float,
    skip_reasons: dict[str, int],
    busy_skip_count: float,
) -> dict[str, Any]:
    blockers: list[str] = []
    if pose_valid_rate < 0.70:
        blockers.append("pose_valid_rate_below_0.70")
    if published_pose_available_ratio < 0.60:
        blockers.append("published_pose_available_ratio_below_0.60")
    if busy_skip_count > 0:
        blockers.append("busy_skip_present")
    for reason in (*BLOCKING_STALE_REASONS, "frame_tracking_desync", "pose_track_mismatch"):
        if int(skip_reasons.get(reason) or 0) > 0:
            blockers.append(reason)
    return {
        "passed": not blockers,
        "blockers": blockers,
        "recommendation": gate_recommendation(blockers),
    }


def gate_recommendation(blockers: list[str]) -> str:
    if not blockers:
        return "profile is acceptable for wider replay/provider validation"
    if any(reason in blockers for reason in BLOCKING_STALE_REASONS):
        return "classify stale as source/capture/detection lag before increasing frame-age limits"
    if "frame_tracking_desync" in blockers:
        return "increase POSE_MAX_TRACKING_FRAME_DELTA only after checking tracker lag"
    if "published_pose_available_ratio_below_0.60" in blockers:
        return "raise POSE_RESULT_TTL_MS or increase pose worker throughput"
    if "pose_valid_rate_below_0.70" in blockers:
        return "fix pose attachment before using pose for LSTM/fusion"
    if "busy_skip_present" in blockers:
        return "reduce inference lock contention before retraining"
    return "fix runtime blockers before retraining"


def recommend_profile(results: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        results,
        key=lambda item: (
            bool(item.get("gate", {}).get("passed")),
            float(item.get("published_pose_available_ratio") or 0.0),
            float(item.get("pose_valid_rate") or 0.0),
            -float(item.get("avg_frame_process_ms") or 0.0),
        ),
        reverse=True,
    )
    if not ranked:
        return {"selected_profile": None, "reason": "no replay results"}
    best = ranked[0]
    return {
        "selected_profile": best.get("profile_name"),
        "passed": best.get("gate", {}).get("passed"),
        "reason": best.get("gate", {}).get("recommendation"),
        "published_pose_available_ratio": best.get("published_pose_available_ratio"),
        "pose_valid_rate": best.get("pose_valid_rate"),
    }


def summarize_for_stdout(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(item.get("profile_name")): {
            "pose_valid_rate": item.get("pose_valid_rate"),
            "published_pose_available_ratio": item.get("published_pose_available_ratio"),
            "skip_reasons": item.get("skip_reasons"),
            "avg_frame_process_ms": item.get("avg_frame_process_ms"),
            "gate": item.get("gate"),
        }
        for item in results
    }


def replace_devices(settings, device: str):
    return replace(
        settings,
        yolo_device=device,
        yolo_fall_device=device,
        yolo_pose_device=device,
        yolo11_pose_device=device,
        rtmpose_device=device,
    )


def active_pose_model_path(settings, provider: str) -> str | None:
    normalized = str(provider or "").strip().lower()
    if normalized in {"yolo11_legacy", "branch4_legacy"}:
        return getattr(settings, "yolo11_pose_model_path", None)
    if normalized == "yolo":
        return getattr(settings, "yolo_pose_model_path", None)
    if normalized == "rtmpose_onnx":
        return getattr(settings, "rtmpose_onnx_model_path", None)
    if normalized in {"mmpose", "mmpose_finetuned"}:
        return getattr(settings, "rtmpose_checkpoint_path", None)
    return (
        getattr(settings, "yolo11_pose_model_path", None)
        or getattr(settings, "yolo_pose_model_path", None)
        or getattr(settings, "rtmpose_onnx_model_path", None)
    )


if __name__ == "__main__":
    raise SystemExit(main())
