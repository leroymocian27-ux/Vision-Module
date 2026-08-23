from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.demo_terminal_format import (  # noqa: E402
    banner,
    bullet,
    final_status,
    json_block,
    open_artifact,
    path_block,
    run_with_guard,
    section,
)


DEFAULT_VIDEO_SOURCE = Path(
    r"D:\WeChat\xwechat_files\wxid_k047egb6o87f22_adc9\msg\video\2026-07\78eb6899a713f81b021636efedfc82bc.mp4"
)
DEFAULT_OUTPUT_DIR = ROOT / "artifacts" / "model_showcase"
HEALTH1_MODEL_ROOT = Path(r"D:\Program\model\fall_detection")
DEFAULT_PERSON_MODEL = HEALTH1_MODEL_ROOT / "yolo11n-pose.pt"
DEFAULT_FALL_MODEL = HEALTH1_MODEL_ROOT / "weights" / "yolo_fall_detector_v1.pt"
DEFAULT_POSE_MODEL = HEALTH1_MODEL_ROOT / "yolo11n-pose.pt"
DEFAULT_POSTURE_MODEL = HEALTH1_MODEL_ROOT / "runs" / "yolo_posture_person_binary_cls_v1" / "weights" / "best.pt"
DEFAULT_TCN_WEIGHTS = HEALTH1_MODEL_ROOT / "weights" / "pose_tcn_fall_v2.pt"
DEFAULT_TEMPORAL_MODEL = ROOT / "models" / "fall_lstm_v5.onnx"
DEFAULT_TEMPORAL_SCHEMA = ROOT / "models" / "fall_lstm_v5_features.json"
SHOWCASE_ASSET_DIR = ROOT / "models" / "showcase_assets" / "health1_demo"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a local model showcase video using demo-only copies of the health1 model assets."
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=DEFAULT_VIDEO_SOURCE,
        help="Input video path. Defaults to the uploaded local demo video.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated showcase artifacts.",
    )
    parser.add_argument(
        "--output-video",
        type=Path,
        default=None,
        help="Optional explicit output video path.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Optional explicit JSON summary path.",
    )
    parser.add_argument(
        "--mode",
        choices=["health1_pose_tcn", "system", "fall", "person"],
        default="health1_pose_tcn",
        help="health1_pose_tcn runs the demo-only pose+TCN showcase; system/fall/person reuse the current repo renderers with demo model assets.",
    )
    parser.add_argument("--camera-id", default="showcase_camera")
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--person-model", type=Path, default=DEFAULT_PERSON_MODEL)
    parser.add_argument("--fall-model", type=Path, default=DEFAULT_FALL_MODEL)
    parser.add_argument("--pose-model", type=Path, default=DEFAULT_POSE_MODEL)
    parser.add_argument("--posture-model", type=Path, default=DEFAULT_POSTURE_MODEL)
    parser.add_argument("--tcn-weights", type=Path, default=DEFAULT_TCN_WEIGHTS)
    parser.add_argument("--temporal-model", type=Path, default=DEFAULT_TEMPORAL_MODEL)
    parser.add_argument("--temporal-schema", type=Path, default=DEFAULT_TEMPORAL_SCHEMA)
    parser.add_argument("--sequence-length", type=int, default=32)
    parser.add_argument("--imgsz", type=int, default=384)
    parser.add_argument("--conf", type=float, default=0.2)
    parser.add_argument("--max-frames", type=int, default=0, help="0 means full video.")
    parser.add_argument(
        "--copy-missing-models",
        action="store_true",
        default=True,
        help="Copy missing external model files into this repo before running.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    original_source = args.source.expanduser().resolve()
    if not original_source.is_file():
        raise FileNotFoundError(f"Input video not found: {original_source}")
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = ensure_showcase_source(original_source, output_dir=output_dir)

    section("Resolve Assets")
    path_block("Original video", original_source)
    path_block("Showcase video source", source)

    person_model = resolve_model(
        args.person_model,
        fallback_candidates=[HEALTH1_MODEL_ROOT / "yolo11n-pose.pt", ROOT / "yolov8n.pt", Path(r"D:\Program\model\fall_detection\yolo11n.pt")],
        copy_missing=args.copy_missing_models,
        local_name="yolo11n-pose.pt",
    )
    fall_model = resolve_model(
        args.fall_model,
        fallback_candidates=[
            HEALTH1_MODEL_ROOT / "weights" / "yolo_fall_detector_v1.pt",
            ROOT / "models" / "yolo_fall_hint_candidate_v3_c_temporal_friendly_20260705.pt",
            ROOT / "models" / "yolo_fall_hint_v2_plus_b012_best.pt",
            ROOT / "models" / "7-3bestmodel.pt",
        ],
        copy_missing=args.copy_missing_models,
        local_name="yolo_fall_detector_v1.pt",
    )
    pose_model = resolve_model(
        args.pose_model,
        fallback_candidates=[
            HEALTH1_MODEL_ROOT / "yolo11n-pose.pt",
            ROOT / "models" / "pose_yolo_batch001_003_yolo11s_best.pt",
            ROOT / "yolo11s-pose.pt",
            ROOT / "yolo11n-pose.pt",
            Path(r"D:\Program\model\fall_detection\yolo11n-pose.pt"),
        ],
        copy_missing=args.copy_missing_models,
        local_name="yolo11n-pose.pt",
    )
    posture_model = resolve_model(
        args.posture_model,
        fallback_candidates=[
            HEALTH1_MODEL_ROOT / "runs" / "yolo_posture_person_binary_cls_v1" / "weights" / "best.pt",
        ],
        copy_missing=args.copy_missing_models,
        local_name="yolo_posture_person_binary_cls_best.pt",
    )
    tcn_weights = resolve_model(
        args.tcn_weights,
        fallback_candidates=[
            HEALTH1_MODEL_ROOT / "weights" / "pose_tcn_fall_v2.pt",
        ],
        copy_missing=args.copy_missing_models,
        local_name="pose_tcn_fall_v2.pt",
    )
    temporal_model = resolve_model(
        args.temporal_model,
        fallback_candidates=[ROOT / "models" / "fall_lstm_v5.onnx"],
        copy_missing=args.copy_missing_models,
    )
    temporal_schema = resolve_model(
        args.temporal_schema,
        fallback_candidates=[ROOT / "models" / "fall_lstm_v5_features.json"],
        copy_missing=args.copy_missing_models,
    )

    path_block("Person model", person_model)
    path_block("Fall model", fall_model)
    path_block("Pose model", pose_model)
    path_block("Posture model", posture_model)
    path_block("TCN model", tcn_weights)
    path_block("Temporal model", temporal_model)
    path_block("Temporal schema", temporal_schema)

    video_slug = safe_slug(source.stem)
    suffix = {
        "health1_pose_tcn": "health1_pose_tcn_showcase",
        "system": "system_showcase",
        "fall": "fall_detector_showcase",
        "person": "person_detector_showcase",
    }[args.mode]
    output_video = args.output_video.expanduser().resolve() if args.output_video else output_dir / f"{video_slug}_{suffix}.mp4"
    json_output = args.json.expanduser().resolve() if args.json else output_dir / f"{video_slug}_{suffix}.json"

    section("Configure Runtime")
    configure_showcase_environment(
        person_model=person_model,
        fall_model=fall_model,
        pose_model=pose_model,
        posture_model=posture_model,
        tcn_weights=tcn_weights,
        temporal_model=temporal_model,
        temporal_schema=temporal_schema,
    )
    bullet("Runtime configured for demo-only showcase assets.", kind="ok")
    path_block("Output video", output_video)
    path_block("Output JSON", json_output)

    section("Run Showcase")
    if args.mode == "health1_pose_tcn":
        from scripts.showcase_legacy.pose_tcn_demo import run_pose_tcn_showcase  # noqa: E402

        payload = run_pose_tcn_showcase(
            source=source,
            output_video=output_video,
            pose_model_path=pose_model,
            tcn_weights_path=tcn_weights,
            sequence_length=max(1, args.sequence_length),
            imgsz=max(32, args.imgsz),
            conf=max(0.01, args.conf),
            max_frames=max(0, args.max_frames),
        )
    else:
        from scripts.render_fall_video_offline import render_detector_video, render_video  # noqa: E402

        if args.mode == "system":
            payload = render_video(
                video_path=source,
                output_dir=output_dir,
                camera_id=args.camera_id,
                frame_stride=max(1, args.frame_stride),
                output_video=output_video,
            )
        else:
            payload = render_detector_video(
                video_path=source,
                output_dir=output_dir,
                output_video=output_video,
                detector_mode=args.mode,
            )

    payload["showcase_models"] = {
        "person_model": str(person_model),
        "fall_model": str(fall_model),
        "pose_model": str(pose_model),
        "posture_model": str(posture_model),
        "tcn_weights": str(tcn_weights),
        "temporal_model": str(temporal_model),
        "temporal_schema": str(temporal_schema),
    }
    json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    json_block("Result", payload)

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    items = [
        ("mode", args.mode),
        ("frames", payload.get("frame_count")),
        ("processed_frames", payload.get("processed_frames")),
        ("elapsed_seconds", payload.get("elapsed_seconds")),
        ("output_video", payload.get("output_video")),
        ("json", str(json_output)),
    ]
    if args.mode == "health1_pose_tcn":
        items.extend(
            [
                ("status_counts", summary.get("status_counts")),
                ("max_fall_probability", summary.get("max_fall_probability")),
            ]
        )
    elif summary:
        items.extend(
            [
                ("fall_confirm", summary.get("fall_confirm")),
                ("fall_state_peak", summary.get("fall_state_peak")),
                ("incident_id", summary.get("incident_id")),
            ]
        )
    final_status("Model showcase demo completed", color="green", items=items)
    open_artifact(payload.get("output_video"), label="showcase video")
    return 0


def resolve_model(path: Path, *, fallback_candidates: list[Path], copy_missing: bool, local_name: str | None = None) -> Path:
    preferred = path.expanduser()
    if preferred.is_file():
        return ensure_local_copy(preferred, local_name=local_name) if copy_missing else preferred.resolve()

    candidates = [candidate.expanduser() for candidate in fallback_candidates]
    for candidate in candidates:
        if candidate.is_file():
            return ensure_local_copy(candidate, local_name=local_name) if copy_missing else candidate.resolve()

    candidate_list = [str(preferred), *[str(item) for item in candidates]]
    raise FileNotFoundError("Model not found. Checked: " + " | ".join(candidate_list))


def ensure_local_copy(path: Path, *, local_name: str | None = None) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
        return resolved
    except ValueError:
        SHOWCASE_ASSET_DIR.mkdir(parents=True, exist_ok=True)
        target = SHOWCASE_ASSET_DIR / (local_name or resolved.name)
        if not target.exists():
            shutil.copy2(resolved, target)
        return target.resolve()


def ensure_showcase_source(path: Path, *, output_dir: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT)
        return resolved
    except ValueError:
        input_dir = output_dir / "inputs"
        input_dir.mkdir(parents=True, exist_ok=True)
        target = input_dir / resolved.name
        if not target.exists() or target.stat().st_size != resolved.stat().st_size:
            shutil.copy2(resolved, target)
        return target.resolve()


def configure_showcase_environment(
    *,
    person_model: Path,
    fall_model: Path,
    pose_model: Path,
    posture_model: Path,
    tcn_weights: Path,
    temporal_model: Path,
    temporal_schema: Path,
) -> None:
    env_updates = {
        "VISION_SERVICE_RUNTIME_PROFILE": "model_showcase_demo",
        "ENABLE_TRACKING": "true",
        "ENABLE_POSE": "true",
        "POSE_PROVIDER": "yolo11_legacy",
        "ENABLE_BEHAVIOR": "true",
        "ENABLE_TEMPORAL": "true",
        "TEMPORAL_TRACK_MODE": "all_tracks",
        "TEMPORAL_SEQUENCE_KEY_MODE": "spatial",
        "TEMPORAL_MODEL_PROVIDER": "onnx_lstm",
        "POSE_FALLBACK_TO_DETECTION": "true",
        "POSE_FALLBACK_MIN_CONFIDENCE": "0.15",
        "MAIN_SYSTEM_ALERT_ENABLED": "false",
        "VISION_SERVICE_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
        "TEMPORAL_ONNX_PROVIDERS": "CPUExecutionProvider",
        "YOLO_DEVICE": "",
        "YOLO_FALL_DEVICE": "",
        "YOLO_POSE_DEVICE": "",
        "YOLO11_POSE_DEVICE": "",
        "SHOWCASE_MODEL_SOURCE_PROFILE": "health1_demo_only",
        "YOLO_MODEL_PATH": str(person_model),
        "YOLO_FALL_MODEL_PATH": str(fall_model),
        "YOLO_POSE_MODEL_PATH": str(pose_model),
        "YOLO11_POSE_MODEL_PATH": str(pose_model),
        "SHOWCASE_POSTURE_MODEL_PATH": str(posture_model),
        "SHOWCASE_TCN_WEIGHTS_PATH": str(tcn_weights),
        "TEMPORAL_ONNX_MODEL_PATH": str(temporal_model),
        "TEMPORAL_FEATURE_SCHEMA_PATH": str(temporal_schema),
    }
    for key, value in env_updates.items():
        os.environ[key] = value


def safe_slug(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_").lower() or "video"


if __name__ == "__main__":
    raise SystemExit(run_with_guard(main, script_name="run_model_showcase_demo.py"))
