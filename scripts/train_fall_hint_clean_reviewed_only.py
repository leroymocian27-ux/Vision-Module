from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "external" / "fall_hint_base_20260703_clean" / "yolo11n_coco_clean_base_20260703.pt"
DEFAULT_DATA = ROOT / "datasets" / "fall_hint_v2_clean_reviewed_only_noaug_20260703" / "data.yaml"
DEFAULT_PROJECT = ROOT / "runs" / "fall_hint_v2_clean_reviewed_only"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train YOLO Fall Hint using clean reviewed-only data.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--name", default="yolo11n_coco_clean_reviewed_only_noaug_20260703")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--patience", type=int, default=25)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260703)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.project.mkdir(parents=True, exist_ok=True)
    config = {
        "model": str(args.model),
        "data": str(args.data),
        "project": str(args.project),
        "name": args.name,
        "epochs": args.epochs,
        "patience": args.patience,
        "batch": args.batch,
        "imgsz": args.imgsz,
        "device": args.device,
        "workers": args.workers,
        "seed": args.seed,
        "offline_augmentation_used": False,
        "base_type": "official_yolo11n_coco_detect",
        "training_style_reference": "runs/fall_hint_v2/yolo_fall_hint_v2_first/args.yaml",
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
        batch=args.batch,
        imgsz=args.imgsz,
        save=True,
        save_period=-1,
        cache=False,
        device=args.device,
        workers=args.workers,
        project=str(args.project),
        name=args.name,
        exist_ok=True,
        pretrained=True,
        optimizer="auto",
        verbose=True,
        seed=args.seed,
        deterministic=True,
        single_cls=False,
        rect=False,
        cos_lr=True,
        close_mosaic=10,
        resume=False,
        amp=True,
        fraction=1.0,
        val=True,
        split="val",
        conf=None,
        iou=0.7,
        max_det=300,
        plots=True,
        augment=False,
        lr0=0.01,
        lrf=0.01,
        momentum=0.937,
        weight_decay=0.0005,
        warmup_epochs=3.0,
        warmup_momentum=0.8,
        warmup_bias_lr=0.1,
        box=7.5,
        cls=0.5,
        dfl=1.5,
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        degrees=0.0,
        translate=0.1,
        scale=0.5,
        shear=0.0,
        perspective=0.0,
        flipud=0.0,
        fliplr=0.5,
        bgr=0.0,
        mosaic=1.0,
        mixup=0.0,
        copy_paste=0.0,
        erasing=0.4,
        crop_fraction=1.0,
    )

    run_dir = args.project / args.name
    summary = {
        "run_dir": str(run_dir),
        "best": str(run_dir / "weights" / "best.pt"),
        "last": str(run_dir / "weights" / "last.pt"),
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
