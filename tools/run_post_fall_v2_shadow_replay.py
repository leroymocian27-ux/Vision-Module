from __future__ import annotations

import argparse
import time
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.post_fall_v2.fall_binary_classifier_service import FallBinaryClassifierService
from app.post_fall_v2.fall_shadow_evidence_service import FallShadowEvidenceService
from app.post_fall_v2.schemas import FULL_FRAME_TRAIN_MATCHED, SampledFrame, monotonic_to_utc_iso


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
DEFAULT_MODEL = "models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx"
DEFAULT_SHA256 = "e9871cdb4687055fb5d934dd994c2ad883adac0c2acab375c240f8e005ee04cc"
DEFAULT_THRESHOLD = 0.3979087471961975


def collect_images(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"unsupported image extension: {path}")
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(path)
    return sorted(item for item in path.rglob("*") if item.suffix.lower() in IMAGE_EXTENSIONS)


def read_image_bgr(path: Path):
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def sampled_from_frame(frame, *, camera_id: str, seq: int, sampled_at: float) -> SampledFrame:
    height, width = frame.shape[:2]
    return SampledFrame(
        camera_id=camera_id,
        frame_id=f"{camera_id}_replay_{seq:08d}",
        frame_seq=seq,
        captured_at=monotonic_to_utc_iso(sampled_at),
        sampled_at=monotonic_to_utc_iso(sampled_at),
        captured_monotonic=sampled_at,
        sampled_monotonic=sampled_at,
        source_width=int(width),
        source_height=int(height),
        source_generation=0,
        frame=frame,
    )


def run_image_replay(args, classifier: FallBinaryClassifierService, recorder: FallShadowEvidenceService) -> tuple[int, int]:
    processed = 0
    candidates = 0
    for seq, path in enumerate(collect_images(args.input), start=1):
        frame = read_image_bgr(path)
        if frame is None:
            continue
        sampled = sampled_from_frame(frame, camera_id=args.camera_id, seq=seq, sampled_at=time.monotonic())
        result = classifier.infer(sampled)
        recorder.write(result, sampled)
        processed += 1
        candidates += int(result.shadow_candidate_hint)
    return processed, candidates


def run_video_replay(args, classifier: FallBinaryClassifierService, recorder: FallShadowEvidenceService) -> tuple[int, int]:
    capture = cv2.VideoCapture(str(args.input))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video: {args.input}")
    native_fps = capture.get(cv2.CAP_PROP_FPS) or args.sample_fps
    frame_interval = max(1, round(native_fps / max(args.sample_fps, 0.01)))
    processed = 0
    candidates = 0
    seq = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            seq += 1
            if seq % frame_interval != 0:
                continue
            sampled = sampled_from_frame(frame, camera_id=args.camera_id, seq=seq, sampled_at=time.monotonic())
            result = classifier.infer(sampled)
            recorder.write(result, sampled)
            processed += 1
            candidates += int(result.shadow_candidate_hint)
    finally:
        capture.release()
    return processed, candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Post-Fall V2 binary classifier in offline shadow replay mode.")
    parser.add_argument("--input", type=Path, required=True, help="Image file, image directory, or video file.")
    parser.add_argument("--input-kind", choices=["image", "directory", "video"], default=None)
    parser.add_argument("--camera-id", default="offline_replay")
    parser.add_argument("--sample-fps", type=float, default=2.0)
    parser.add_argument("--model", type=Path, default=Path(DEFAULT_MODEL))
    parser.add_argument("--model-sha256", default=DEFAULT_SHA256)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/post_fall_v2/shadow"))
    parser.add_argument("--save-frames", action="store_true")
    parser.add_argument("--save-frame-threshold", type=float, default=0.30)
    args = parser.parse_args()

    input_kind = args.input_kind
    if input_kind is None:
        input_kind = "directory" if args.input.is_dir() else ("image" if args.input.suffix.lower() in IMAGE_EXTENSIONS else "video")

    classifier = FallBinaryClassifierService(
        model_path=args.model,
        expected_sha256=args.model_sha256,
        threshold=args.threshold,
        input_policy=FULL_FRAME_TRAIN_MATCHED,
    )
    recorder = FallShadowEvidenceService(
        output_dir=args.output_dir,
        save_metadata=True,
        save_frames=args.save_frames,
        save_frame_probability_threshold=args.save_frame_threshold,
    )
    if input_kind in {"image", "directory"}:
        processed, candidates = run_image_replay(args, classifier, recorder)
    else:
        processed, candidates = run_video_replay(args, classifier, recorder)
    print(
        {
            "processed": processed,
            "shadow_candidate_hints": candidates,
            "provider": classifier.provider,
            "records_written": recorder.records_written,
            "output_dir": str(args.output_dir),
        }
    )


if __name__ == "__main__":
    main()
