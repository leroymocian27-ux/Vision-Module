from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "models" / "external" / "human-fall-detection-yolo11_20260703" / "best.pt"
DEFAULT_DATA = ROOT / "datasets" / "fall_hint_v2_reviewed_only_filtered_b001_b029_20260703" / "data.yaml"
DEFAULT_PROJECT = ROOT / "runs" / "fall_hint_v2_reviewed_only"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train YOLO Fall Hint on reviewed-only data, following the previous best two-stage flow."
    )
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--stage1-name", default="stage1_hfbase_reviewed_only_b001_b029_20260703")
    parser.add_argument("--stage2-name", default="stage2_from_stage1_reviewed_only_b001_b029_20260703")
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--stage1-epochs", type=int, default=80)
    parser.add_argument("--stage1-patience", type=int, default=25)
    parser.add_argument("--stage2-epochs", type=int, default=60)
    parser.add_argument("--stage2-patience", type=int, default=18)
    parser.add_argument("--skip-stage1", action="store_true")
    parser.add_argument("--stage1-best", type=Path, default=None)
    return parser.parse_args()


def train_once(
    model_path: Path,
    data: Path,
    project: Path,
    name: str,
    epochs: int,
    patience: int,
    seed: int,
    device: str,
    workers: int,
    batch: int,
    imgsz: int,
) -> Path:
    model = YOLO(str(model_path))
    model.train(
        data=str(data),
        epochs=epochs,
        patience=patience,
        batch=batch,
        imgsz=imgsz,
        save=True,
        save_period=-1,
        cache=False,
        device=device,
        workers=workers,
        project=str(project),
        name=name,
        exist_ok=True,
        pretrained=True,
        optimizer="auto",
        verbose=True,
        seed=seed,
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
    return project / name / "weights" / "best.pt"


def main() -> int:
    args = parse_args()
    args.project.mkdir(parents=True, exist_ok=True)
    config = {
        "base": str(args.base),
        "data": str(args.data),
        "project": str(args.project),
        "stage1_name": args.stage1_name,
        "stage2_name": args.stage2_name,
        "device": args.device,
        "workers": args.workers,
        "batch": args.batch,
        "imgsz": args.imgsz,
        "stage1_epochs": args.stage1_epochs,
        "stage1_patience": args.stage1_patience,
        "stage2_epochs": args.stage2_epochs,
        "stage2_patience": args.stage2_patience,
        "offline_augmentation_used": False,
        "flow_reference": [
            "runs/fall_hint_v2/yolo_fall_hint_v2_first/args.yaml",
            "runs/fall_hint_v2/yolo_fall_hint_v2_plus_b012/args.yaml",
        ],
    }
    (args.project / "reviewed_only_like_best_train_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(config, ensure_ascii=False, indent=2))

    if args.skip_stage1:
        if args.stage1_best is None:
            raise SystemExit("--skip-stage1 requires --stage1-best")
        stage1_best = args.stage1_best
    else:
        stage1_best = train_once(
            model_path=args.base,
            data=args.data,
            project=args.project,
            name=args.stage1_name,
            epochs=args.stage1_epochs,
            patience=args.stage1_patience,
            seed=42,
            device=args.device,
            workers=args.workers,
            batch=args.batch,
            imgsz=args.imgsz,
        )

    if not stage1_best.exists():
        raise SystemExit(f"stage1 best weight missing: {stage1_best}")

    stage2_best = train_once(
        model_path=stage1_best,
        data=args.data,
        project=args.project,
        name=args.stage2_name,
        epochs=args.stage2_epochs,
        patience=args.stage2_patience,
        seed=43,
        device=args.device,
        workers=args.workers,
        batch=args.batch,
        imgsz=args.imgsz,
    )

    summary = {
        "stage1_best": str(stage1_best),
        "stage2_best": str(stage2_best),
        "stage1_run": str(args.project / args.stage1_name),
        "stage2_run": str(args.project / args.stage2_name),
    }
    (args.project / "reviewed_only_like_best_train_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
