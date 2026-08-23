from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(description="Run a localhost-only Qwen keyframe advisory smoke with a synthetic image.")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    image = np.zeros((96, 160, 3), dtype=np.uint8)
    cv2.rectangle(image, (58, 24), (102, 82), (220, 220, 220), thickness=-1)
    ok, encoded = cv2.imencode(".jpg", image)
    if not ok:
        print(json.dumps({"status": "REVISE", "reason": "synthetic_image_encode_failed"}, ensure_ascii=False))
        return 1

    analyzer = QwenKeyframeAnalyzer(
        endpoint_url=args.endpoint,
        model_name=args.model,
        timeout_seconds=args.timeout,
    )
    try:
        advisory = analyzer.analyze(
            semantics=None,
            images=[QwenImageInput(offset_ms=0, role="trigger", image_bytes=encoded.tobytes())],
        )
    except QwenKeyframeTimeout:
        print(json.dumps({"status": "REVISE", "reason": "qwen_timeout", "model_name": args.model}, ensure_ascii=False))
        return 1
    except QwenKeyframeInvalidOutput:
        print(json.dumps({"status": "REVISE", "reason": "qwen_invalid_json", "model_name": args.model}, ensure_ascii=False))
        return 1
    except QwenKeyframeError:
        print(json.dumps({"status": "REVISE", "reason": "qwen_unavailable", "model_name": args.model}, ensure_ascii=False))
        return 1

    print(json.dumps({
        "status": "PASS" if advisory.analysis_status == "completed" else "REVISE",
        "input_type": "synthetic_image_only",
        "image_input": "local_ollama_only",
        "model_name": advisory.model_name,
        "latency_ms": advisory.latency_ms,
        "advisory": advisory.model_dump(mode="json"),
    }, ensure_ascii=False, indent=2))
    return 0 if advisory.analysis_status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
