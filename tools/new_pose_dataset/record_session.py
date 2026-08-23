from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests
from PIL import Image


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def fetch_json(url: str, *, params: dict[str, Any] | None = None, timeout: float = 4.0) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def fetch_jpeg(url: str, *, params: dict[str, Any] | None = None, timeout: float = 4.0) -> bytes:
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.content


def decode_jpeg(content: bytes) -> np.ndarray:
    array = np.frombuffer(content, dtype=np.uint8)
    frame = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("failed_to_decode_jpeg")
    return frame


def build_qa_report(
    *,
    session_id: str,
    action_label: str,
    duration_sec: float,
    frame_count: int,
    estimated_fps: float,
    missing_frame_count: int,
    status_sample_count: int,
    integration_sample_count: int,
    pose_enabled: Any,
    pose_provider: Any,
    stream_state: Any,
    latest_frame_ok: bool,
    quality_status: str,
    recommended_action: str,
    retake_reason: str | None,
) -> str:
    return "\n".join(
        [
            "# QA Report",
            "",
            f"- session_id: `{session_id}`",
            f"- action_label: `{action_label}`",
            f"- duration_sec: `{round(duration_sec, 2)}`",
            f"- frame_count: `{frame_count}`",
            f"- estimated_fps: `{round(estimated_fps, 2)}`",
            f"- missing_frame_count: `{missing_frame_count}`",
            f"- status_sample_count: `{status_sample_count}`",
            f"- integration_sample_count: `{integration_sample_count}`",
            f"- pose_enabled: `{pose_enabled}`",
            f"- pose_provider: `{pose_provider}`",
            f"- stream_state: `{stream_state}`",
            f"- latest_frame_ok: `{latest_frame_ok}`",
            f"- quality_status: `{quality_status}`",
            f"- retake_reason: `{retake_reason}`",
            f"- recommended_action: `{recommended_action}`",
            "",
        ]
    ) + "\n"


def save_preview_gif(frames: list[np.ndarray], output_path: Path, fps: float) -> None:
    if not frames:
        return
    pil_frames: list[Image.Image] = []
    for frame in frames:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_frames.append(Image.fromarray(rgb))
    duration_ms = max(80, int(1000 / max(1.0, fps)))
    pil_frames[0].save(
        output_path,
        save_all=True,
        append_images=pil_frames[1:],
        duration=duration_ms,
        loop=0,
    )


def choose_quality_status(frame_count: int, latest_frame_ok: bool, missing_frame_count: int) -> tuple[str, str | None, str]:
    if not latest_frame_ok or frame_count <= 0:
        return "FAIL", "latest_frame_capture_failed", "retake_required"
    if missing_frame_count > max(5, frame_count * 0.2):
        return "RETAKE_RECOMMENDED", "too_many_missing_frames", "retake_recommended"
    return "PASS", None, "usable_for_training_review"


def record_session(args: argparse.Namespace) -> Path:
    base_url = args.base_url.rstrip("/")
    session_dir = Path(args.session_dir).resolve()
    metadata_path = session_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"missing metadata.json in {session_dir}")

    metadata = read_json(metadata_path)
    camera_id = args.camera_id
    session_id = str(metadata.get("session_id") or session_dir.name)
    action_label = str(metadata.get("primary_action") or "unknown")

    status_path = session_dir / "status_samples.jsonl"
    integration_path = session_dir / "integration_latest_samples.jsonl"
    video_path = session_dir / "video.mp4"
    preview_path = session_dir / "preview.gif"
    notes_path = session_dir / "notes.md"
    qa_path = session_dir / "qa_report.md"

    frames: list[np.ndarray] = []
    gif_frames: list[np.ndarray] = []
    last_status = 0.0
    last_integration = 0.0
    last_gif_capture = 0.0
    missing_frame_count = 0
    latest_frame_ok = False
    writer: cv2.VideoWriter | None = None
    frame_width: int | None = None
    frame_height: int | None = None
    capture_started_at = time.monotonic()
    started_utc = utc_now_iso()

    while time.monotonic() - capture_started_at < args.duration_sec:
        loop_started = time.monotonic()
        sample_timestamp = utc_now_iso()

        try:
            frame_bytes = fetch_jpeg(
                f"{base_url}/stream/latest-frame.jpg",
                params={"camera_id": camera_id},
                timeout=args.timeout_sec,
            )
            frame = decode_jpeg(frame_bytes)
            latest_frame_ok = True
            if writer is None:
                frame_height, frame_width = frame.shape[:2]
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(str(video_path), fourcc, float(args.output_fps), (frame_width, frame_height))
                if not writer.isOpened():
                    raise RuntimeError("video_writer_open_failed")
            writer.write(frame)
            frames.append(frame.copy())
            if loop_started - last_gif_capture >= 1.0 / max(1.0, args.preview_fps):
                gif_frames.append(frame.copy())
                last_gif_capture = loop_started
        except Exception as exc:
            missing_frame_count += 1
            append_jsonl(
                status_path,
                {
                    "timestamp": sample_timestamp,
                    "source": "record_session_frame_error",
                    "camera_id": camera_id,
                    "error": str(exc),
                },
            )

        if loop_started - last_status >= args.status_interval_sec:
            last_status = loop_started
            try:
                status_payload = fetch_json(
                    f"{base_url}/status",
                    params={"camera_id": camera_id},
                    timeout=args.timeout_sec,
                )
                append_jsonl(
                    status_path,
                    {
                        "timestamp": sample_timestamp,
                        "source": "status",
                        "data": status_payload,
                    },
                )
            except Exception as exc:
                append_jsonl(
                    status_path,
                    {
                        "timestamp": sample_timestamp,
                        "source": "status",
                        "error": str(exc),
                    },
                )

        if loop_started - last_integration >= args.integration_interval_sec:
            last_integration = loop_started
            try:
                integration_payload = fetch_json(
                    f"{base_url}/integration/results/{camera_id}/latest",
                    timeout=args.timeout_sec,
                )
                append_jsonl(
                    integration_path,
                    {
                        "timestamp": sample_timestamp,
                        "source": "integration_latest",
                        "data": integration_payload,
                    },
                )
            except Exception as exc:
                append_jsonl(
                    integration_path,
                    {
                        "timestamp": sample_timestamp,
                        "source": "integration_latest",
                        "error": str(exc),
                    },
                )

        elapsed = time.monotonic() - loop_started
        sleep_sec = max(0.0, (1.0 / max(1.0, args.output_fps)) - elapsed)
        time.sleep(sleep_sec)

    ended_utc = utc_now_iso()
    actual_duration = max(0.001, time.monotonic() - capture_started_at)
    if writer is not None:
        writer.release()
    save_preview_gif(gif_frames or frames[: min(len(frames), 20)], preview_path, args.preview_fps)

    status_sample_count = sum(1 for _ in status_path.open("r", encoding="utf-8")) if status_path.exists() else 0
    integration_sample_count = (
        sum(1 for _ in integration_path.open("r", encoding="utf-8")) if integration_path.exists() else 0
    )
    estimated_fps = len(frames) / actual_duration

    latest_status = fetch_json(f"{base_url}/status", params={"camera_id": camera_id}, timeout=args.timeout_sec)
    pose_status = latest_status.get("pose") if isinstance(latest_status.get("pose"), dict) else {}
    camera_status = (latest_status.get("cameras") or [{}])[0]
    stream_state = camera_status.get("stream_state")
    quality_status, retake_reason, recommended_action = choose_quality_status(
        len(frames),
        latest_frame_ok,
        missing_frame_count,
    )

    metadata["recorded_at"] = started_utc
    metadata["duration_sec"] = round(actual_duration, 2)
    metadata["fps"] = round(estimated_fps, 2)
    metadata["resolution"] = f"{frame_width}x{frame_height}" if frame_width and frame_height else ""
    metadata["pose_provider"] = pose_status.get("pose_provider", metadata.get("pose_provider", "disabled_placeholder"))
    metadata["pose_enabled"] = bool(pose_status.get("pose_enabled", metadata.get("pose_enabled", False)))
    metadata["quality_notes"] = f"quality_status={quality_status}; missing_frame_count={missing_frame_count}"
    write_json(metadata_path, metadata)

    with notes_path.open("a", encoding="utf-8") as notes_handle:
        notes_handle.write(
            "\n".join(
                [
                    f"- actual_start_time: {started_utc}",
                    f"- actual_end_time: {ended_utc}",
                    f"- recorded_duration_sec: {round(actual_duration, 2)}",
                    f"- estimated_fps: {round(estimated_fps, 2)}",
                    f"- missing_frame_count: {missing_frame_count}",
                    f"- quality_status: {quality_status}",
                    f"- retake_reason: {retake_reason}",
                    "",
                ]
            )
        )

    qa_path.write_text(
        build_qa_report(
            session_id=session_id,
            action_label=action_label,
            duration_sec=actual_duration,
            frame_count=len(frames),
            estimated_fps=estimated_fps,
            missing_frame_count=missing_frame_count,
            status_sample_count=status_sample_count,
            integration_sample_count=integration_sample_count,
            pose_enabled=metadata["pose_enabled"],
            pose_provider=metadata["pose_provider"],
            stream_state=stream_state,
            latest_frame_ok=latest_frame_ok,
            quality_status=quality_status,
            recommended_action=recommended_action,
            retake_reason=retake_reason,
        ),
        encoding="utf-8",
    )

    return session_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record one raw session from the current 8000 live service.")
    parser.add_argument("--session-dir", required=True, help="Target session directory created by create_session.py.")
    parser.add_argument("--duration-sec", required=True, type=float, help="Recording duration in seconds.")
    parser.add_argument("--camera-id", default="camera_01", help="Camera id.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Vision service base url.")
    parser.add_argument("--output-fps", type=float, default=4.0, help="Target output video fps built from latest-frame polling.")
    parser.add_argument("--preview-fps", type=float, default=2.0, help="Preview gif fps.")
    parser.add_argument("--status-interval-sec", type=float, default=0.5, help="Status sample interval.")
    parser.add_argument(
        "--integration-interval-sec",
        type=float,
        default=0.5,
        help="Integration latest sample interval.",
    )
    parser.add_argument("--timeout-sec", type=float, default=4.0, help="HTTP request timeout.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    session_dir = record_session(args)
    print(session_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
