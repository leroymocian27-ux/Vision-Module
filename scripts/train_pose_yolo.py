from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
DATA_YAML = ROOT / "datasets" / "pose_yolo" / "data.yaml"
RUNS_DIR = ROOT / "runs" / "pose_yolo"
MODELS_DIR = ROOT / "models"


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a project-specific YOLO Pose model.")
    parser.add_argument("--model", default="yolo11n-pose.pt")
    parser.add_argument("--data", default=str(DATA_YAML))
    parser.add_argument("--name", default="pose_yolo_batch001_003_yolo11n")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--patience", type=int, default=30)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260630)
    args = parser.parse_args()

    model = YOLO(args.model)
    train_result = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=args.patience,
        device=args.device,
        workers=args.workers,
        project=str(RUNS_DIR),
        name=args.name,
        exist_ok=True,
        seed=args.seed,
        deterministic=True,
        pretrained=True,
        plots=True,
        val=True,
    )

    run_dir = Path(getattr(train_result, "save_dir", RUNS_DIR / args.name))
    best = run_dir / "weights" / "best.pt"
    last = run_dir / "weights" / "last.pt"
    if not best.exists():
        raise SystemExit(f"best.pt not found: {best}")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    out_model = MODELS_DIR / f"{args.name}_best.pt"
    out_model.write_bytes(best.read_bytes())

    summary = {
        "model": args.model,
        "data": str(Path(args.data).resolve()),
        "run_dir": str(run_dir.resolve()),
        "best": str(best.resolve()),
        "last": str(last.resolve()) if last.exists() else "",
        "exported_model": str(out_model.resolve()),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "device": args.device,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
    }
    summary_path = MODELS_DIR / f"{args.name}_train_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
