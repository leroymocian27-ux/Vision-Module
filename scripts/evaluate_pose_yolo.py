from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
DATA_YAML = ROOT / "datasets" / "pose_yolo" / "data.yaml"
MODELS_DIR = ROOT / "models"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate YOLO Pose models on the project pose dataset.")
    parser.add_argument("--baseline", default="yolo11n-pose.pt")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--data", default=str(DATA_YAML))
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    parser.add_argument("--name", default="pose_yolo_batch001_003_yolo11n")
    args = parser.parse_args()

    baseline = evaluate_one(args.baseline, args.data, args.imgsz, args.device, "baseline")
    candidate = evaluate_one(args.candidate, args.data, args.imgsz, args.device, "candidate")
    comparison = {
        "baseline_model": args.baseline,
        "candidate_model": args.candidate,
        "data": str(Path(args.data).resolve()),
        "imgsz": args.imgsz,
        "device": args.device,
        "baseline": baseline,
        "candidate": candidate,
        "delta": {
            key: round(candidate.get(key, 0.0) - baseline.get(key, 0.0), 6)
            for key in sorted(set(baseline) | set(candidate))
            if isinstance(candidate.get(key, 0.0), (int, float)) and isinstance(baseline.get(key, 0.0), (int, float))
        },
    }
    out_path = MODELS_DIR / f"{args.name}_metrics.json"
    out_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    return 0


def evaluate_one(model_path: str, data: str, imgsz: int, device: str, split_name: str) -> dict[str, Any]:
    model = YOLO(model_path)
    metrics = model.val(
        data=data,
        split="test",
        imgsz=imgsz,
        device=device,
        project=str(ROOT / "runs" / "pose_yolo_eval"),
        name=split_name,
        exist_ok=True,
        plots=True,
    )
    return extract_metrics(metrics)


def extract_metrics(metrics: Any) -> dict[str, Any]:
    box = getattr(metrics, "box", None)
    pose = getattr(metrics, "pose", None)
    speed = getattr(metrics, "speed", {}) or {}
    return {
        "box_precision": scalar(getattr(box, "mp", None)),
        "box_recall": scalar(getattr(box, "mr", None)),
        "box_map50": scalar(getattr(box, "map50", None)),
        "box_map50_95": scalar(getattr(box, "map", None)),
        "pose_precision": scalar(getattr(pose, "mp", None)),
        "pose_recall": scalar(getattr(pose, "mr", None)),
        "pose_map50": scalar(getattr(pose, "map50", None)),
        "pose_map50_95": scalar(getattr(pose, "map", None)),
        "speed_ms": {key: scalar(value) for key, value in speed.items()},
    }


def scalar(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
