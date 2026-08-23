from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a YOLO person detector on the person_yolo dataset.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", default=str(ROOT / "datasets" / "person_yolo" / "data.yaml"))
    parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    parser.add_argument("--project", default=str(ROOT / "runs" / "person_yolo_eval"))
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    model = YOLO(args.model)
    metrics = model.val(
        data=args.data,
        split=args.split,
        imgsz=args.imgsz,
        device=args.device,
        project=args.project,
        name=args.name,
        exist_ok=True,
        workers=0,
        verbose=True,
    )
    summary = {
        "model": str(Path(args.model)),
        "data": str(Path(args.data)),
        "split": args.split,
        "save_dir": str(metrics.save_dir),
        "precision": float(metrics.box.mp),
        "recall": float(metrics.box.mr),
        "map50": float(metrics.box.map50),
        "map50_95": float(metrics.box.map),
    }
    out_path = Path(metrics.save_dir) / "person_eval_summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
