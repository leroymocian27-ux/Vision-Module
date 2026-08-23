from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]

import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class ProviderVideoResult:
    provider: str
    video_id: str
    label: str
    split: str
    sampled_frames: int = 0
    pose_frames: int = 0
    pose_object_frames: int = 0
    pose_valid_rate: float = 0.0
    inference_attempt_count: int = 0
    inference_success_count: int = 0
    pose_target_object_count: int = 0
    pose_attached_object_count: int = 0
    avg_skeleton_confidence: float = 0.0
    avg_latency_ms: float = 0.0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    pose_quality_counts: dict[str, int] = field(default_factory=dict)
    errors: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare pose providers on representative project videos.")
    parser.add_argument("--manifest", default="data/phase7_labels/phase7_video_labels.jsonl")
    parser.add_argument("--output", default="evaluations/phase10_pose_provider_comparison_001.json")
    parser.add_argument("--frame-stride", type=int, default=20)
    parser.add_argument("--max-frames-per-video", type=int, default=80, help="Maximum sampled frames per video.")
    parser.add_argument("--limit-fall", type=int, default=4)
    parser.add_argument("--limit-non-fall", type=int, default=4)
    parser.add_argument(
        "--providers",
        default="yolo11_legacy,yolo,branch4_legacy,rtmpose_onnx",
        help="Comma-separated pose providers to compare.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Optional detector/pose device override, for example cpu or cuda:0.",
    )
    parser.add_argument(
        "--pose-fps",
        type=float,
        default=1000000.0,
        help="Pose FPS used inside offline provider comparison. High default avoids runtime throttle bias.",
    )
    args = parser.parse_args()

    from app.core.config import get_settings
    from app.detection.object_detector import YoloPersonDetector
    from app.services.pose_service import PoseService
    from app.services.tracking_service import TrackingService

    base_settings = get_settings()
    if args.device:
        base_settings = replace(
            base_settings,
            yolo_device=args.device,
            yolo_fall_device=args.device,
            yolo_pose_device=args.device,
            yolo11_pose_device=args.device,
            rtmpose_device=args.device,
        )
    base_settings = replace(base_settings, pose_fps=args.pose_fps)
    detector = YoloPersonDetector(base_settings)
    manifest = _read_jsonl(ROOT / args.manifest)
    candidates = _select_representative_videos(manifest, args.limit_fall, args.limit_non_fall)
    requested_providers = _parse_providers(args.providers)

    results: list[ProviderVideoResult] = []
    provider_settings = [
        (provider, replace(base_settings, pose_provider=provider))
        for provider in requested_providers
        if provider != "mmpose_finetuned"
    ]
    adapted_ckpt = ROOT / "models" / "rtmpose" / "rtmpose-l-pose-adapted-best.pth"
    adapted_cfg = ROOT / "models" / "rtmpose" / "rtmpose_l_pose_adaptation_384x288.py"
    if "mmpose_finetuned" in requested_providers and adapted_ckpt.exists() and adapted_cfg.exists():
        provider_settings.append(
            (
                "mmpose_finetuned",
                replace(
                    base_settings,
                    pose_provider="mmpose",
                    rtmpose_config_path=str(adapted_cfg),
                    rtmpose_checkpoint_path=str(adapted_ckpt),
                    rtmpose_device=args.device or base_settings.rtmpose_device or "cuda:0",
                ),
            )
        )
    provider_model_paths = {
        provider: _active_pose_model_path(settings, provider)
        for provider, settings in provider_settings
    }

    for provider, settings in provider_settings:
        for row in candidates:
            tracker = TrackingService(settings)
            pose = PoseService(settings)
            results.append(
                _evaluate_video(
                    detector=detector,
                    tracker=tracker,
                    pose=pose,
                    provider=provider,
                    row=row,
                    frame_stride=args.frame_stride,
                    max_frames=args.max_frames_per_video,
                )
            )

    summary = _summarize(results)
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "run_config": {
                    "device": args.device,
                    "providers": requested_providers,
                    "provider_model_paths": provider_model_paths,
                    "frame_stride": args.frame_stride,
                    "max_frames_per_video": args.max_frames_per_video,
                    "limit_fall": args.limit_fall,
                    "limit_non_fall": args.limit_non_fall,
                    "manifest": args.manifest,
                },
                "results": [asdict(item) for item in results],
                "summary": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _select_representative_videos(rows: list[dict], limit_fall: int, limit_non_fall: int) -> list[dict]:
    usable = [row for row in rows if row.get("usable_for_training")]
    falls = [row for row in usable if row.get("binary_label") == "fall"][:limit_fall]
    non_falls = [row for row in usable if row.get("binary_label") == "non_fall"][:limit_non_fall]
    return non_falls + falls


def _parse_providers(value: str) -> list[str]:
    providers = []
    for item in value.split(","):
        provider = item.strip()
        if provider and provider not in providers:
            providers.append(provider)
    return providers or ["yolo11_legacy"]


def _active_pose_model_path(settings, provider: str) -> str | None:
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


def _resolve_video_path(row: dict) -> Path:
    video_id = str(row["video_id"]).replace("\\", "/")
    if video_id.startswith("ur_fall/"):
        return ROOT / "datasets" / "ur_fall" / "videos" / Path(video_id).name
    if video_id.startswith("gmdcsa24/"):
        return ROOT / "datasets" / "gmdcsa24" / "videos" / Path(video_id).name
    return ROOT / video_id


def _evaluate_video(
    *,
    detector,
    tracker,
    pose,
    provider: str,
    row: dict,
    frame_stride: int,
    max_frames: int,
) -> ProviderVideoResult:
    camera_id = f"{provider}_{Path(row['video_id']).stem}"
    result = ProviderVideoResult(
        provider=provider,
        video_id=row["video_id"],
        label=row["binary_label"],
        split=row["split"],
    )
    video_path = _resolve_video_path(row)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        result.errors = f"could not open video: {video_path}"
        return result

    conf_sum = 0.0
    conf_count = 0
    latency_sum = 0.0
    quality_counts: Counter[str] = Counter()
    frame_index = 0
    try:
        while result.sampled_frames < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % max(1, frame_stride) != 0:
                frame_index += 1
                continue
            objects = detector.detect(frame)
            objects = tracker.enrich(camera_id, objects, frame=frame)
            started = time.perf_counter()
            objects = pose.enrich(camera_id, frame, objects, frame_seq=frame_index, tracking_frame_seq=frame_index)
            latency_sum += (time.perf_counter() - started) * 1000
            result.sampled_frames += 1
            for item in objects:
                if item.pose is None:
                    continue
                quality = str(item.pose.get("pose_quality_level") or "unknown")
                quality_counts[quality] += 1
                result.pose_object_frames += 1
                if not _pose_has_visible_keypoints(item.pose):
                    continue
                result.pose_frames += 1
                conf_sum += float(item.pose.get("skeleton_confidence") or 0.0)
                conf_count += 1
            frame_index += 1
    except Exception as exc:
        result.errors = str(exc)
    finally:
        cap.release()

    if conf_count:
        result.avg_skeleton_confidence = round(conf_sum / conf_count, 4)
    if result.sampled_frames:
        result.avg_latency_ms = round(latency_sum / result.sampled_frames, 2)
    status = pose.status(camera_id)
    result.inference_attempt_count = status.inference_attempt_count
    result.inference_success_count = status.inference_success_count
    result.pose_target_object_count = status.pose_target_object_count
    result.pose_attached_object_count = status.pose_attached_object_count
    result.pose_valid_rate = status.pose_valid_rate
    result.skip_reasons = dict(status.skip_reasons)
    result.pose_quality_counts = dict(quality_counts)
    return result


def _summarize(results: list[ProviderVideoResult]) -> dict:
    by_provider = defaultdict(list)
    for item in results:
        by_provider[item.provider].append(item)

    summary = {}
    for provider, rows in by_provider.items():
        pose_frame_total = sum(item.pose_frames for item in rows)
        pose_object_frame_total = sum(item.pose_object_frames for item in rows)
        sampled_total = sum(item.sampled_frames for item in rows)
        target_total = sum(item.pose_target_object_count for item in rows)
        attached_total = sum(item.pose_attached_object_count for item in rows)
        skip_reasons: Counter[str] = Counter()
        pose_quality_counts: Counter[str] = Counter()
        for item in rows:
            skip_reasons.update(item.skip_reasons or {})
            pose_quality_counts.update(item.pose_quality_counts or {})
        summary[provider] = {
            "videos": len(rows),
            "pose_frames": pose_frame_total,
            "pose_object_frames": pose_object_frame_total,
            "sampled_frames": sampled_total,
            "pose_frame_ratio": round(pose_frame_total / sampled_total, 4) if sampled_total else 0.0,
            "pose_object_frame_ratio": round(pose_object_frame_total / sampled_total, 4) if sampled_total else 0.0,
            "pose_target_object_count": target_total,
            "pose_attached_object_count": attached_total,
            "pose_valid_rate": round(attached_total / target_total, 4) if target_total else 0.0,
            "inference_attempt_count": sum(item.inference_attempt_count for item in rows),
            "inference_success_count": sum(item.inference_success_count for item in rows),
            "avg_pose_frames_per_video": round(pose_frame_total / len(rows), 2) if rows else 0.0,
            "avg_latency_ms": round(sum(item.avg_latency_ms for item in rows) / len(rows), 2) if rows else 0.0,
            "avg_skeleton_confidence": round(
                sum(item.avg_skeleton_confidence for item in rows if item.avg_skeleton_confidence) / max(1, sum(1 for item in rows if item.avg_skeleton_confidence)),
                4,
            ),
            "skip_reasons": dict(skip_reasons),
            "pose_quality_counts": dict(pose_quality_counts),
            "errors": dict(Counter(item.errors for item in rows if item.errors)),
        }
    return summary


def _pose_has_visible_keypoints(pose: dict, threshold: float = 0.2) -> bool:
    quality_level = str(pose.get("pose_quality_level") or "").strip().lower()
    if quality_level in {"pose_absent", "low_quality", "pose_track_mismatch"}:
        return False
    debug = pose.get("debug")
    if isinstance(debug, dict) and debug.get("rejected_reason"):
        return False
    keypoints = pose.get("keypoints")
    if not isinstance(keypoints, list):
        return False
    for point in keypoints:
        if not isinstance(point, dict):
            continue
        try:
            if float(point.get("confidence") or 0.0) >= threshold:
                return True
        except (TypeError, ValueError):
            continue
    return False


if __name__ == "__main__":
    raise SystemExit(main())
