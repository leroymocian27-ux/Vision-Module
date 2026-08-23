from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"
DEFAULT_MODEL = ROOT / "models" / "external" / "human-fall-detection-yolo11" / "best.pt"

CLASS_NAMES = {
    0: "falling",
    1: "fallen",
    2: "lying",
    3: "sitting",
    4: "bending",
    5: "kneeling",
    6: "standing",
}

HF_TO_FALL_HINT_V2 = {
    "falling": 0,
    "fallen": 1,
    "lying": 2,
    "sitting": 3,
    "bending": 4,
    "kneeling": 5,
    "standing": 6,
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create mapped YOLO draft labels for a fall_hint_v2 human-review batch."
    )
    parser.add_argument("--batch-id", default="batch_001")
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--conf", type=float, default=0.20)
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    batch_dir = RAW_ROOT / args.batch_id
    frame_dir = batch_dir / "frames"
    output_dir = batch_dir / "prelabels" / "hf_human_fall_yolo11_mapped"
    label_dir = output_dir / "labels"
    meta_dir = output_dir / "meta"
    label_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    image_paths = sorted(path for path in frame_dir.glob("*") if path.suffix.lower() in IMAGE_EXTS)
    if not image_paths:
        raise SystemExit(f"No images found in {frame_dir}")

    model_path = Path(args.model)
    if not model_path.is_absolute():
        model_path = ROOT / model_path
    model_name = relative_to_root(model_path)
    model = YOLO(str(model_path))
    rows: list[dict[str, Any]] = []
    class_counts = {name: 0 for name in CLASS_NAMES.values()}
    empty_count = 0

    for image_path in image_paths:
        result = model.predict(str(image_path), conf=args.conf, imgsz=args.imgsz, verbose=False)[0]
        label_lines: list[str] = []
        boxes = getattr(result, "boxes", None)
        names = getattr(result, "names", {}) or {}
        detections = 0
        if boxes is not None:
            for box in boxes:
                src_cls = int(box.cls[0].item()) if box.cls is not None else -1
                src_label = str(names.get(src_cls, src_cls)).lower()
                target_cls = HF_TO_FALL_HINT_V2.get(src_label)
                if target_cls is None:
                    continue
                x_center, y_center, width, height = [float(value) for value in box.xywhn[0].tolist()]
                confidence = float(box.conf[0].item())
                label_lines.append(
                    f"{target_cls} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"
                )
                detections += 1
                class_counts[CLASS_NAMES[target_cls]] += 1
                rows.append(
                    {
                        "image": image_path.name,
                        "source_model": model_name,
                        "source_label": src_label,
                        "target_class_id": target_cls,
                        "target_label": CLASS_NAMES[target_cls],
                        "confidence": round(confidence, 6),
                        "x_center": round(x_center, 6),
                        "y_center": round(y_center, 6),
                        "width": round(width, 6),
                        "height": round(height, 6),
                        "needs_human_review": "true",
                    }
                )
        if detections == 0:
            empty_count += 1
        (label_dir / f"{image_path.stem}.txt").write_text("\n".join(label_lines) + ("\n" if label_lines else ""), encoding="utf-8")

    write_classes(output_dir / "classes.txt")
    write_csv(meta_dir / "prelabel_manifest.csv", rows)
    summary = {
        "batch_id": args.batch_id,
        "model": model_name,
        "image_count": len(image_paths),
        "empty_label_count": empty_count,
        "class_counts": class_counts,
        "label_dir": str(label_dir.relative_to(ROOT)).replace("\\", "/"),
        "warning": "Draft labels only. Human must correct boxes and classes before training.",
    }
    (meta_dir / "prelabel_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def relative_to_root(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def write_classes(path: Path) -> None:
    path.write_text("\n".join(CLASS_NAMES[index] for index in sorted(CLASS_NAMES)) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
