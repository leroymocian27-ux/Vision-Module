from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.events.qwen_keyframe import (
    QwenImageInput,
    QwenKeyframeAnalyzer,
    QwenKeyframeError,
    QwenKeyframeInvalidOutput,
    QwenKeyframeTimeout,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a localhost-only Qwen keyframe advisory smoke with six synthetic images.")
    parser.add_argument("--model", default="qwen-vision-cn:latest")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    images = _build_images()
    analyzer = QwenKeyframeAnalyzer(
        endpoint_url=args.endpoint,
        model_name=args.model,
        timeout_seconds=args.timeout,
    )
    try:
        detail = analyzer.analyze_post_fall(
            images=images,
            keyframe_status="ready",
            missing_offsets_ms=(),
        )
    except QwenKeyframeTimeout:
        print(json.dumps({"status": "REVISE", "reason": "qwen_timeout", "model_name": args.model}, ensure_ascii=False, indent=2))
        return 1
    except QwenKeyframeInvalidOutput:
        print(json.dumps({"status": "REVISE", "reason": "qwen_invalid_json", "model_name": args.model}, ensure_ascii=False, indent=2))
        return 1
    except QwenKeyframeError:
        print(json.dumps({"status": "REVISE", "reason": "qwen_unavailable", "model_name": args.model}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({
        "status": "PASS",
        "image_count": len(images),
        "model_name": args.model,
        "latency_ms": detail.latency_ms,
        "detail": asdict(detail),
    }, ensure_ascii=False, indent=2))
    return 0


def _build_images() -> list[QwenImageInput]:
    specs = [
        (-3000, "pre_context", (32, 48, 96), (26, 26, 160), "rect"),
        (-1000, "pre_fall", (48, 72, 120), (190, 190, 190), "circle"),
        (0, "trigger", (64, 96, 64), (220, 180, 40), "bar"),
        (1000, "post_fall", (72, 48, 120), (240, 120, 80), "ellipse"),
        (3000, "post_check", (96, 64, 48), (120, 220, 120), "line"),
        (5000, "post_check", (48, 96, 96), (200, 80, 200), "cross"),
    ]
    images: list[QwenImageInput] = []
    for offset_ms, role, background, accent, shape in specs:
        canvas = np.zeros((128, 192, 3), dtype=np.uint8)
        canvas[:, :] = background
        _draw_shape(canvas, shape, accent)
        ok, encoded = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise RuntimeError("failed to encode synthetic qwen smoke image")
        images.append(QwenImageInput(offset_ms=offset_ms, role=role, image_bytes=encoded.tobytes()))
    return images


def _draw_shape(canvas: np.ndarray, shape: str, color: tuple[int, int, int]) -> None:
    h, w = canvas.shape[:2]
    if shape == "rect":
        cv2.rectangle(canvas, (20, 28), (w - 28, h - 30), color, thickness=-1)
    elif shape == "circle":
        cv2.circle(canvas, (w // 2, h // 2), min(h, w) // 4, color, thickness=-1)
    elif shape == "bar":
        cv2.rectangle(canvas, (18, h // 2 - 16), (w - 18, h // 2 + 16), color, thickness=-1)
    elif shape == "ellipse":
        cv2.ellipse(canvas, (w // 2, h // 2), (w // 4, h // 5), 0, 0, 360, color, thickness=-1)
    elif shape == "line":
        cv2.line(canvas, (16, 16), (w - 16, h - 16), color, thickness=8)
    elif shape == "cross":
        cv2.line(canvas, (16, 16), (w - 16, h - 16), color, thickness=8)
        cv2.line(canvas, (w - 16, 16), (16, h - 16), color, thickness=8)


if __name__ == "__main__":
    sys.exit(main())
