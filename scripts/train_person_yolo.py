from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the single-class YOLO person detector.")
    parser.add_argument("--data", default=str(ROOT / "datasets" / "person_yolo" / "data.yaml"))
    parser.add_argument("--model", default=str(ROOT / "yolov8n.pt"))
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="0")
    parser.add_argument("--project", default=str(ROOT / "runs" / "person_yolo"))
    parser.add_argument("--name", default="batch_001_yolov8n_person_v1")
    parser.add_argument("--seed", type=int, default=20260629)
    args = parser.parse_args()

    model = YOLO(args.model)
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
        seed=args.seed,
        workers=0,
        patience=20,
        close_mosaic=10,
        cos_lr=True,
        exist_ok=True,
        verbose=True,
    )
    save_dir = Path(results.save_dir)
    summary = {
        "data": str(Path(args.data)),
        "base_model": str(Path(args.model)),
        "save_dir": str(save_dir),
        "best_model": str(save_dir / "weights" / "best.pt"),
        "last_model": str(save_dir / "weights" / "last.pt"),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "device": args.device,
    }
    (save_dir / "person_train_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
