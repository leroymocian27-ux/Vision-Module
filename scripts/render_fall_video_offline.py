from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def configure_render_environment() -> None:
    defaults = {
        "VISION_SERVICE_RUNTIME_PROFILE": "offline_fall_video_render",
        "ENABLE_TRACKING": "true",
        "ENABLE_POSE": "true",
        "POSE_PROVIDER": "yolo",
        "ENABLE_BEHAVIOR": "true",
        "ENABLE_TEMPORAL": "true",
        "TEMPORAL_TRACK_MODE": "all_tracks",
        "TEMPORAL_SEQUENCE_KEY_MODE": "spatial",
        "TEMPORAL_MODEL_PROVIDER": "shadow",
        "POSE_FALLBACK_TO_DETECTION": "true",
        "POSE_FALLBACK_MIN_CONFIDENCE": "0.15",
        "MAIN_SYSTEM_ALERT_ENABLED": "false",
        "VISION_SERVICE_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
        "TEMPORAL_ONNX_PROVIDERS": "CUDAExecutionProvider,CPUExecutionProvider",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


configure_render_environment()

from scripts.evaluate_fall_video_offline import (  # noqa: E402
    OfflineFallVideoEvaluator,
    SimulatedClock,
    VideoEvalCase,
    build_video_summary,
    safe_slug,
    write_frame_outputs,
)
from app.schemas.vision_result import DetectedObject, VisionResult  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.detection.object_detector import YoloPersonDetector  # noqa: E402
from app.detection.yolo_fall_detector import YoloFallDetector  # noqa: E402


PERSON_COLOR = (40, 180, 70)
FALL_HINT_COLOR = (0, 150, 255)
CONFIRMED_COLOR = (0, 0, 255)
TEXT_BG = (24, 24, 24)


def render_video(
    *,
    video_path: Path,
    output_dir: Path,
    camera_id: str,
    frame_stride: int,
    output_video: Path | None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("FALL_EVENT_SNAPSHOT_DIR", str((output_dir / "snapshots").resolve()))

    evaluator = OfflineFallVideoEvaluator(
        output_dir=output_dir,
        camera_id=camera_id,
        frame_stride=frame_stride,
    )
    evaluator._reset_services()

    video_slug = safe_slug(video_path.stem)
    video_camera_id = f"{camera_id}_{video_slug}"
    output_video = output_video or (output_dir / f"{video_slug}_boxed.mp4")
    frames_csv = output_dir / f"offline_eval_{video_slug}_frames.csv"
    frames_jsonl = output_dir / f"offline_eval_{video_slug}_frames.jsonl"
    summary_json = output_dir / f"offline_eval_{video_slug}_summary.json"

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration_ms = int(round(frame_count * 1000 / fps)) if frame_count > 0 else 0
    if width <= 0 or height <= 0:
        raise RuntimeError(f"could not read video dimensions: {video_path}")

    writer = cv2.VideoWriter(
        str(output_video),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"could not open video writer: {output_video}")

    rows: list[dict[str, Any]] = []
    pose_success_frames = 0
    confirmed_frames = 0
    alarm_confirmed_frames = 0
    max_person_count = 0
    max_tracked_objects = 0
    incident_id: str | None = None
    snapshot_path: str | None = None
    snapshot_url: str | None = None
    latest_result_consumable = False
    first_confirmed_frame: int | None = None
    first_confirmed_timestamp_ms: int | None = None
    first_incident_id_frame: int | None = None

    clock = SimulatedClock()
    frame_duration = 1.0 / fps
    frame_index = 0
    last_result: VisionResult | None = None
    last_fall_hint_objects: list[DetectedObject] = []
    stride = max(1, frame_stride)
    started_at = time.perf_counter()

    with ExitStack() as stack:
        evaluator._patch_time(stack, clock)
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if frame_index % stride == 0:
                row = evaluator._process_frame(
                    camera_id=video_camera_id,
                    video_name=video_path.name,
                    frame_index=frame_index,
                    timestamp_ms=int(round(frame_index * 1000 / fps)),
                    frame=frame,
                    frame_monotonic=clock.monotonic(),
                    case=None,
                )
                rows.append(row)
                max_person_count = max(max_person_count, int(row["latest_raw_person_count"]))
                max_tracked_objects = max(max_tracked_objects, int(row["tracked_objects_count"]))
                if row["pose_success"]:
                    pose_success_frames += 1
                if row["alarm_confirmed"]:
                    alarm_confirmed_frames += 1
                if row["fall_state"] == "fallen_confirmed":
                    confirmed_frames += 1
                    if first_confirmed_frame is None:
                        first_confirmed_frame = frame_index
                        first_confirmed_timestamp_ms = int(row["timestamp_ms"])
                if row["incident_id"]:
                    incident_id = str(row["incident_id"])
                    snapshot_path = row["snapshot_path"] or snapshot_path
                    snapshot_url = row["snapshot_url"] or snapshot_url
                    latest_result_consumable = bool(
                        row["camera_id"]
                        and row["fall_state"] == "fallen_confirmed"
                        and row["alarm_confirmed"]
                        and row["incident_id"]
                    )
                    if first_incident_id_frame is None:
                        first_incident_id_frame = frame_index

                pipeline = evaluator.result_store.snapshot(video_camera_id)
                last_result = pipeline.latest_published_result or last_result
                last_fall_hint_objects = (
                    list(pipeline.latest_fall_detection.objects)
                    if pipeline.latest_fall_detection is not None
                    else []
                )

            canvas = frame.copy()
            draw_overlay(
                canvas,
                frame_index=frame_index,
                fps=fps,
                result=last_result,
                fall_hint_objects=last_fall_hint_objects,
            )
            writer.write(canvas)

            frame_index += 1
            clock.advance(frame_duration)

    cap.release()
    writer.release()

    write_frame_outputs(frames_csv, frames_jsonl, rows)
    summary = build_video_summary(
        video_path=video_path,
        case=VideoEvalCase(path=video_path),
        frame_count=frame_count or frame_index,
        processed_frames=len(rows),
        fps=fps,
        duration_ms=duration_ms,
        rows=rows,
        max_person_count=max_person_count,
        max_tracked_objects=max_tracked_objects,
        pose_success_frames=pose_success_frames,
        alarm_confirmed_frames=alarm_confirmed_frames,
        confirmed_frames=confirmed_frames,
        first_confirmed_frame=first_confirmed_frame,
        first_confirmed_timestamp_ms=first_confirmed_timestamp_ms,
        first_incident_id_frame=first_incident_id_frame,
        incident_id=incident_id,
        snapshot_path=snapshot_path,
        snapshot_url=snapshot_url,
        latest_result_consumable=latest_result_consumable,
    )
    summary_json.write_text(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "video": str(video_path.resolve()),
        "output_video": str(output_video.resolve()),
        "frames_csv": str(frames_csv.resolve()),
        "frames_jsonl": str(frames_jsonl.resolve()),
        "summary_json": str(summary_json.resolve()),
        "frame_count": frame_count or frame_index,
        "processed_frames": len(rows),
        "elapsed_seconds": round(time.perf_counter() - started_at, 2),
        "summary": summary.to_dict(),
    }


def render_detector_video(
    *,
    video_path: Path,
    output_dir: Path,
    output_video: Path | None,
    detector_mode: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    video_slug = safe_slug(video_path.stem)
    suffix = "fall_detector" if detector_mode == "fall" else "person_detector"
    output_video = output_video or (output_dir / f"{video_slug}_{suffix}_boxed.mp4")

    settings = get_settings()
    detector = YoloFallDetector(settings) if detector_mode == "fall" else YoloPersonDetector(settings)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError(f"could not read video dimensions: {video_path}")

    writer = cv2.VideoWriter(
        str(output_video),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"could not open video writer: {output_video}")

    rows: list[dict[str, Any]] = []
    frame_index = 0
    started_at = time.perf_counter()
    color = FALL_HINT_COLOR if detector_mode == "fall" else PERSON_COLOR
    label_prefix = "fall-detector" if detector_mode == "fall" else "person"

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        objects = detector.detect(frame)
        canvas = frame.copy()
        for obj in objects:
            draw_box(
                canvas,
                obj.bbox,
                color,
                f"{label_prefix} {obj.label} {float(obj.confidence):.2f}",
                thickness=2,
            )
        draw_panel(
            canvas,
            [
                f"Vision Service {label_prefix}",
                f"frame {frame_index}  t={frame_index / max(fps, 1.0):.2f}s",
                f"detections={len(objects)}",
            ],
        )
        writer.write(canvas)
        rows.append(
            {
                "frame_index": frame_index,
                "timestamp_ms": int(round(frame_index * 1000 / fps)),
                "detections": [
                    {
                        "label": obj.label,
                        "confidence": obj.confidence,
                        "bbox": obj.bbox,
                    }
                    for obj in objects
                ],
            }
        )
        frame_index += 1

    cap.release()
    writer.release()

    result_json = output_dir / f"{video_slug}_{suffix}_frames.json"
    result_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "video": str(video_path.resolve()),
        "output_video": str(output_video.resolve()),
        "frames_json": str(result_json.resolve()),
        "detector_mode": detector_mode,
        "frame_count": frame_count or frame_index,
        "processed_frames": frame_index,
        "elapsed_seconds": round(time.perf_counter() - started_at, 2),
    }


def draw_overlay(
    frame: np.ndarray,
    *,
    frame_index: int,
    fps: float,
    result: VisionResult | None,
    fall_hint_objects: list[DetectedObject],
) -> None:
    if result is not None:
        for obj in result.objects:
            if obj.label != "person":
                continue
            alarm = obj.alarm_preview if isinstance(obj.alarm_preview, dict) else {}
            decision = obj.fall_decision if isinstance(obj.fall_decision, dict) else {}
            confirmed = bool(alarm.get("confirmed")) or str(decision.get("fall_state") or "") == "fallen_confirmed"
            color = CONFIRMED_COLOR if confirmed else PERSON_COLOR
            label = person_label(obj)
            draw_box(frame, obj.bbox, color, label, thickness=3 if confirmed else 2)
            draw_pose(frame, obj.pose if isinstance(obj.pose, dict) else None)

    for obj in fall_hint_objects:
        label = f"fall-hint {obj.label} {float(obj.confidence):.2f}"
        draw_box(frame, obj.bbox, FALL_HINT_COLOR, label, thickness=2)

    header_lines = [
        "Vision Service offline render",
        f"frame {frame_index}  t={frame_index / max(fps, 1.0):.2f}s",
    ]
    if result is not None:
        people = [obj for obj in result.objects if obj.label == "person"]
        states = [object_state(obj) for obj in people]
        state_text = ", ".join(item for item in states if item) or "no fall state"
        header_lines.append(f"people={len(people)}  {state_text}")
    else:
        header_lines.append("waiting for first system result")
    draw_panel(frame, header_lines)


def person_label(obj: DetectedObject) -> str:
    alarm = obj.alarm_preview if isinstance(obj.alarm_preview, dict) else {}
    decision = obj.fall_decision if isinstance(obj.fall_decision, dict) else {}
    state = str(decision.get("fall_state") or object_state(obj) or "person")
    probability = alarm.get("fall_probability") or decision.get("fall_probability")
    pieces = [f"id={obj.track_id}" if obj.track_id is not None else "person", state]
    if probability is not None:
        try:
            pieces.append(f"p={float(probability):.2f}")
        except (TypeError, ValueError):
            pass
    if bool(alarm.get("confirmed")):
        pieces.append("CONFIRMED")
    return " ".join(pieces)


def object_state(obj: DetectedObject) -> str | None:
    decision = obj.fall_decision if isinstance(obj.fall_decision, dict) else {}
    alarm = obj.alarm_preview if isinstance(obj.alarm_preview, dict) else {}
    temporal = obj.temporal if isinstance(obj.temporal, dict) else {}
    return (
        str(decision.get("fall_state"))
        if decision.get("fall_state")
        else str(alarm.get("risk_level"))
        if alarm.get("risk_level")
        else str(temporal.get("fall_state"))
        if temporal.get("fall_state")
        else None
    )


def draw_box(
    frame: np.ndarray,
    bbox: list[float],
    color: tuple[int, int, int],
    label: str,
    *,
    thickness: int,
) -> None:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = clamp_bbox(bbox, width, height)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

    scale = max(0.6, min(width, height) / 1200)
    text_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    text_w, text_h = text_size
    label_y1 = max(0, y1 - text_h - baseline - 8)
    label_y2 = label_y1 + text_h + baseline + 8
    label_x2 = min(width - 1, x1 + text_w + 10)
    cv2.rectangle(frame, (x1, label_y1), (label_x2, label_y2), color, -1)
    cv2.putText(
        frame,
        label,
        (x1 + 5, label_y2 - baseline - 4),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def draw_panel(frame: np.ndarray, lines: list[str]) -> None:
    scale = max(0.6, min(frame.shape[:2]) / 1250)
    line_height = int(28 * scale)
    panel_width = max(cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)[0][0] for line in lines) + 28
    panel_height = line_height * len(lines) + 22
    overlay = frame.copy()
    cv2.rectangle(overlay, (12, 12), (min(frame.shape[1] - 1, 12 + panel_width), 12 + panel_height), TEXT_BG, -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)
    y = 12 + line_height
    for line in lines:
        cv2.putText(frame, line, (26, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (245, 245, 245), 2, cv2.LINE_AA)
        y += line_height


def draw_pose(frame: np.ndarray, pose: dict | None) -> None:
    if not pose:
        return
    keypoints = pose.get("keypoints")
    if not isinstance(keypoints, list):
        return
    for item in keypoints:
        if not isinstance(item, dict):
            continue
        score = float(item.get("score") or item.get("confidence") or 0.0)
        if score < 0.25:
            continue
        x = item.get("x")
        y = item.get("y")
        if x is None or y is None:
            continue
        cv2.circle(frame, (int(float(x)), int(float(y))), 3, (255, 255, 0), -1, cv2.LINE_AA)


def clamp_bbox(bbox: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = [int(round(float(value))) for value in bbox]
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(0, min(width - 1, x2))
    y2 = max(0, min(height - 1, y2))
    if x2 <= x1:
        x2 = min(width - 1, x1 + 1)
    if y2 <= y1:
        y2 = min(height - 1, y1 + 1)
    return x1, y1, x2, y2


def main() -> int:
    parser = argparse.ArgumentParser(description="Render offline fall pipeline results into a boxed video.")
    parser.add_argument("--video", required=True, help="Input video path.")
    parser.add_argument("--output-dir", default=str(ROOT / "logs" / "offline_fall_render"))
    parser.add_argument("--output-video", default=None)
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument(
        "--mode",
        choices=["system", "fall", "person"],
        default="system",
        help="system renders the full service pipeline; fall/person render only that detector model.",
    )
    args = parser.parse_args()

    if args.mode == "system":
        payload = render_video(
            video_path=Path(args.video),
            output_dir=Path(args.output_dir),
            camera_id=args.camera_id,
            frame_stride=args.frame_stride,
            output_video=Path(args.output_video) if args.output_video else None,
        )
    else:
        payload = render_detector_video(
            video_path=Path(args.video),
            output_dir=Path(args.output_dir),
            output_video=Path(args.output_video) if args.output_video else None,
            detector_mode=args.mode,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
