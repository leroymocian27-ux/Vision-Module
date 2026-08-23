from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit YOLO person predictions against reviewed raw-batch labels.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--batch-dir", default=str(ROOT / "datasets" / "person_yolo_raw" / "batch_001"))
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.30)
    parser.add_argument("--device", default="0")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    batch_dir = Path(args.batch_dir)
    frames_dir = batch_dir / "frames"
    labels_dir = batch_dir / "human_review" / "labels"
    manifest = read_manifest(batch_dir / "meta" / "frame_manifest.csv")

    model = YOLO(args.model)
    rows: list[dict[str, object]] = []
    stats: dict[str, Counter[str]] = defaultdict(Counter)
    failures: list[dict[str, object]] = []

    for image_name in sorted(manifest):
        image_path = frames_dir / image_name
        label_path = labels_dir / f"{Path(image_name).stem}.txt"
        if not image_path.exists() or not label_path.exists():
            continue
        gt_boxes = read_yolo_boxes(label_path)
        result = model.predict(
            source=str(image_path),
            conf=args.conf,
            iou=0.7,
            imgsz=640,
            device=args.device,
            classes=[0],
            verbose=False,
        )[0]
        pred_boxes = []
        if result.boxes is not None and len(result.boxes) > 0:
            h, w = result.orig_shape
            for box in result.boxes:
                xyxy = box.xyxy[0].detach().cpu().numpy().astype(float)
                pred_boxes.append(
                    [
                        xyxy[0] / w,
                        xyxy[1] / h,
                        xyxy[2] / w,
                        xyxy[3] / h,
                        float(box.conf[0].detach().cpu().item()),
                    ]
                )

        matches, missed, false_positive = match_boxes(gt_boxes, pred_boxes, args.iou)
        group = manifest[image_name].get("group") or "unknown"
        stats[group]["images"] += 1
        stats[group]["gt_boxes"] += len(gt_boxes)
        stats[group]["pred_boxes"] += len(pred_boxes)
        stats[group]["matched"] += matches
        stats[group]["missed"] += missed
        stats[group]["false_positive"] += false_positive
        if len(gt_boxes) == 0:
            stats[group]["empty_images"] += 1
        if missed or false_positive:
            failures.append(
                {
                    "image": image_name,
                    "group": group,
                    "gt_boxes": len(gt_boxes),
                    "pred_boxes": len(pred_boxes),
                    "missed": missed,
                    "false_positive": false_positive,
                }
            )
        rows.append(
            {
                "image": image_name,
                "group": group,
                "gt_boxes": len(gt_boxes),
                "pred_boxes": len(pred_boxes),
                "matched": matches,
                "missed": missed,
                "false_positive": false_positive,
            }
        )

    total = Counter()
    for counter in stats.values():
        total.update(counter)
    summary = {
        "model": str(Path(args.model)),
        "batch_dir": str(batch_dir),
        "conf": args.conf,
        "match_iou": args.iou,
        "total": dict(total),
        "groups": {group: dict(counter) for group, counter in sorted(stats.items())},
        "failure_count": len(failures),
        "failures": failures[:50],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(out_path.with_suffix(".csv"), rows)
    if failures:
        write_failure_sheet(out_path.with_suffix(".jpg"), failures[:24], frames_dir, labels_dir, model, args.conf, args.device)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def read_manifest(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        return {row["image"]: row for row in csv.DictReader(fh)}


def read_yolo_boxes(path: Path) -> list[list[float]]:
    boxes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _, x, y, w, h = line.split()
        xc, yc, bw, bh = map(float, [x, y, w, h])
        boxes.append([xc - bw / 2, yc - bh / 2, xc + bw / 2, yc + bh / 2])
    return boxes


def match_boxes(gt_boxes: list[list[float]], pred_boxes: list[list[float]], iou_threshold: float) -> tuple[int, int, int]:
    used_pred: set[int] = set()
    matches = 0
    for gt in gt_boxes:
        best_iou = 0.0
        best_index = -1
        for index, pred in enumerate(pred_boxes):
            if index in used_pred:
                continue
            score = iou(gt, pred[:4])
            if score > best_iou:
                best_iou = score
                best_index = index
        if best_iou >= iou_threshold and best_index >= 0:
            matches += 1
            used_pred.add(best_index)
    missed = len(gt_boxes) - matches
    false_positive = len(pred_boxes) - len(used_pred)
    return matches, missed, false_positive


def iou(a: list[float], b: list[float]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_failure_sheet(
    path: Path,
    failures: list[dict[str, object]],
    frames_dir: Path,
    labels_dir: Path,
    model: YOLO,
    conf: float,
    device: str,
) -> None:
    thumbs = []
    for failure in failures:
        image_name = str(failure["image"])
        image = cv2.imread(str(frames_dir / image_name))
        if image is None:
            continue
        h, w = image.shape[:2]
        for box in read_yolo_boxes(labels_dir / f"{Path(image_name).stem}.txt"):
            draw_box(image, box, (0, 200, 0), "gt")
        result = model.predict(source=str(frames_dir / image_name), conf=conf, imgsz=640, device=device, classes=[0], verbose=False)[0]
        if result.boxes is not None:
            for box in result.boxes:
                xyxy = box.xyxy[0].detach().cpu().numpy().astype(float)
                draw_box(image, [xyxy[0] / w, xyxy[1] / h, xyxy[2] / w, xyxy[3] / h], (0, 0, 255), "pred")
        scale = min(260 / w, 170 / h)
        resized = cv2.resize(image, (int(w * scale), int(h * scale)))
        canvas = np.full((210, 280, 3), 245, dtype=np.uint8)
        canvas[: resized.shape[0], : resized.shape[1]] = resized
        label = f"{failure['group']} miss={failure['missed']} fp={failure['false_positive']}"
        cv2.putText(canvas, label, (6, 198), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 20, 20), 1, cv2.LINE_AA)
        thumbs.append(canvas)
    if not thumbs:
        return
    cols = 4
    pad = 8
    rows = (len(thumbs) + cols - 1) // cols
    sheet = np.full((rows * (210 + pad) + pad, cols * (280 + pad) + pad, 3), 230, dtype=np.uint8)
    for index, thumb in enumerate(thumbs):
        row, col = divmod(index, cols)
        y = pad + row * (210 + pad)
        x = pad + col * (280 + pad)
        sheet[y : y + 210, x : x + 280] = thumb
    cv2.imwrite(str(path), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 92])


def draw_box(image: np.ndarray, box: list[float], color: tuple[int, int, int], label: str) -> None:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = [int(round(value)) for value in [box[0] * w, box[1] * h, box[2] * w, box[3] * h]]
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    cv2.putText(image, label, (x1, max(12, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


if __name__ == "__main__":
    raise SystemExit(main())
