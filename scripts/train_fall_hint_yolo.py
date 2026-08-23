from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "external" / "fall_hint_base" / "yolo11s_coco_fall_hint_base_2026-07-02.pt"
DEFAULT_DATA = ROOT / "datasets" / "fall_hint_v2_training_reviewed_aug_filtered_20260702" / "data.yaml"
DEFAULT_PROJECT = ROOT / "runs" / "fall_hint_v2"
DEFAULT_NAME = "yolo11s_reviewed_aug_filtered_20260702_e80"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a YOLO Fall Hint detector.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260702)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = args.project / args.name
    args.project.mkdir(parents=True, exist_ok=True)
    config = {
        "model": str(args.model),
        "data": str(args.data),
        "project": str(args.project),
        "name": args.name,
        "epochs": args.epochs,
        "patience": args.patience,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "device": args.device,
        "workers": args.workers,
        "seed": args.seed,
        "resume": args.resume,
        "augmentation_policy": {
            "mosaic": 0.0,
            "mixup": 0.0,
            "copy_paste": 0.0,
            "erasing": 0.0,
            "degrees": 5.0,
            "translate": 0.05,
            "scale": 0.10,
            "shear": 0.0,
            "perspective": 0.0,
            "flipud": 0.0,
            "fliplr": 0.5,
            "hsv_h": 0.01,
            "hsv_s": 0.20,
            "hsv_v": 0.20,
        },
    }
    (args.project / f"{args.name}_train_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(config, ensure_ascii=False, indent=2))

    model = YOLO(str(args.model))
    result = model.train(
        data=str(args.data),
        epochs=args.epochs,
        patience=args.patience,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        project=str(args.project),
        name=args.name,
        exist_ok=args.resume,
        resume=args.resume,
        save=True,
        save_period=10,
        val=True,
        plots=True,
        amp=True,
        seed=args.seed,
        deterministic=True,
        mosaic=0.0,
        mixup=0.0,
        copy_paste=0.0,
        erasing=0.0,
        degrees=5.0,
        translate=0.05,
        scale=0.10,
        shear=0.0,
        perspective=0.0,
        flipud=0.0,
        fliplr=0.5,
        hsv_h=0.01,
        hsv_s=0.20,
        hsv_v=0.20,
    )

    weights_dir = run_dir / "weights"
    summary = {
        "run_dir": str(run_dir),
        "best": str(weights_dir / "best.pt"),
        "last": str(weights_dir / "last.pt"),
        "result_type": type(result).__name__,
    }
    (run_dir / "train_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
