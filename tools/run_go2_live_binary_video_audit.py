from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


CAMERA_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(CAMERA_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(CAMERA_SERVICE_ROOT))

from app.post_fall_v2.binary_decision_aggregator import (  # noqa: E402
    BinaryDecisionAggregator,
    BinaryDecisionAggregatorConfig,
)
from app.post_fall_v2.fall_binary_classifier_service import FallBinaryClassifierService  # noqa: E402
from app.post_fall_v2.schemas import (  # noqa: E402
    FULL_FRAME_TRAIN_MATCHED,
    BinaryFrameResult,
    SampledFrame,
    monotonic_to_utc_iso,
)


DEFAULT_STREAM_URL = "http://192.168.8.254:8093/stream.mjpg"
DEFAULT_MODEL = CAMERA_SERVICE_ROOT / "models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx"
DEFAULT_SHA256 = "e9871cdb4687055fb5d934dd994c2ad883adac0c2acab375c240f8e005ee04cc"
# Previous OOF/audit threshold: 0.3979087471961975
DEFAULT_THRESHOLD = 0.60
DEFAULT_OUTPUT_ROOT = CAMERA_SERVICE_ROOT.parent / "diagnostics" / "go2_live_binary_video_audit"


def now_local_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")


def save_jpeg(path: Path, frame: np.ndarray, *, quality: int = 92) -> None:
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError(f"failed to encode jpeg: {path}")
    path.write_bytes(encoded.tobytes())


def safe_float(value: float | int | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def flatten(prefix: str, payload: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in payload.items():
        name = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten(name, value))
        else:
            flat[name] = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
    return flat


def open_capture(url: str) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if not capture.isOpened():
        capture.release()
        capture = cv2.VideoCapture(url)
    return capture


def capture_mjpeg_stream(
    *,
    stream_url: str,
    duration_seconds: float,
    output_dir: Path,
    fps_hint: float,
    reconnect_delay_seconds: float,
    read_failure_limit: int,
) -> dict[str, Any]:
    video_path = output_dir / "go2_live_capture.avi"
    frame_log_path = output_dir / "capture_frames.csv"
    event_log_path = output_dir / "capture_events.jsonl"
    first_frame_path = output_dir / "first_frame.jpg"
    last_frame_path = output_dir / "last_frame.jpg"

    capture = open_capture(stream_url)
    writer: cv2.VideoWriter | None = None
    start_monotonic = time.monotonic()
    deadline = start_monotonic + float(duration_seconds)
    start_utc = now_utc_iso()
    first_frame_monotonic: float | None = None
    last_frame_monotonic: float | None = None
    last_received_monotonic: float | None = None
    frame_count = 0
    reconnect_count = 0
    read_failures = 0
    source_width: int | None = None
    source_height: int | None = None
    writer_fps: float | None = None
    inter_frame_gaps: list[float] = []
    event_count_by_type: dict[str, int] = {}
    last_progress_monotonic = start_monotonic
    last_frame_for_snapshot: np.ndarray | None = None

    def log_event(event_type: str, **fields: Any) -> None:
        event_count_by_type[event_type] = event_count_by_type.get(event_type, 0) + 1
        record = {
            "event_type": event_type,
            "utc": now_utc_iso(),
            "elapsed_seconds": round(time.monotonic() - start_monotonic, 3),
            **fields,
        }
        with event_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=json_default) + "\n")

    with frame_log_path.open("w", newline="", encoding="utf-8-sig") as handle:
        fieldnames = [
            "frame_id",
            "timestamp_utc",
            "elapsed_seconds",
            "source_width",
            "source_height",
            "inter_frame_gap_seconds",
            "video_path",
        ]
        writer_csv = csv.DictWriter(handle, fieldnames=fieldnames)
        writer_csv.writeheader()
        log_event("capture_started", stream_url=stream_url, duration_seconds=duration_seconds)

        while time.monotonic() < deadline:
            if not capture.isOpened():
                capture.release()
                log_event("stream_disconnected", reason="capture_not_opened")
                time.sleep(max(0.0, reconnect_delay_seconds))
                capture = open_capture(stream_url)
                reconnect_count += 1
                log_event("stream_reconnect_attempt", reconnect_count=reconnect_count, opened=capture.isOpened())
                continue

            ok, frame = capture.read()
            received_monotonic = time.monotonic()
            if not ok or frame is None:
                read_failures += 1
                log_event("frame_read_failed", failure_count=read_failures)
                if read_failures >= max(1, read_failure_limit):
                    capture.release()
                    time.sleep(max(0.0, reconnect_delay_seconds))
                    capture = open_capture(stream_url)
                    reconnect_count += 1
                    log_event("stream_reconnect_attempt", reconnect_count=reconnect_count, opened=capture.isOpened())
                    read_failures = 0
                continue

            read_failures = 0
            height, width = frame.shape[:2]
            if writer is None:
                source_width = int(width)
                source_height = int(height)
                captured_fps = safe_float(capture.get(cv2.CAP_PROP_FPS))
                writer_fps = captured_fps if captured_fps and 0.1 <= captured_fps <= 120.0 else float(fps_hint)
                fourcc = cv2.VideoWriter_fourcc(*"MJPG")
                writer = cv2.VideoWriter(str(video_path), fourcc, float(writer_fps), (int(width), int(height)))
                if not writer.isOpened():
                    raise RuntimeError(f"failed to open VideoWriter: {video_path}")
                first_frame_monotonic = received_monotonic
                save_jpeg(first_frame_path, frame)
                log_event(
                    "first_frame_received",
                    source_width=source_width,
                    source_height=source_height,
                    capture_reported_fps=captured_fps,
                    writer_fps=writer_fps,
                )
            elif width != source_width or height != source_height:
                log_event(
                    "resolution_changed",
                    previous_width=source_width,
                    previous_height=source_height,
                    current_width=int(width),
                    current_height=int(height),
                )

            gap = received_monotonic - last_received_monotonic if last_received_monotonic is not None else None
            if gap is not None:
                inter_frame_gaps.append(float(gap))
                expected_gap = 1.0 / max(0.1, float(writer_fps or fps_hint))
                if gap > max(0.5, expected_gap * 3.0):
                    log_event("frame_gap_detected", gap_seconds=round(gap, 3), expected_gap_seconds=round(expected_gap, 3))

            frame_count += 1
            timestamp_utc = monotonic_to_utc_iso(received_monotonic)
            elapsed = received_monotonic - start_monotonic
            writer.write(frame)
            last_frame_for_snapshot = frame.copy()
            if frame_count % 150 == 0:
                save_jpeg(last_frame_path, frame)
            if received_monotonic - last_progress_monotonic >= 30.0:
                print(
                    json.dumps(
                        {
                            "stage": "capture",
                            "elapsed_seconds": round(received_monotonic - start_monotonic, 1),
                            "frames": frame_count,
                            "average_received_fps": round(frame_count / max(0.001, received_monotonic - start_monotonic), 3),
                            "reconnect_count": reconnect_count,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                last_progress_monotonic = received_monotonic
            writer_csv.writerow(
                {
                    "frame_id": frame_count,
                    "timestamp_utc": timestamp_utc,
                    "elapsed_seconds": round(elapsed, 6),
                    "source_width": int(width),
                    "source_height": int(height),
                    "inter_frame_gap_seconds": "" if gap is None else round(gap, 6),
                    "video_path": str(video_path),
                }
            )
            handle.flush()
            last_received_monotonic = received_monotonic
            last_frame_monotonic = received_monotonic

    if writer is not None:
        writer.release()
    capture.release()
    if last_frame_for_snapshot is not None:
        save_jpeg(last_frame_path, last_frame_for_snapshot)
    end_utc = now_utc_iso()
    log_event("capture_finished", frame_count=frame_count, reconnect_count=reconnect_count)

    wall_duration = time.monotonic() - start_monotonic
    received_duration = (
        last_frame_monotonic - first_frame_monotonic if first_frame_monotonic is not None and last_frame_monotonic is not None else 0.0
    )
    average_fps = frame_count / received_duration if received_duration > 0 else 0.0
    gap_stats = {
        "count": len(inter_frame_gaps),
        "mean_seconds": statistics.fmean(inter_frame_gaps) if inter_frame_gaps else None,
        "median_seconds": statistics.median(inter_frame_gaps) if inter_frame_gaps else None,
        "max_seconds": max(inter_frame_gaps) if inter_frame_gaps else None,
    }
    summary = {
        "stream_url": stream_url,
        "video_path": str(video_path),
        "frame_log_path": str(frame_log_path),
        "event_log_path": str(event_log_path),
        "start_utc": start_utc,
        "end_utc": end_utc,
        "requested_duration_seconds": float(duration_seconds),
        "wall_duration_seconds": round(wall_duration, 3),
        "received_duration_seconds": round(received_duration, 3),
        "total_frames": frame_count,
        "average_received_fps": round(average_fps, 6),
        "writer_fps": writer_fps,
        "source_width": source_width,
        "source_height": source_height,
        "reconnect_count": reconnect_count,
        "event_count_by_type": event_count_by_type,
        "inter_frame_gap_stats": gap_stats,
        "first_frame_path": str(first_frame_path) if first_frame_path.exists() else None,
        "last_frame_path": str(last_frame_path) if last_frame_path.exists() else None,
    }
    write_json(output_dir / "capture_summary.json", summary)
    return summary


def make_sample(frame: np.ndarray, *, frame_id: int, timestamp_utc: str, elapsed_seconds: float) -> SampledFrame:
    height, width = frame.shape[:2]
    sampled_monotonic = time.monotonic()
    return SampledFrame(
        camera_id="go2_front_camera",
        frame_id=f"go2_live_video_{frame_id:06d}",
        frame_seq=frame_id,
        captured_at=timestamp_utc,
        sampled_at=timestamp_utc,
        captured_monotonic=sampled_monotonic - max(0.0, elapsed_seconds),
        sampled_monotonic=sampled_monotonic,
        source_width=int(width),
        source_height=int(height),
        source_generation=0,
        frame=frame,
    )


def load_capture_frame_log(path: Path) -> dict[int, dict[str, Any]]:
    if not path.is_file():
        return {}
    rows: dict[int, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                frame_id = int(row["frame_id"])
            except Exception:
                continue
            rows[frame_id] = row
    return rows


def find_positive_runs(rows: list[dict[str, Any]], *, label_key: str = "binary_label") -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        is_positive = row.get(label_key) == "FALL"
        if is_positive and current is None:
            current = {
                "start_frame": row["frame_id"],
                "end_frame": row["frame_id"],
                "start_timestamp": row["timestamp"],
                "end_timestamp": row["timestamp"],
                "start_elapsed_seconds": row["elapsed_seconds"],
                "end_elapsed_seconds": row["elapsed_seconds"],
                "frame_count": 1,
                "max_fall_probability": row["fall_probability"],
                "mean_fall_probability": row["fall_probability"],
                "_sum": row["fall_probability"],
                "peak_frame": row["frame_id"],
                "peak_timestamp": row["timestamp"],
            }
            continue
        if is_positive and current is not None:
            current["end_frame"] = row["frame_id"]
            current["end_timestamp"] = row["timestamp"]
            current["end_elapsed_seconds"] = row["elapsed_seconds"]
            current["frame_count"] += 1
            current["_sum"] += row["fall_probability"]
            if row["fall_probability"] > current["max_fall_probability"]:
                current["max_fall_probability"] = row["fall_probability"]
                current["peak_frame"] = row["frame_id"]
                current["peak_timestamp"] = row["timestamp"]
            current["mean_fall_probability"] = current["_sum"] / current["frame_count"]
            continue
        if not is_positive and current is not None:
            current.pop("_sum", None)
            runs.append(current)
            current = None
    if current is not None:
        current.pop("_sum", None)
        runs.append(current)
    return runs


def probability_distribution(probabilities: list[float], threshold: float) -> dict[str, Any]:
    edges = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.000001]
    if 0.0 < threshold < 1.0:
        edges.append(float(threshold))
    edges = sorted({round(edge, 6) for edge in edges})
    bins = list(zip(edges, edges[1:]))
    distribution: dict[str, int] = {}
    for low, high in bins:
        if high <= low:
            continue
        label = f"[{low:.4f},{min(high, 1.0):.4f})"
        if high > 1.0:
            label = f"[{low:.4f},1.0000]"
        distribution[label] = sum(1 for p in probabilities if low <= p < high)
    return distribution


def analyze_video(
    *,
    video_path: Path,
    capture_frame_log_path: Path | None,
    output_dir: Path,
    model_path: Path,
    model_sha256: str,
    threshold: float,
    providers: list[str],
    temporal_config: BinaryDecisionAggregatorConfig,
    context_frames: int,
    high_probability_threshold: float,
    save_all_fall_frames: bool,
) -> dict[str, Any]:
    frame_log = load_capture_frame_log(capture_frame_log_path) if capture_frame_log_path else {}
    predictions_path = output_dir / "binary_frame_predictions.csv"
    predictions_jsonl_path = output_dir / "binary_frame_predictions.jsonl"
    temporal_path = output_dir / "temporal_window_results.csv"
    screenshots_dir = output_dir / "fall_screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    classifier = FallBinaryClassifierService(
        model_path=model_path,
        expected_sha256=model_sha256,
        threshold=threshold,
        input_policy=FULL_FRAME_TRAIN_MATCHED,
        providers=providers,
        warmup_runs=3,
    )
    aggregator = BinaryDecisionAggregator(temporal_config)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"failed to open video for analysis: {video_path}")

    rows: list[dict[str, Any]] = []
    temporal_rows: list[dict[str, Any]] = []
    screenshots_to_save: dict[int, dict[str, Any]] = {}
    recent_frames: deque[tuple[int, np.ndarray]] = deque(maxlen=max(0, context_frames) + 1)
    pending_after: list[dict[str, Any]] = []
    frame_id = 0
    video_fps = safe_float(capture.get(cv2.CAP_PROP_FPS)) or 0.0
    analysis_started = time.perf_counter()
    last_analysis_progress = analysis_started
    previous_temporal_active = False
    temporal_candidate_start_count = 0
    temporal_event_created_count = 0
    temporal_normal_candidate_trigger_count = 0
    temporal_high_confidence_trigger_count = 0
    temporal_recovery_confirmed_count = 0
    temporal_duplicate_event_count = 0

    prediction_fieldnames = [
        "frame_id",
        "timestamp",
        "elapsed_seconds",
        "fall_probability",
        "non_fall_probability",
        "threshold",
        "binary_label",
        "raw_label",
        "class_index",
        "inference_ms",
        "preprocess_ms",
        "total_ms",
        "source_width",
        "source_height",
        "valid",
        "error",
    ]
    temporal_fieldnames = [
        "frame_id",
        "timestamp",
        "elapsed_seconds",
        "single_frame_label",
        "fall_probability",
        "temporal_state",
        "temporal_reason",
        "temporal_event_created",
        "temporal_rearmed",
        "temporal_incident_id",
        "temporal_window_size",
        "temporal_positive_count",
        "temporal_consecutive_positive_count",
        "temporal_mean_fall_probability",
        "temporal_max_fall_probability",
        "temporal_candidate_duration_ms",
        "temporal_threshold",
        "temporal_frame_positive",
        "temporal_tail_consecutive_positive",
        "temporal_high_conf_consecutive",
        "temporal_normal_candidate_condition",
        "temporal_high_conf_candidate_condition",
        "temporal_candidate_triggered",
        "temporal_recovery_low_count",
        "temporal_candidate_active",
        "temporal_trigger_reason",
        "temporal_probability_window",
        "temporal_persistent_strong_candidate",
    ]

    with predictions_path.open("w", encoding="utf-8-sig", newline="") as pred_handle, temporal_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as temporal_handle, predictions_jsonl_path.open("w", encoding="utf-8") as jsonl_handle:
        pred_writer = csv.DictWriter(pred_handle, fieldnames=prediction_fieldnames)
        temporal_writer = csv.DictWriter(temporal_handle, fieldnames=temporal_fieldnames)
        pred_writer.writeheader()
        temporal_writer.writeheader()

        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            frame_id += 1
            logged = frame_log.get(frame_id, {})
            elapsed_seconds = float(logged.get("elapsed_seconds") or ((frame_id - 1) / video_fps if video_fps > 0 else 0.0))
            timestamp = str(logged.get("timestamp_utc") or monotonic_to_utc_iso(time.monotonic()))
            sampled = make_sample(frame, frame_id=frame_id, timestamp_utc=timestamp, elapsed_seconds=elapsed_seconds)
            result = classifier.infer(sampled)
            binary_result = BinaryFrameResult.from_classifier_result(result)
            binary_label = binary_result.decision_label
            row = {
                "frame_id": frame_id,
                "timestamp": timestamp,
                "elapsed_seconds": round(elapsed_seconds, 6),
                "fall_probability": result.fall_probability,
                "non_fall_probability": result.nofall_probability,
                "threshold": threshold,
                "binary_label": binary_label,
                "raw_label": result.prediction,
                "class_index": result.class_index,
                "inference_ms": result.performance.inference_ms,
                "preprocess_ms": result.performance.preprocess_ms,
                "total_ms": result.performance.total_ms,
                "source_width": result.input.source_width,
                "source_height": result.input.source_height,
                "valid": result.valid,
                "error": result.error_message,
            }
            rows.append(row)
            pred_writer.writerow(row)
            jsonl_handle.write(json.dumps({"binary": result.to_record()}, ensure_ascii=False, default=json_default) + "\n")

            decision = aggregator.update(binary_result, now=elapsed_seconds)
            evidence = asdict(decision.evidence)
            temporal_active = decision.state in {"FALL_CANDIDATE", "EVENT_ACTIVE", "RECOVERY_PENDING", "FALL_CONFIRMED"}
            was_temporal_active = previous_temporal_active
            if temporal_active and not was_temporal_active:
                temporal_candidate_start_count += 1
            previous_temporal_active = temporal_active
            if decision.event_created:
                temporal_event_created_count += 1
                if was_temporal_active:
                    temporal_duplicate_event_count += 1
            if decision.evidence.trigger_reason == "normal_temporal_confirmation":
                temporal_normal_candidate_trigger_count += 1
            elif decision.evidence.trigger_reason == "high_confidence_fast_path":
                temporal_high_confidence_trigger_count += 1
            if decision.reason == "recovery_confirmed":
                temporal_recovery_confirmed_count += 1
            temporal_row = {
                "frame_id": frame_id,
                "timestamp": timestamp,
                "elapsed_seconds": round(elapsed_seconds, 6),
                "single_frame_label": binary_label,
                "fall_probability": result.fall_probability,
                "temporal_state": decision.state,
                "temporal_reason": decision.reason,
                "temporal_event_created": decision.event_created,
                "temporal_rearmed": decision.rearmed,
                "temporal_incident_id": decision.incident_id,
                **flatten("temporal", evidence),
            }
            temporal_rows.append(temporal_row)
            temporal_writer.writerow(temporal_row)

            recent_frames.append((frame_id, frame.copy()))
            is_fall = binary_label == "FALL"
            is_high = bool(result.fall_probability is not None and result.fall_probability >= high_probability_threshold)
            if is_fall or is_high:
                if save_all_fall_frames:
                    screenshots_to_save[frame_id] = {"reason": "fall_frame" if is_fall else "high_probability_frame", "row": row}
                for context_id, context_frame in recent_frames:
                    screenshots_to_save.setdefault(context_id, {"reason": "pre_context", "row": row, "frame": context_frame.copy()})
                pending_after.append({"remaining": max(0, context_frames), "trigger": frame_id, "row": row})

            if pending_after:
                for item in list(pending_after):
                    if frame_id > int(item["trigger"]):
                        screenshots_to_save.setdefault(frame_id, {"reason": "post_context", "row": item["row"]})
                        item["remaining"] -= 1
                    if item["remaining"] <= 0:
                        pending_after.remove(item)

            if frame_id % 250 == 0:
                pred_handle.flush()
                temporal_handle.flush()
                jsonl_handle.flush()
            if time.perf_counter() - last_analysis_progress >= 30.0:
                print(
                    json.dumps(
                        {
                            "stage": "analysis",
                            "processed_frames": frame_id,
                            "fall_frames_so_far": sum(1 for item in rows if item["binary_label"] == "FALL"),
                            "elapsed_wall_seconds": round(time.perf_counter() - analysis_started, 1),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                last_analysis_progress = time.perf_counter()

    capture.release()
    run_seconds = time.perf_counter() - analysis_started

    if screenshots_to_save:
        capture = cv2.VideoCapture(str(video_path))
        current_id = 0
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            current_id += 1
            info = screenshots_to_save.get(current_id)
            if not info:
                continue
            source_row = info.get("row", {})
            prob = source_row.get("fall_probability")
            label = source_row.get("binary_label", "context")
            reason = info.get("reason", "context")
            name = f"frame_{current_id:06d}_{label}_p{float(prob if prob is not None else -1.0):.4f}_{reason}.jpg"
            save_jpeg(screenshots_dir / name, frame)
        capture.release()

    valid_rows = [row for row in rows if row["valid"] and row["fall_probability"] is not None]
    probabilities = [float(row["fall_probability"]) for row in valid_rows]
    fall_rows = [row for row in valid_rows if row["binary_label"] == "FALL"]
    non_fall_rows = [row for row in valid_rows if row["binary_label"] == "NON_FALL"]
    positive_runs = find_positive_runs(valid_rows)
    longest_run = max(positive_runs, key=lambda item: item["frame_count"], default=None)
    avg_fps = None
    if len(valid_rows) >= 2:
        duration = float(valid_rows[-1]["elapsed_seconds"]) - float(valid_rows[0]["elapsed_seconds"])
        avg_fps = (len(valid_rows) - 1) / duration if duration > 0 else None
    elif video_fps:
        avg_fps = video_fps
    for run in positive_runs:
        run["duration_seconds"] = max(0.0, float(run["end_elapsed_seconds"]) - float(run["start_elapsed_seconds"]))
    temporal_ranges = summarize_temporal_ranges(temporal_rows)
    suspected_ranges = sorted(
        positive_runs,
        key=lambda item: (float(item["max_fall_probability"]), int(item["frame_count"])),
        reverse=True,
    )

    summary = {
        "video_path": str(video_path),
        "capture_frame_log_path": str(capture_frame_log_path) if capture_frame_log_path else None,
        "predictions_csv": str(predictions_path),
        "predictions_jsonl": str(predictions_jsonl_path),
        "temporal_csv": str(temporal_path),
        "screenshots_dir": str(screenshots_dir),
        "model_path": str(model_path),
        "model_sha256": classifier.model_sha256,
        "provider": classifier.provider,
        "threshold": threshold,
        "temporal_config": asdict(temporal_config),
        "total_processed_frames": len(rows),
        "valid_processed_frames": len(valid_rows),
        "fall_frame_count": len(fall_rows),
        "non_fall_frame_count": len(non_fall_rows),
        "fall_frame_ratio": len(fall_rows) / len(valid_rows) if valid_rows else None,
        "max_fall_probability": max(probabilities) if probabilities else None,
        "mean_fall_probability": statistics.fmean(probabilities) if probabilities else None,
        "median_fall_probability": statistics.median(probabilities) if probabilities else None,
        "fall_probability_distribution": probability_distribution(probabilities, threshold),
        "longest_consecutive_fall_frames": int(longest_run["frame_count"]) if longest_run else 0,
        "longest_consecutive_fall_seconds": float(longest_run.get("duration_seconds", 0.0)) if longest_run else 0.0,
        "temporal_candidate_start_count": temporal_candidate_start_count,
        "temporal_event_created_count": temporal_event_created_count,
        "temporal_normal_candidate_trigger_count": temporal_normal_candidate_trigger_count,
        "temporal_high_confidence_trigger_count": temporal_high_confidence_trigger_count,
        "temporal_recovery_confirmed_count": temporal_recovery_confirmed_count,
        "temporal_duplicate_event_count": temporal_duplicate_event_count,
        "temporal_ranges": temporal_ranges,
        "suspected_false_positive_ranges": suspected_ranges,
        "saved_screenshot_count": len(list(screenshots_dir.glob("*.jpg"))),
        "video_metadata_fps": video_fps,
        "analysis_average_fps_from_timestamps": avg_fps,
        "analysis_wall_seconds": run_seconds,
        "mean_inference_ms": statistics.fmean([float(row["inference_ms"]) for row in valid_rows if row["inference_ms"] is not None])
        if valid_rows
        else None,
    }
    write_json(output_dir / "analysis_summary.json", summary)
    write_report(output_dir / "TEST_REPORT.md", summary)
    return summary


def summarize_temporal_ranges(temporal_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    active_states = {"FALL_CANDIDATE", "EVENT_ACTIVE", "RECOVERY_PENDING", "FALL_CONFIRMED"}
    for row in temporal_rows:
        active = row.get("temporal_state") in active_states
        if active and current is None:
            current = {
                "start_frame": row["frame_id"],
                "end_frame": row["frame_id"],
                "start_timestamp": row["timestamp"],
                "end_timestamp": row["timestamp"],
                "start_elapsed_seconds": row["elapsed_seconds"],
                "end_elapsed_seconds": row["elapsed_seconds"],
                "states": {row["temporal_state"]},
                "event_created": bool(row["temporal_event_created"]),
                "max_fall_probability": row["fall_probability"] or 0.0,
                "peak_frame": row["frame_id"],
            }
            continue
        if active and current is not None:
            current["end_frame"] = row["frame_id"]
            current["end_timestamp"] = row["timestamp"]
            current["end_elapsed_seconds"] = row["elapsed_seconds"]
            current["states"].add(row["temporal_state"])
            current["event_created"] = current["event_created"] or bool(row["temporal_event_created"])
            probability = row["fall_probability"] or 0.0
            if probability > current["max_fall_probability"]:
                current["max_fall_probability"] = probability
                current["peak_frame"] = row["frame_id"]
            continue
        if not active and current is not None:
            current["states"] = sorted(current["states"])
            current["duration_seconds"] = max(0.0, float(current["end_elapsed_seconds"]) - float(current["start_elapsed_seconds"]))
            ranges.append(current)
            current = None
    if current is not None:
        current["states"] = sorted(current["states"])
        current["duration_seconds"] = max(0.0, float(current["end_elapsed_seconds"]) - float(current["start_elapsed_seconds"]))
        ranges.append(current)
    return ranges


def format_percent(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def format_float(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}"


def write_report(path: Path, summary: dict[str, Any]) -> None:
    ranges = summary.get("suspected_false_positive_ranges", [])
    temporal_ranges = summary.get("temporal_ranges", [])
    lines = [
        "# 机器狗实时视频二分类独立审计报告",
        "",
        "## 结论速览",
        "",
        f"- 处理帧数：{summary.get('valid_processed_frames')} / {summary.get('total_processed_frames')}",
        f"- 单帧 FALL：{summary.get('fall_frame_count')}，NON_FALL：{summary.get('non_fall_frame_count')}，FALL 占比：{format_percent(summary.get('fall_frame_ratio'))}",
        f"- FALL probability：平均 {format_float(summary.get('mean_fall_probability'))}，最大 {format_float(summary.get('max_fall_probability'))}，中位数 {format_float(summary.get('median_fall_probability'))}",
        f"- 阈值：{format_float(summary.get('threshold'), 10)}",
        f"- 最长连续 FALL：{summary.get('longest_consecutive_fall_frames')} 帧，约 {format_float(summary.get('longest_consecutive_fall_seconds'), 3)} 秒",
        f"- 当前 8 帧时序 candidate 起始次数：{summary.get('temporal_candidate_start_count')}，event_created 次数：{summary.get('temporal_event_created_count')}",
        f"- 普通时序触发：{summary.get('temporal_normal_candidate_trigger_count')}，高置信快速触发：{summary.get('temporal_high_confidence_trigger_count')}，恢复确认：{summary.get('temporal_recovery_confirmed_count')}，重复事件：{summary.get('temporal_duplicate_event_count')}",
        "",
        "## 文件",
        "",
        f"- 视频：`{summary.get('video_path')}`",
        f"- 逐帧概率 CSV：`{summary.get('predictions_csv')}`",
        f"- 逐帧概率 JSONL：`{summary.get('predictions_jsonl')}`",
        f"- 时序滑窗 CSV：`{summary.get('temporal_csv')}`",
        f"- 截图目录：`{summary.get('screenshots_dir')}`",
        "",
        "## 模型与配置",
        "",
        f"- 模型：`{summary.get('model_path')}`",
        f"- SHA256：`{summary.get('model_sha256')}`",
        f"- 推理 provider：`{summary.get('provider')}`",
        f"- 单帧阈值：{format_float(summary.get('threshold'), 10)}",
        f"- 时序配置：`{json.dumps(summary.get('temporal_config'), ensure_ascii=False)}`",
        "- 旧阈值记录：上一轮 OOF/audit 阈值为 `0.3979087471961975`，本轮实验阈值为 `0.60`。",
        "",
        "## FALL Probability 分布",
        "",
        "| 区间 | 帧数 |",
        "|---|---:|",
    ]
    for bucket, count in summary.get("fall_probability_distribution", {}).items():
        lines.append(f"| `{bucket}` | {count} |")
    lines.extend(
        [
            "",
            "## 疑似误报时间段",
            "",
            "| # | 起止时间戳 | 起止秒 | 帧范围 | 持续帧数 | 持续秒 | 峰值概率 | 平均概率 | 峰值帧 |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    if ranges:
        for index, item in enumerate(ranges[:100], start=1):
            lines.append(
                f"| {index} | `{item['start_timestamp']}` -> `{item['end_timestamp']}` | "
                f"{float(item['start_elapsed_seconds']):.3f} -> {float(item['end_elapsed_seconds']):.3f} | "
                f"{item['start_frame']} -> {item['end_frame']} | {item['frame_count']} | "
                f"{float(item.get('duration_seconds', 0.0)):.3f} | {float(item['max_fall_probability']):.4f} | "
                f"{float(item['mean_fall_probability']):.4f} | {item['peak_frame']} |"
            )
    else:
        lines.append("| - | 未发现单帧 FALL | - | - | - | - | - | - | - |")
    lines.extend(
        [
            "",
            "## 时序 Candidate/Event 时间段",
            "",
            "| # | 状态 | 起止秒 | 帧范围 | 持续秒 | event_created | 峰值概率 | 峰值帧 |",
            "|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    if temporal_ranges:
        for index, item in enumerate(temporal_ranges[:100], start=1):
            lines.append(
                f"| {index} | `{','.join(item['states'])}` | "
                f"{float(item['start_elapsed_seconds']):.3f} -> {float(item['end_elapsed_seconds']):.3f} | "
                f"{item['start_frame']} -> {item['end_frame']} | {float(item['duration_seconds']):.3f} | "
                f"{item['event_created']} | {float(item['max_fall_probability']):.4f} | {item['peak_frame']} |"
            )
    else:
        lines.append("| - | 未触发 | - | - | - | - | - | - |")
    lines.extend(
        [
            "",
            "## 问题回答",
            "",
            f"- 正常实时画面是否频繁输出 FALL：看 `FALL 占比` 和上方疑似误报段；本次为 {format_percent(summary.get('fall_frame_ratio'))}。",
            f"- 误报是偶发还是连续：最长连续 {summary.get('longest_consecutive_fall_frames')} 帧，约 {format_float(summary.get('longest_consecutive_fall_seconds'), 3)} 秒。",
            f"- 误报概率范围：最大 {format_float(summary.get('max_fall_probability'))}，平均 {format_float(summary.get('mean_fall_probability'))}，具体段落见表。",
            "- 阈值是否放大边界样本：重点查看分布表里紧邻当前阈值上下两侧的区间帧数。",
            "- 单帧输出与时序链路是否混淆：`binary_frame_predictions.csv` 是单帧模型输出，`temporal_window_results.csv` 是 8 帧时序结果。",
            "- 最值得人工查看：优先看 `疑似误报时间段` 表中峰值概率最高、持续帧数最长的段，以及截图目录中的对应帧。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Go2 MJPEG video and audit the existing EfficientNet-B0 binary model frame by frame.")
    parser.add_argument("--stream-url", default=DEFAULT_STREAM_URL)
    parser.add_argument("--duration-seconds", type=float, default=600.0)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--model-sha256", default=DEFAULT_SHA256)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--providers", default="CPUExecutionProvider")
    parser.add_argument("--fps-hint", type=float, default=20.0)
    parser.add_argument("--reconnect-delay-seconds", type=float, default=1.0)
    parser.add_argument("--read-failure-limit", type=int, default=10)
    parser.add_argument("--context-frames", type=int, default=3)
    parser.add_argument("--high-probability-threshold", type=float, default=0.8)
    parser.add_argument("--temporal-window-size", type=int, default=8)
    parser.add_argument("--temporal-min-positive-frames", type=int, default=4)
    parser.add_argument("--temporal-min-consecutive-frames", type=int, default=3)
    parser.add_argument("--temporal-candidate-min-ms", type=int, default=0)
    parser.add_argument("--temporal-high-confidence-threshold", type=float, default=0.90)
    parser.add_argument("--temporal-high-confidence-min-consecutive-frames", type=int, default=2)
    parser.add_argument("--temporal-recovery-threshold", type=float, default=0.45)
    parser.add_argument("--temporal-recovery-min-consecutive-frames", type=int, default=5)
    parser.add_argument("--temporal-recovery-min-ms", type=int, default=1500)
    parser.add_argument("--temporal-cooldown-ms", type=int, default=3000)
    parser.add_argument("--input-video", type=Path, default=None, help="Analyze an already captured video instead of recording a new one.")
    parser.add_argument("--capture-frame-log", type=Path, default=None)
    parser.add_argument("--no-save-all-fall-frames", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = f"go2_live_binary_video_audit_{now_local_id()}"
    output_dir = args.output_root / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    providers = [part.strip() for part in args.providers.split(",") if part.strip()]
    write_json(
        output_dir / "run_config.json",
        {
            "stream_url": args.stream_url,
            "duration_seconds": args.duration_seconds,
            "model": args.model,
            "threshold": args.threshold,
            "providers": providers,
            "input_video": args.input_video,
            "capture_frame_log": args.capture_frame_log,
        },
    )

    if args.input_video:
        capture_summary = {
            "video_path": str(args.input_video),
            "frame_log_path": str(args.capture_frame_log) if args.capture_frame_log else None,
            "capture_skipped": True,
        }
        write_json(output_dir / "capture_summary.json", capture_summary)
    else:
        capture_summary = capture_mjpeg_stream(
            stream_url=args.stream_url,
            duration_seconds=args.duration_seconds,
            output_dir=output_dir,
            fps_hint=args.fps_hint,
            reconnect_delay_seconds=args.reconnect_delay_seconds,
            read_failure_limit=args.read_failure_limit,
        )

    video_path = Path(capture_summary["video_path"])
    capture_frame_log = Path(capture_summary["frame_log_path"]) if capture_summary.get("frame_log_path") else None
    if not video_path.is_file() or video_path.stat().st_size <= 0:
        raise RuntimeError(f"captured video is missing or empty: {video_path}")

    temporal_config = BinaryDecisionAggregatorConfig(
        threshold=float(args.threshold),
        window_size=int(args.temporal_window_size),
        min_positive_frames=int(args.temporal_min_positive_frames),
        min_consecutive_frames=int(args.temporal_min_consecutive_frames),
        candidate_min_ms=int(args.temporal_candidate_min_ms),
        high_confidence_threshold=float(args.temporal_high_confidence_threshold),
        high_confidence_min_consecutive_frames=int(args.temporal_high_confidence_min_consecutive_frames),
        recovery_threshold=float(args.temporal_recovery_threshold),
        recovery_min_consecutive_frames=int(args.temporal_recovery_min_consecutive_frames),
        recovery_min_ms=int(args.temporal_recovery_min_ms),
        cooldown_ms=int(args.temporal_cooldown_ms),
    )
    analysis_summary = analyze_video(
        video_path=video_path,
        capture_frame_log_path=capture_frame_log,
        output_dir=output_dir,
        model_path=args.model,
        model_sha256=args.model_sha256,
        threshold=float(args.threshold),
        providers=providers,
        temporal_config=temporal_config,
        context_frames=int(args.context_frames),
        high_probability_threshold=float(args.high_probability_threshold),
        save_all_fall_frames=not args.no_save_all_fall_frames,
    )
    write_json(output_dir / "RUN_COMPLETE.json", {"capture": capture_summary, "analysis": analysis_summary})
    print(json.dumps({"output_dir": str(output_dir), "capture": capture_summary, "analysis": analysis_summary}, ensure_ascii=False, indent=2, default=json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
