from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULT_DIR = ROOT / "diagnostics" / "go2_live_binary_video_audit" / "go2_live_binary_video_audit_20260905_174459"
ACTIVE_TEMPORAL_STATES = {"FALL_CANDIDATE", "EVENT_ACTIVE", "RECOVERY_PENDING", "FALL_CONFIRMED"}
REVIEW_LABELS = [
    "真实跌倒",
    "正常坐下",
    "正常坐地",
    "正常躺卧",
    "弯腰",
    "蹲下",
    "行走",
    "站立",
    "空场景",
    "画面异常",
    "不确定",
]
SCREENSHOT_RE = re.compile(r"frame_(?P<frame_id>\d+)_(?P<label>[^_]+)_p(?P<prob>-?\d+\.\d+)_(?P<reason>.+)\.jpg$", re.I)
MANUAL_REVIEW_COLUMNS = [
    "segment_id",
    "review_type",
    "frame_id",
    "timestamp",
    "start_time",
    "end_time",
    "peak_probability",
    "current_probability",
    "review_label",
    "review_note",
    "review_time",
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_audit(result_dir_text: str) -> dict[str, Any]:
    result_dir = Path(result_dir_text)
    predictions_path = result_dir / "binary_frame_predictions.csv"
    temporal_path = result_dir / "temporal_window_results.csv"
    capture_summary_path = result_dir / "capture_summary.json"
    analysis_summary_path = result_dir / "analysis_summary.json"
    if not result_dir.is_dir():
        raise FileNotFoundError(f"结果目录不存在：{result_dir}")
    if not predictions_path.is_file():
        raise FileNotFoundError(f"缺少逐帧预测文件：{predictions_path}")
    if not temporal_path.is_file():
        raise FileNotFoundError(f"缺少时序结果文件：{temporal_path}")

    predictions = pd.read_csv(predictions_path)
    temporal = pd.read_csv(temporal_path)
    capture_summary = read_json(capture_summary_path)
    analysis_summary = read_json(analysis_summary_path)

    predictions["frame_id"] = pd.to_numeric(predictions["frame_id"], errors="coerce").astype("Int64")
    predictions["elapsed_seconds"] = pd.to_numeric(predictions["elapsed_seconds"], errors="coerce")
    predictions["fall_probability"] = pd.to_numeric(predictions["fall_probability"], errors="coerce")
    predictions["non_fall_probability"] = pd.to_numeric(predictions["non_fall_probability"], errors="coerce")
    predictions["threshold"] = pd.to_numeric(predictions["threshold"], errors="coerce")
    for column in ["inference_ms", "preprocess_ms", "total_ms"]:
        if column in predictions:
            predictions[column] = pd.to_numeric(predictions[column], errors="coerce")

    temporal["frame_id"] = pd.to_numeric(temporal["frame_id"], errors="coerce").astype("Int64")
    temporal["elapsed_seconds"] = pd.to_numeric(temporal["elapsed_seconds"], errors="coerce")
    for column in [
        "temporal_positive_count",
        "temporal_consecutive_positive_count",
        "temporal_window_size",
        "temporal_candidate_duration_ms",
        "fall_probability",
    ]:
        if column in temporal:
            temporal[column] = pd.to_numeric(temporal[column], errors="coerce")

    merged = predictions.merge(
        temporal[
            [
                column
                for column in [
                    "frame_id",
                    "temporal_state",
                    "temporal_reason",
                    "temporal_event_created",
                    "temporal_incident_id",
                    "temporal_window_size",
                    "temporal_positive_count",
                    "temporal_consecutive_positive_count",
                    "temporal_mean_fall_probability",
                    "temporal_max_fall_probability",
                    "temporal_candidate_duration_ms",
                    "temporal_threshold",
                    "temporal_probability_window",
                    "temporal_persistent_strong_candidate",
                ]
                if column in temporal.columns
            ]
        ],
        on="frame_id",
        how="left",
    )
    screenshots = load_screenshots(result_dir / "fall_screenshots", predictions)
    return {
        "result_dir": result_dir,
        "predictions": predictions,
        "temporal": temporal,
        "merged": merged,
        "capture_summary": capture_summary,
        "analysis_summary": analysis_summary,
        "screenshots": screenshots,
    }


def load_screenshots(screenshots_dir: Path, predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not screenshots_dir.is_dir():
        return pd.DataFrame(rows)
    lookup = predictions.set_index("frame_id", drop=False) if not predictions.empty else pd.DataFrame()
    for path in screenshots_dir.glob("*.jpg"):
        match = SCREENSHOT_RE.match(path.name)
        if not match:
            continue
        frame_id = int(match.group("frame_id"))
        pred = lookup.loc[frame_id].iloc[0] if frame_id in lookup.index and isinstance(lookup.loc[frame_id], pd.DataFrame) else None
        if pred is None and frame_id in lookup.index:
            pred = lookup.loc[frame_id]
        rows.append(
            {
                "frame_id": frame_id,
                "path": str(path),
                "filename": path.name,
                "label": match.group("label"),
                "probability_from_name": float(match.group("prob")),
                "reason": match.group("reason"),
                "elapsed_seconds": float(pred["elapsed_seconds"]) if pred is not None else None,
                "timestamp": str(pred["timestamp"]) if pred is not None else "",
                "fall_probability": float(pred["fall_probability"]) if pred is not None else float(match.group("prob")),
            }
        )
    return pd.DataFrame(rows).sort_values(["frame_id", "path"]) if rows else pd.DataFrame(rows)


def fmt(value: Any, digits: int = 3, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, (float, int)):
        return f"{float(value):.{digits}f}{suffix}"
    return str(value)


def pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value) * 100:.2f}%"


def bool_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, str):
        return "TRUE" if value.strip().lower() in {"true", "1", "yes"} else "FALSE"
    return "TRUE" if bool(value) else "FALSE"


def is_event_created(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def is_candidate_state(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    return str(value) in ACTIVE_TEMPORAL_STATES


def video_path_from_summary(result_dir: Path, capture_summary: dict[str, Any]) -> Path:
    configured = capture_summary.get("video_path")
    if configured:
        path = Path(str(configured))
        if path.is_file():
            return path
    return result_dir / "go2_live_capture.avi"


@st.cache_data(show_spinner=False)
def read_video_frame(video_path_text: str, frame_id: int) -> dict[str, Any]:
    video_path = Path(video_path_text)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return {"ok": False, "error": f"无法打开视频：{video_path}"}
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    target_frame = max(1, min(int(frame_id), total_frames if total_frames > 0 else int(frame_id)))
    capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame - 1)
    ok, frame = capture.read()
    position_msec = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
    capture.release()
    if not ok or frame is None:
        return {"ok": False, "error": f"无法读取视频帧：{target_frame}"}
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    container_time = (target_frame - 1) / fps if fps > 0 else None
    if position_msec > 0:
        container_time = position_msec / 1000.0
    return {
        "ok": True,
        "frame": rgb,
        "frame_id": target_frame,
        "video_container_seconds": container_time,
        "video_fps": fps,
        "video_total_frames": total_frames,
        "width": int(frame.shape[1]),
        "height": int(frame.shape[0]),
    }


def set_inspect_time(value: float, predictions: pd.DataFrame) -> None:
    min_time = float(predictions["elapsed_seconds"].min())
    max_time = float(predictions["elapsed_seconds"].max())
    st.session_state["inspect_time"] = min(max(float(value), min_time), max_time)


def set_inspect_frame(frame_id: int, predictions: pd.DataFrame) -> None:
    target = predictions[predictions["frame_id"] == int(frame_id)]
    if not target.empty:
        st.session_state["inspect_time"] = float(target.iloc[0]["elapsed_seconds"])


def current_prediction_index(predictions: pd.DataFrame, frame_id: int) -> int:
    matches = predictions.index[predictions["frame_id"] == int(frame_id)]
    if len(matches):
        return int(matches[0])
    return 0


def find_fall_segments(predictions: pd.DataFrame, threshold: float, temporal: pd.DataFrame | None = None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in predictions.sort_values("frame_id").itertuples(index=False):
        prob = float(getattr(row, "fall_probability")) if not pd.isna(getattr(row, "fall_probability")) else float("nan")
        is_fall = not pd.isna(prob) and prob >= threshold
        if is_fall and current is None:
            current = {
                "start_frame": int(getattr(row, "frame_id")),
                "end_frame": int(getattr(row, "frame_id")),
                "start_time": float(getattr(row, "elapsed_seconds")),
                "end_time": float(getattr(row, "elapsed_seconds")),
                "start_timestamp": str(getattr(row, "timestamp")),
                "end_timestamp": str(getattr(row, "timestamp")),
                "frame_count": 1,
                "sum_probability": prob,
                "max_probability": prob,
                "peak_frame": int(getattr(row, "frame_id")),
            }
            continue
        if is_fall and current is not None:
            current["end_frame"] = int(getattr(row, "frame_id"))
            current["end_time"] = float(getattr(row, "elapsed_seconds"))
            current["end_timestamp"] = str(getattr(row, "timestamp"))
            current["frame_count"] += 1
            current["sum_probability"] += prob
            if prob > current["max_probability"]:
                current["max_probability"] = prob
                current["peak_frame"] = int(getattr(row, "frame_id"))
            continue
        if not is_fall and current is not None:
            rows.append(finish_segment(current, temporal))
            current = None
    if current is not None:
        rows.append(finish_segment(current, temporal))
    if not rows:
        return pd.DataFrame(
            columns=[
                "segment_id",
                "start_time",
                "end_time",
                "duration_seconds",
                "start_frame",
                "end_frame",
                "frame_count",
                "mean_probability",
                "max_probability",
                "peak_frame",
                "candidate_triggered",
                "event_created",
            ]
        )
    data = pd.DataFrame(rows)
    data.insert(0, "segment_id", [f"segment_{index:03d}" for index in range(1, len(data) + 1)])
    return data


def finish_segment(segment: dict[str, Any], temporal: pd.DataFrame | None) -> dict[str, Any]:
    start_frame = int(segment["start_frame"])
    end_frame = int(segment["end_frame"])
    duration = max(0.0, float(segment["end_time"]) - float(segment["start_time"]))
    temporal_slice = pd.DataFrame()
    if temporal is not None and not temporal.empty:
        temporal_slice = temporal[(temporal["frame_id"] >= start_frame) & (temporal["frame_id"] <= end_frame)]
    states = set(str(item) for item in temporal_slice.get("temporal_state", pd.Series(dtype=str)).dropna().tolist())
    event_created = False
    if "temporal_event_created" in temporal_slice:
        event_created = temporal_slice["temporal_event_created"].astype(str).str.lower().isin(["true", "1"]).any()
    segment.update(
        {
            "duration_seconds": duration,
            "mean_probability": segment["sum_probability"] / max(1, int(segment["frame_count"])),
            "candidate_triggered": any(state in {"FALL_CANDIDATE", "EVENT_ACTIVE", "RECOVERY_PENDING", "FALL_CONFIRMED"} for state in states),
            "event_created": bool(event_created),
        }
    )
    segment.pop("sum_probability", None)
    return segment


def simulated_stats(predictions: pd.DataFrame, threshold: float, temporal: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    valid = predictions[predictions["fall_probability"].notna()].copy()
    labels = valid["fall_probability"] >= threshold
    segments = find_fall_segments(valid, threshold, temporal)
    longest = segments.sort_values("duration_seconds", ascending=False).head(1)
    stats = {
        "fall_count": int(labels.sum()),
        "non_fall_count": int((~labels).sum()),
        "fall_ratio": float(labels.mean()) if len(labels) else None,
        "segment_count": int(len(segments)),
        "longest_frames": int(longest["frame_count"].iloc[0]) if not longest.empty else 0,
        "longest_seconds": float(longest["duration_seconds"].iloc[0]) if not longest.empty else 0.0,
    }
    return stats, segments


def probability_figure(predictions: pd.DataFrame, temporal: pd.DataFrame, threshold: float, max_points: int = 5000) -> go.Figure:
    plot_df = predictions.sort_values("frame_id")
    if len(plot_df) > max_points:
        step = max(1, len(plot_df) // max_points)
        plot_df = plot_df.iloc[::step].copy()
    fig = go.Figure()
    fig.add_trace(
        go.Scattergl(
            x=plot_df["elapsed_seconds"],
            y=plot_df["fall_probability"],
            mode="lines",
            name="FALL probability",
            customdata=plot_df[["frame_id", "binary_label", "timestamp"]].to_numpy(),
            hovertemplate="time=%{x:.3f}s<br>frame=%{customdata[0]}<br>p=%{y:.4f}<br>label=%{customdata[1]}<br>%{customdata[2]}<extra></extra>",
            line=dict(width=1.8),
        )
    )
    fig.add_hline(y=threshold, line_dash="dash", line_color="#d62728", annotation_text=f"Threshold {threshold:.4f}")
    add_temporal_regions(fig, temporal)
    event_rows = temporal[temporal.get("temporal_event_created", pd.Series(dtype=str)).astype(str).str.lower().isin(["true", "1"])]
    if not event_rows.empty:
        fig.add_trace(
            go.Scatter(
                x=event_rows["elapsed_seconds"],
                y=event_rows["fall_probability"],
                mode="markers",
                name="Event Created",
                marker=dict(size=8, symbol="diamond"),
                hovertemplate="event=%{x:.3f}s<br>p=%{y:.4f}<extra></extra>",
            )
        )
    fig.update_layout(
        height=420,
        margin=dict(l=8, r=8, t=30, b=8),
        xaxis_title="视频时间 / seconds",
        yaxis_title="FALL probability",
        yaxis=dict(range=[0, 1]),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


def add_temporal_regions(fig: go.Figure, temporal: pd.DataFrame) -> None:
    active = False
    start = None
    end = None
    for row in temporal.sort_values("frame_id").itertuples(index=False):
        state = str(getattr(row, "temporal_state", ""))
        time_value = float(getattr(row, "elapsed_seconds"))
        if state in ACTIVE_TEMPORAL_STATES and not active:
            active = True
            start = time_value
            end = time_value
            continue
        if state in ACTIVE_TEMPORAL_STATES and active:
            end = time_value
            continue
        if state not in ACTIVE_TEMPORAL_STATES and active:
            fig.add_vrect(x0=start, x1=end, fillcolor="rgba(255, 165, 0, 0.16)", line_width=0, layer="below")
            active = False
            start = None
            end = None
    if active:
        fig.add_vrect(x0=start, x1=end, fillcolor="rgba(255, 165, 0, 0.16)", line_width=0, layer="below")


def distribution_figure(predictions: pd.DataFrame, threshold: float) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=predictions["fall_probability"].dropna(),
            xbins=dict(start=0, end=1, size=0.05),
            name="frames",
            hovertemplate="p range=%{x}<br>frames=%{y}<extra></extra>",
        )
    )
    fig.add_vline(x=threshold, line_dash="dash", line_color="#d62728", annotation_text=f"{threshold:.4f}")
    fig.update_layout(
        height=300,
        margin=dict(l=8, r=8, t=20, b=8),
        xaxis_title="FALL probability",
        yaxis_title="帧数",
        bargap=0.04,
        showlegend=False,
    )
    return fig


def local_probability_figure(predictions: pd.DataFrame, temporal: pd.DataFrame, threshold: float, current_time: float) -> go.Figure:
    fig = probability_figure(predictions, temporal, threshold, max_points=5000)
    fig.add_vline(
        x=current_time,
        line_dash="dot",
        line_color="#1f77b4",
        annotation_text=f"当前帧 {current_time:.3f}s",
    )
    fig.update_layout(height=320)
    return fig


def nearest_frame(merged: pd.DataFrame, elapsed_seconds: float) -> pd.Series:
    index = (merged["elapsed_seconds"] - elapsed_seconds).abs().idxmin()
    return merged.loc[index]


def rows_in_time_range(predictions: pd.DataFrame, start_time: float, end_time: float) -> pd.DataFrame:
    start = min(float(start_time), float(end_time))
    end = max(float(start_time), float(end_time))
    return predictions[(predictions["elapsed_seconds"] >= start) & (predictions["elapsed_seconds"] <= end)].copy()


def nearest_prediction(predictions: pd.DataFrame, elapsed_seconds: float) -> pd.Series:
    index = (predictions["elapsed_seconds"] - elapsed_seconds).abs().idxmin()
    return predictions.loc[index]


def segment_from_time_range(predictions: pd.DataFrame, start_time: float, end_time: float, segment_id: str) -> pd.Series:
    start_row = nearest_prediction(predictions, min(start_time, end_time))
    end_row = nearest_prediction(predictions, max(start_time, end_time))
    start_frame = int(start_row["frame_id"])
    end_frame = int(end_row["frame_id"])
    if end_frame < start_frame:
        start_frame, end_frame = end_frame, start_frame
    subset = predictions[(predictions["frame_id"] >= start_frame) & (predictions["frame_id"] <= end_frame)]
    return pd.Series(
        {
            "segment_id": segment_id,
            "start_time": float(subset["elapsed_seconds"].min()) if not subset.empty else min(start_time, end_time),
            "end_time": float(subset["elapsed_seconds"].max()) if not subset.empty else max(start_time, end_time),
            "duration_seconds": float(subset["elapsed_seconds"].max() - subset["elapsed_seconds"].min()) if len(subset) > 1 else 0.0,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "frame_count": int(len(subset)),
            "mean_probability": float(subset["fall_probability"].mean()) if not subset.empty else 0.0,
            "max_probability": float(subset["fall_probability"].max()) if not subset.empty else 0.0,
            "peak_frame": int(subset.sort_values("fall_probability", ascending=False).iloc[0]["frame_id"]) if not subset.empty else start_frame,
            "candidate_triggered": False,
            "event_created": False,
        }
    )


def clip_path_for_segment(result_dir: Path, segment: pd.Series, context_seconds: float) -> Path:
    clips_dir = result_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    start = max(0.0, float(segment["start_time"]) - context_seconds)
    end = float(segment["end_time"]) + context_seconds
    return clips_dir / f"{segment['segment_id']}_{start:.3f}_{end:.3f}_frames_{int(segment['start_frame'])}_{int(segment['end_frame'])}.mp4"


def generate_clip(result_dir: Path, segment: pd.Series, predictions: pd.DataFrame, capture_summary: dict[str, Any], context_seconds: float) -> tuple[Path | None, str | None]:
    video_path = Path(capture_summary.get("video_path") or result_dir / "go2_live_capture.avi")
    if not video_path.is_file():
        return None, f"原始视频不存在：{video_path}"
    clip_path = clip_path_for_segment(result_dir, segment, context_seconds)
    if clip_path.is_file() and clip_path.stat().st_size > 0:
        return clip_path, None
    avg_fps = float(capture_summary.get("average_received_fps") or 8.0)
    context_frames = max(1, int(round(context_seconds * avg_fps)))
    start_frame = max(1, int(segment["start_frame"]) - context_frames)
    end_frame = min(int(predictions["frame_id"].max()), int(segment["end_frame"]) + context_frames)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None, "找不到 ffmpeg，无法生成 MP4 片段。"
    select_expr = f"select=between(n\\,{start_frame - 1}\\,{end_frame - 1}),setpts=N/({avg_fps:.6f}*TB)"
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        select_expr,
        "-an",
        "-r",
        f"{avg_fps:.6f}",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        str(clip_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        return None, completed.stderr.strip() or "ffmpeg 生成片段失败。"
    return clip_path, None


@st.cache_data(show_spinner=False)
def ensure_thumbnail(video_path_text: str, result_dir_text: str, frame_id: int, width: int = 200) -> str | None:
    video_path = Path(video_path_text)
    result_dir = Path(result_dir_text)
    thumbnails_dir = result_dir / "frame_thumbnails"
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    output_path = thumbnails_dir / f"frame_{int(frame_id):06d}_w{int(width)}.jpg"
    if output_path.is_file() and output_path.stat().st_size > 0:
        return str(output_path)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return None
    capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(frame_id) - 1))
    ok, frame = capture.read()
    capture.release()
    if not ok or frame is None:
        return None
    height, original_width = frame.shape[:2]
    scale = float(width) / max(1, original_width)
    resized = cv2.resize(frame, (int(width), max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
    if not ok:
        return None
    output_path.write_bytes(encoded.tobytes())
    return str(output_path)


def thumbnail_rows_for_range(predictions: pd.DataFrame, start_time: float, end_time: float, interval_seconds: float) -> pd.DataFrame:
    if predictions.empty:
        return predictions.iloc[0:0].copy()
    start = max(float(predictions["elapsed_seconds"].min()), min(float(start_time), float(end_time)))
    end = min(float(predictions["elapsed_seconds"].max()), max(float(start_time), float(end_time)))
    if end < start:
        end = start
    times = []
    current = start
    while current <= end + 1e-6:
        times.append(current)
        current += max(1.0, float(interval_seconds))
    selected_indices = []
    for value in times:
        selected_indices.append(int((predictions["elapsed_seconds"] - value).abs().idxmin()))
    return predictions.loc[sorted(set(selected_indices))].copy()


def load_manual_reviews(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=MANUAL_REVIEW_COLUMNS)
    data = pd.read_csv(path)
    for column in MANUAL_REVIEW_COLUMNS:
        if column not in data.columns:
            data[column] = ""
    return data[MANUAL_REVIEW_COLUMNS]


def save_manual_review(path: Path, record: dict[str, Any]) -> None:
    rows = []
    if path.is_file():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    rows = [row for row in rows if row.get("segment_id") != record["segment_id"]]
    rows.append(record)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANUAL_REVIEW_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in MANUAL_REVIEW_COLUMNS})


def render_metric_grid(capture_summary: dict[str, Any], analysis_summary: dict[str, Any], predictions: pd.DataFrame) -> None:
    duration = capture_summary.get("wall_duration_seconds") or predictions["elapsed_seconds"].max()
    columns = st.columns(5)
    metrics = [
        ("视频时长", fmt(duration, 3, " s")),
        ("总帧数", str(analysis_summary.get("valid_processed_frames") or len(predictions))),
        ("实际 FPS", fmt(capture_summary.get("average_received_fps"), 4)),
        ("FALL", str(analysis_summary.get("fall_frame_count", "N/A"))),
        ("FALL 占比", pct(analysis_summary.get("fall_frame_ratio"))),
        ("NON_FALL", str(analysis_summary.get("non_fall_frame_count", "N/A"))),
        ("最大概率", fmt(analysis_summary.get("max_fall_probability"), 4)),
        ("平均概率", fmt(analysis_summary.get("mean_fall_probability"), 4)),
        ("中位数", fmt(analysis_summary.get("median_fall_probability"), 4)),
        ("Candidate", str(analysis_summary.get("temporal_candidate_start_count", "N/A"))),
        ("Event Created", str(analysis_summary.get("temporal_event_created_count", "N/A"))),
        ("最长 FALL 帧", str(analysis_summary.get("longest_consecutive_fall_frames", "N/A"))),
        ("最长 FALL 秒", fmt(analysis_summary.get("longest_consecutive_fall_seconds"), 3, " s")),
    ]
    for index, (label, value) in enumerate(metrics):
        columns[index % len(columns)].metric(label, value)


def render_current_frame_info(row: pd.Series) -> None:
    st.subheader("当前帧信息")
    st.metric("FALL Probability", fmt(row.get("fall_probability"), 4))
    st.metric("Binary Label", str(row.get("binary_label", "N/A")))
    st.metric("Candidate Triggered", bool_text(is_candidate_state(row.get("temporal_state"))))
    data = {
        "Timestamp": row.get("timestamp", "N/A"),
        "Frame ID": row.get("frame_id", "N/A"),
        "NON_FALL Probability": fmt(row.get("non_fall_probability"), 4),
        "Threshold": fmt(row.get("threshold"), 10),
        "Temporal Window": row.get("temporal_window_size", "N/A"),
        "Positive Count": row.get("temporal_positive_count", "N/A"),
        "Consecutive Positive": row.get("temporal_consecutive_positive_count", "N/A"),
        "Event Created": bool_text(row.get("temporal_event_created")),
        "Inference Latency": fmt(row.get("inference_ms"), 3, " ms"),
    }
    detail_df = pd.DataFrame({"field": list(data.keys()), "value": [str(value) for value in data.values()]})
    st.dataframe(detail_df, width="stretch", hide_index=True)


def render_frame_inspector(
    result_dir: Path,
    predictions: pd.DataFrame,
    temporal: pd.DataFrame,
    merged: pd.DataFrame,
    capture_summary: dict[str, Any],
    threshold: float,
) -> pd.Series:
    st.subheader("逐帧审计 / Frame Inspector")
    min_time = float(predictions["elapsed_seconds"].min())
    max_time = float(predictions["elapsed_seconds"].max())
    if "inspect_time" not in st.session_state:
        st.session_state["inspect_time"] = min_time
    st.session_state["inspect_time"] = min(max(float(st.session_state["inspect_time"]), min_time), max_time)

    inspect_time = st.slider("视频时间轴", min_value=min_time, max_value=max_time, step=0.01, key="inspect_time")
    current = nearest_frame(merged, inspect_time)
    current_frame_id = int(current["frame_id"])
    current_csv_time = float(current["elapsed_seconds"])
    video_path = video_path_from_summary(result_dir, capture_summary)
    frame = read_video_frame(str(video_path), current_frame_id)

    controls = st.columns(6)
    prev_frame = max(int(predictions["frame_id"].min()), current_frame_id - 1)
    next_frame = min(int(predictions["frame_id"].max()), current_frame_id + 1)
    controls[0].button("上一帧", on_click=set_inspect_frame, args=(prev_frame, predictions), key="inspect_prev_frame")
    controls[1].button("前1秒", on_click=set_inspect_time, args=(current_csv_time - 1.0, predictions), key="inspect_prev_1s")
    controls[2].button("前5秒", on_click=set_inspect_time, args=(current_csv_time - 5.0, predictions), key="inspect_prev_5s")
    controls[3].button("后一帧", on_click=set_inspect_frame, args=(next_frame, predictions), key="inspect_next_frame")
    controls[4].button("后1秒", on_click=set_inspect_time, args=(current_csv_time + 1.0, predictions), key="inspect_next_1s")
    controls[5].button("后5秒", on_click=set_inspect_time, args=(current_csv_time + 5.0, predictions), key="inspect_next_5s")

    left, right = st.columns([2, 1])
    with left:
        if frame.get("ok"):
            st.image(frame["frame"], caption=f"真实视频帧 f{current_frame_id} | CSV {current_csv_time:.3f}s", width="stretch")
        else:
            st.error(frame.get("error", "无法读取当前视频帧。"))
    with right:
        render_current_frame_info(current)
        match_data = {
            "Requested slider time": fmt(inspect_time, 3, " s"),
            "Matched CSV elapsed": fmt(current_csv_time, 3, " s"),
            "CSV match delta": fmt(abs(current_csv_time - inspect_time), 3, " s"),
            "Video container time": fmt(frame.get("video_container_seconds"), 3, " s") if frame.get("ok") else "N/A",
            "Video FPS metadata": fmt(frame.get("video_fps"), 3) if frame.get("ok") else "N/A",
            "Resolution": f"{frame.get('width')}x{frame.get('height')}" if frame.get("ok") else "N/A",
        }
        st.dataframe(pd.DataFrame({"field": list(match_data.keys()), "value": list(match_data.values())}), width="stretch", hide_index=True)

    nearby_start = max(0, current_prediction_index(predictions, current_frame_id) - 10)
    nearby_end = min(len(predictions), current_prediction_index(predictions, current_frame_id) + 11)
    nearby = predictions.iloc[nearby_start:nearby_end].copy()
    nearby["selected"] = nearby["frame_id"].astype(int).eq(current_frame_id).map({True: ">>", False: ""})
    nearby_display = nearby[["selected", "frame_id", "elapsed_seconds", "fall_probability", "binary_label"]].rename(
        columns={
            "selected": "",
            "frame_id": "Frame",
            "elapsed_seconds": "Timestamp",
            "fall_probability": "FALL Prob",
            "binary_label": "Label",
        }
    )
    st.caption("当前时间附近帧")
    st.dataframe(nearby_display, width="stretch", hide_index=True)
    nearby_options = {
        f"f{int(row.frame_id)} | {float(row.elapsed_seconds):.3f}s | p={float(row.fall_probability):.4f} | {row.binary_label}": int(row.frame_id)
        for row in nearby.itertuples(index=False)
    }
    jump_choice = st.selectbox("跳转到附近帧", list(nearby_options.keys()), key="nearby_jump_choice")
    st.button("跳转到所选附近帧", on_click=set_inspect_frame, args=(nearby_options[jump_choice], predictions), key="nearby_jump_button")

    local_window = st.slider("局部曲线窗口", 1.0, 20.0, 5.0, 1.0)
    local_predictions = rows_in_time_range(predictions, current_csv_time - local_window, current_csv_time + local_window)
    local_temporal = rows_in_time_range(temporal, current_csv_time - local_window, current_csv_time + local_window)
    st.plotly_chart(local_probability_figure(local_predictions, local_temporal, threshold, current_csv_time), width="stretch")
    return current


def render_time_range_view(
    result_dir: Path,
    predictions: pd.DataFrame,
    temporal: pd.DataFrame,
    capture_summary: dict[str, Any],
    threshold: float,
) -> None:
    st.subheader("按时间范围查看")
    max_time = float(predictions["elapsed_seconds"].max())
    default_start = min(max_time, max(0.0, float(st.session_state.get("inspect_time", 0.0)) - 5.0))
    default_end = min(max_time, default_start + 10.0)
    col_start, col_end, col_action = st.columns([1, 1, 1])
    start_time = col_start.number_input("开始时间 / s", min_value=0.0, max_value=max_time, value=float(default_start), step=0.5)
    end_time = col_end.number_input("结束时间 / s", min_value=0.0, max_value=max_time, value=float(default_end), step=0.5)
    range_df = rows_in_time_range(predictions, start_time, end_time)
    range_temporal = rows_in_time_range(temporal, start_time, end_time)
    col_action.button("跳到开始时间", on_click=set_inspect_time, args=(start_time, predictions), key="range_jump_start")
    if range_df.empty:
        st.info("当前时间范围内没有预测帧。")
        return
    fall_count = int((range_df["fall_probability"] >= threshold).sum())
    event_count = int(range_temporal.get("temporal_event_created", pd.Series(dtype=str)).astype(str).str.lower().isin(["true", "1"]).sum())
    candidate_count = int(range_temporal.get("temporal_state", pd.Series(dtype=str)).astype(str).isin(ACTIVE_TEMPORAL_STATES).sum())
    st.caption(
        f"范围内帧数 {len(range_df)}，FALL {fall_count}，Candidate 帧 {candidate_count}，Event Created {event_count}，"
        f"峰值 {range_df['fall_probability'].max():.4f}，均值 {range_df['fall_probability'].mean():.4f}。"
    )
    pseudo = segment_from_time_range(predictions, start_time, end_time, "manual_range_preview")
    clip_path, error = generate_clip(result_dir, pseudo, predictions, capture_summary, 0.0)
    if error:
        st.warning(error)
    elif clip_path:
        st.video(str(clip_path))
    st.plotly_chart(local_probability_figure(range_df, range_temporal, threshold, float(range_df["elapsed_seconds"].median())), width="stretch")
    display = range_df[["frame_id", "elapsed_seconds", "fall_probability", "binary_label", "inference_ms"]].copy()
    st.dataframe(display, width="stretch", hide_index=True)


def render_thumbnail_strip(result_dir: Path, predictions: pd.DataFrame, capture_summary: dict[str, Any]) -> None:
    st.subheader("缩略图时间带")
    max_time = float(predictions["elapsed_seconds"].max())
    col_start, col_end, col_interval = st.columns(3)
    start_time = col_start.number_input("缩略图开始 / s", min_value=0.0, max_value=max_time, value=0.0, step=10.0)
    end_default = min(max_time, start_time + 120.0)
    end_time = col_end.number_input("缩略图结束 / s", min_value=0.0, max_value=max_time, value=float(end_default), step=10.0)
    interval = col_interval.selectbox("间隔", [5.0, 10.0, 20.0, 30.0], index=1, format_func=lambda value: f"{value:.0f} 秒")
    rows = thumbnail_rows_for_range(predictions, start_time, end_time, interval)
    if len(rows) > 48:
        rows = rows.head(48)
        st.caption("当前最多显示前 48 张低分辨率缩略图。")
    video_path = video_path_from_summary(result_dir, capture_summary)
    for chunk_start in range(0, len(rows), 6):
        cols = st.columns(6)
        for col, (_, row) in zip(cols, rows.iloc[chunk_start : chunk_start + 6].iterrows()):
            thumb = ensure_thumbnail(str(video_path), str(result_dir), int(row["frame_id"]))
            if thumb:
                col.image(thumb, caption=f"{float(row['elapsed_seconds']):.1f}s\np={float(row['fall_probability']):.3f}", width="stretch")
            col.button(
                "查看",
                key=f"thumb_jump_{int(row['frame_id'])}",
                on_click=set_inspect_frame,
                args=(int(row["frame_id"]), predictions),
            )


def render_probability_filter(result_dir: Path, predictions: pd.DataFrame, capture_summary: dict[str, Any], threshold: float) -> None:
    st.subheader("Probability 条件筛选")
    mode = st.radio(
        "筛选方式",
        [">= 0.4", ">= 0.6", ">= 0.8", ">= 0.9", "边界误报", "自定义"],
        horizontal=True,
    )
    if mode == "边界误报":
        filtered = predictions[(predictions["fall_probability"] >= threshold) & (predictions["fall_probability"] < 0.60)]
    elif mode == "自定义":
        custom = st.slider("最小 FALL probability", 0.0, 1.0, float(threshold), 0.01)
        filtered = predictions[predictions["fall_probability"] >= custom]
    else:
        value = float(mode.replace(">=", "").strip())
        filtered = predictions[predictions["fall_probability"] >= value]
    st.caption(f"匹配帧数：{len(filtered)}")
    if filtered.empty:
        return
    shown = filtered[["frame_id", "elapsed_seconds", "fall_probability", "binary_label"]].sort_values(
        "fall_probability", ascending=False
    )
    st.dataframe(shown.head(200), width="stretch", hide_index=True)
    options = {
        f"f{int(row.frame_id)} | {float(row.elapsed_seconds):.3f}s | p={float(row.fall_probability):.4f} | {row.binary_label}": int(row.frame_id)
        for row in shown.head(500).itertuples(index=False)
    }
    choice = st.selectbox("跳转到筛选帧", list(options.keys()), key="filter_jump_choice")
    st.button("跳转到所选筛选帧", on_click=set_inspect_frame, args=(options[choice], predictions), key="filter_jump_button")

    video_path = video_path_from_summary(result_dir, capture_summary)
    thumb_rows = shown.head(12)
    for chunk_start in range(0, len(thumb_rows), 4):
        cols = st.columns(4)
        for col, (_, row) in zip(cols, thumb_rows.iloc[chunk_start : chunk_start + 4].iterrows()):
            thumb = ensure_thumbnail(str(video_path), str(result_dir), int(row["frame_id"]))
            if thumb:
                col.image(thumb, caption=f"{float(row['elapsed_seconds']):.3f}s | f{int(row['frame_id'])} | p={float(row['fall_probability']):.4f}", width="stretch")


def render_frame_manual_review(result_dir: Path, current: pd.Series, predictions: pd.DataFrame) -> None:
    st.subheader("当前帧 / 时间段标记")
    review_path = result_dir / "manual_review.csv"
    current_time = float(current["elapsed_seconds"])
    default_start = max(float(predictions["elapsed_seconds"].min()), current_time - 2.0)
    default_end = min(float(predictions["elapsed_seconds"].max()), current_time + 2.0)
    with st.form("frame_manual_review_form"):
        review_type = st.radio("标记类型", ["标记当前帧", "标记当前片段"], horizontal=True)
        start_time = st.number_input("片段开始 / s", min_value=0.0, value=float(default_start), step=0.1)
        end_time = st.number_input("片段结束 / s", min_value=0.0, value=float(default_end), step=0.1)
        label = st.selectbox("人工判断", REVIEW_LABELS, index=REVIEW_LABELS.index("不确定"))
        note = st.text_area("人工备注")
        submitted = st.form_submit_button("保存当前标记")
    if submitted:
        if review_type == "标记当前帧":
            segment_id = f"frame_{int(current['frame_id']):06d}"
            start = current_time
            end = current_time
            peak = float(current["fall_probability"])
        else:
            start = min(float(start_time), float(end_time))
            end = max(float(start_time), float(end_time))
            subset = rows_in_time_range(predictions, start, end)
            peak = float(subset["fall_probability"].max()) if not subset.empty else float(current["fall_probability"])
            segment_id = f"range_{start:.3f}_{end:.3f}".replace(".", "p")
        record = {
            "segment_id": segment_id,
            "review_type": review_type,
            "frame_id": int(current["frame_id"]),
            "timestamp": current.get("timestamp", ""),
            "start_time": f"{start:.3f}",
            "end_time": f"{end:.3f}",
            "peak_probability": f"{peak:.6f}",
            "current_probability": f"{float(current['fall_probability']):.6f}",
            "review_label": label,
            "review_note": note,
            "review_time": datetime.now().isoformat(timespec="seconds"),
        }
        save_manual_review(review_path, record)
        st.success(f"已保存到 {review_path}")
    if review_path.is_file():
        st.dataframe(load_manual_reviews(review_path), width="stretch", hide_index=True)


def render_segment_details(
    result_dir: Path,
    selected: pd.Series,
    predictions: pd.DataFrame,
    temporal: pd.DataFrame,
    capture_summary: dict[str, Any],
    screenshots: pd.DataFrame,
) -> None:
    st.subheader("片段快速查看")
    st.write(
        f"真实触发区间：{float(selected['start_time']):.3f}s - {float(selected['end_time']):.3f}s，"
        f"帧 {int(selected['start_frame'])} - {int(selected['end_frame'])}"
    )
    context_seconds = st.slider("短片上下文秒数", 0.0, 5.0, 2.0, 0.5)
    clip_path, error = generate_clip(result_dir, selected, predictions, capture_summary, context_seconds)
    if error:
        st.warning(error)
    elif clip_path:
        st.video(str(clip_path))

    segment_predictions = predictions[
        (predictions["frame_id"] >= int(selected["start_frame"])) & (predictions["frame_id"] <= int(selected["end_frame"]))
    ]
    st.plotly_chart(
        probability_figure(segment_predictions, temporal.iloc[0:0], float(selected.get("threshold", 0.3979087471961975)) if "threshold" in selected else float(predictions["threshold"].dropna().iloc[0])),
        width="stretch",
    )
    st.json(
        {
            "segment_id": selected["segment_id"],
            "duration_seconds": float(selected["duration_seconds"]),
            "frame_count": int(selected["frame_count"]),
            "mean_probability": float(selected["mean_probability"]),
            "max_probability": float(selected["max_probability"]),
            "candidate_triggered": bool(selected["candidate_triggered"]),
            "event_created": bool(selected["event_created"]),
        }
    )

    nearby = screenshots[
        (screenshots["frame_id"] >= int(selected["start_frame"]) - 3)
        & (screenshots["frame_id"] <= int(selected["end_frame"]) + 3)
    ] if not screenshots.empty else pd.DataFrame()
    if not nearby.empty:
        st.caption("关键截图")
        for chunk_start in range(0, min(len(nearby), 12), 4):
            cols = st.columns(4)
            for col, (_, shot) in zip(cols, nearby.iloc[chunk_start : chunk_start + 4].iterrows()):
                col.image(shot["path"], caption=f"f{int(shot['frame_id'])} | {float(shot['fall_probability']):.4f}", width="stretch")


def render_manual_review(result_dir: Path, selected: pd.Series) -> None:
    st.subheader("人工标记")
    review_path = result_dir / "manual_review.csv"
    existing = load_manual_reviews(review_path)
    old = existing[existing["segment_id"] == selected["segment_id"]] if not existing.empty else pd.DataFrame()
    default_label = old["review_label"].iloc[-1] if not old.empty and old["review_label"].iloc[-1] in REVIEW_LABELS else "不确定"
    default_note = old["review_note"].iloc[-1] if not old.empty else ""
    with st.form("manual_review_form"):
        label = st.selectbox("人工标签", REVIEW_LABELS, index=REVIEW_LABELS.index(default_label))
        note = st.text_area("人工备注", value=str(default_note) if pd.notna(default_note) else "")
        submitted = st.form_submit_button("保存标记")
    if submitted:
        record = {
            "segment_id": selected["segment_id"],
            "start_time": f"{float(selected['start_time']):.3f}",
            "end_time": f"{float(selected['end_time']):.3f}",
            "peak_probability": f"{float(selected['max_probability']):.6f}",
            "review_label": label,
            "review_note": note,
            "review_time": datetime.now().isoformat(timespec="seconds"),
        }
        save_manual_review(review_path, record)
        st.success(f"已保存到 {review_path}")
    if review_path.is_file():
        st.dataframe(load_manual_reviews(review_path), width="stretch", hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Go2 Binary Model Audit", layout="wide")
    st.title("Go2 Binary Model Audit")
    st.caption("离线审计模式：只读取已保存的 10 分钟视频、逐帧预测 CSV 和时序结果 CSV，不连接当前实时视频流。")
    result_dir_text = st.sidebar.text_input("审计结果目录", value=str(DEFAULT_RESULT_DIR))

    try:
        data = load_audit(result_dir_text)
    except Exception as exc:
        st.error(str(exc))
        return

    result_dir: Path = data["result_dir"]
    predictions: pd.DataFrame = data["predictions"]
    temporal: pd.DataFrame = data["temporal"]
    merged: pd.DataFrame = data["merged"]
    capture_summary: dict[str, Any] = data["capture_summary"]
    analysis_summary: dict[str, Any] = data["analysis_summary"]
    screenshots: pd.DataFrame = data["screenshots"]
    st.sidebar.caption(f"离线视频文件：{video_path_from_summary(result_dir, capture_summary)}")

    actual_threshold = float(analysis_summary.get("threshold") or predictions["threshold"].dropna().iloc[0])
    simulated_threshold = st.sidebar.slider(
        "Threshold",
        min_value=0.0,
        max_value=1.0,
        value=float(actual_threshold),
        step=0.001,
        help="模拟阈值，仅用于离线分析，不修改真实模型配置。",
    )
    st.sidebar.caption("模拟阈值，仅用于离线分析，不修改真实模型配置。")

    render_metric_grid(capture_summary, analysis_summary, predictions)
    sim, segments = simulated_stats(predictions, simulated_threshold, temporal)
    st.caption(
        f"模拟阈值 {simulated_threshold:.4f}：FALL {sim['fall_count']}，NON_FALL {sim['non_fall_count']}，"
        f"FALL 占比 {pct(sim['fall_ratio'])}，连续区间 {sim['segment_count']}，最长 {sim['longest_frames']} 帧 / {sim['longest_seconds']:.3f}s。"
    )

    current_frame = render_frame_inspector(result_dir, predictions, temporal, merged, capture_summary, simulated_threshold)
    render_frame_manual_review(result_dir, current_frame, predictions)
    st.divider()

    st.subheader("FALL Probability")
    st.plotly_chart(probability_figure(predictions, temporal, simulated_threshold), width="stretch")

    dist_left, dist_right = st.columns([2, 1])
    with dist_left:
        st.subheader("Probability 分布")
        st.plotly_chart(distribution_figure(predictions, simulated_threshold), width="stretch")
    with dist_right:
        p = predictions["fall_probability"].dropna()
        buckets = pd.DataFrame(
            [
                {"bucket": f"< {actual_threshold:.4f}", "frames": int((p < actual_threshold).sum())},
                {"bucket": f"{actual_threshold:.4f} - 0.6", "frames": int(((p >= actual_threshold) & (p < 0.6)).sum())},
                {"bucket": "0.6 - 0.8", "frames": int(((p >= 0.6) & (p < 0.8)).sum())},
                {"bucket": "> 0.8", "frames": int((p > 0.8).sum())},
                {"bucket": "> 0.9", "frames": int((p > 0.9).sum())},
            ]
        )
        st.dataframe(buckets, width="stretch", hide_index=True)

    tool_tab_range, tool_tab_filter, tool_tab_thumbnails = st.tabs(["按时间范围查看", "Probability 条件筛选", "缩略图时间带"])
    with tool_tab_range:
        render_time_range_view(result_dir, predictions, temporal, capture_summary, simulated_threshold)
    with tool_tab_filter:
        render_probability_filter(result_dir, predictions, capture_summary, actual_threshold)
    with tool_tab_thumbnails:
        render_thumbnail_strip(result_dir, predictions, capture_summary)

    st.subheader("高风险 / 疑似误报片段")
    sort_label = st.selectbox("排序", ["时间顺序", "Probability 最大值", "持续时间", "平均 Probability"])
    filter_label = st.radio("筛选", ["全部 FALL 区间", "低置信边界误报", "高置信 FALL"], horizontal=True)
    shown_segments = segments.copy()
    if filter_label == "低置信边界误报":
        shown_segments = shown_segments[(shown_segments["max_probability"] >= actual_threshold) & (shown_segments["max_probability"] < 0.60)]
    elif filter_label == "高置信 FALL":
        shown_segments = shown_segments[shown_segments["max_probability"] >= 0.90]
    if sort_label == "Probability 最大值":
        shown_segments = shown_segments.sort_values("max_probability", ascending=False)
    elif sort_label == "持续时间":
        shown_segments = shown_segments.sort_values("duration_seconds", ascending=False)
    elif sort_label == "平均 Probability":
        shown_segments = shown_segments.sort_values("mean_probability", ascending=False)
    else:
        shown_segments = shown_segments.sort_values("start_time")

    display_columns = [
        "segment_id",
        "start_time",
        "end_time",
        "duration_seconds",
        "frame_count",
        "mean_probability",
        "max_probability",
        "candidate_triggered",
        "event_created",
    ]
    st.dataframe(shown_segments[display_columns], width="stretch", hide_index=True)
    if shown_segments.empty:
        st.info("当前筛选条件下没有连续 FALL 区间。")
        return

    segment_options = {
        f"{row.segment_id} | {row.start_time:.3f}-{row.end_time:.3f}s | peak {row.max_probability:.4f} | {int(row.frame_count)} frames": row.segment_id
        for row in shown_segments.itertuples(index=False)
    }
    selected_key = st.selectbox("查看片段", list(segment_options.keys()))
    selected_id = segment_options[selected_key]
    selected = segments[segments["segment_id"] == selected_id].iloc[0]
    jump_cols = st.columns(3)
    jump_cols[0].button("在逐帧审计查看起点", on_click=set_inspect_time, args=(float(selected["start_time"]), predictions), key="segment_jump_start")
    peak_time = float(predictions[predictions["frame_id"] == int(selected["peak_frame"])].iloc[0]["elapsed_seconds"])
    jump_cols[1].button("在逐帧审计查看峰值帧", on_click=set_inspect_time, args=(peak_time, predictions), key="segment_jump_peak")
    jump_cols[2].button("在逐帧审计查看终点", on_click=set_inspect_time, args=(float(selected["end_time"]), predictions), key="segment_jump_end")

    left, right = st.columns([2, 1])
    with left:
        render_segment_details(result_dir, selected, predictions, temporal, capture_summary, screenshots)
    with right:
        render_manual_review(result_dir, selected)

    st.subheader("截图浏览")
    if screenshots.empty:
        st.info("没有找到 fall_screenshots。")
        return
    screenshot_mode = st.radio("截图筛选", ["选中片段", "按时间", "按 Probability", "低置信边界误报", "高置信 FALL"], horizontal=True)
    shot_df = screenshots.copy()
    if screenshot_mode == "选中片段":
        shot_df = shot_df[(shot_df["frame_id"] >= int(selected["start_frame"])) & (shot_df["frame_id"] <= int(selected["end_frame"]))]
    elif screenshot_mode == "按 Probability":
        shot_df = shot_df.sort_values("fall_probability", ascending=False)
    elif screenshot_mode == "低置信边界误报":
        shot_df = shot_df[(shot_df["fall_probability"] >= actual_threshold) & (shot_df["fall_probability"] < 0.60)]
    elif screenshot_mode == "高置信 FALL":
        shot_df = shot_df[shot_df["fall_probability"] >= 0.90]
    else:
        shot_df = shot_df.sort_values("frame_id")
    limit = st.slider("显示截图数量", 4, 48, 12, 4)
    for chunk_start in range(0, min(len(shot_df), limit), 4):
        cols = st.columns(4)
        for col, (_, shot) in zip(cols, shot_df.iloc[chunk_start : chunk_start + 4].iterrows()):
            caption = f"{float(shot['elapsed_seconds']):.3f}s | f{int(shot['frame_id'])} | p={float(shot['fall_probability']):.4f}"
            col.image(shot["path"], caption=caption, width="stretch")


if __name__ == "__main__":
    main()
