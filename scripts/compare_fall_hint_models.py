from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEWED = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"
DEFAULT_OUTPUT = ROOT / "runs" / "fall_hint_v2_model_compare_20260703"

CLASSES = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
FALL_CLASSES = {"falling", "fallen"}
ADL_FALL_CONFUSION_CLASSES = {"sitting", "kneeling", "lying"}
POSE_HARD_CLASSES = {"kneeling", "lying"}


MODELS = {
    "runtime_current": ROOT / "models" / "yolo_fall_hint_v2_plus_b012_best.pt",
    "stage1": ROOT
    / "runs"
    / "fall_hint_v2_reviewed_only"
    / "stage1_hfbase_reviewed_only_b001_b029_20260703"
    / "weights"
    / "best.pt",
    "stage2": ROOT
    / "runs"
    / "fall_hint_v2_reviewed_only"
    / "stage2_from_stage1_reviewed_only_b001_b029_20260703"
    / "weights"
    / "best.pt",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Fall Hint models on the reviewed archive.")
    parser.add_argument("--reviewed", type=Path, default=DEFAULT_REVIEWED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--chunk-size", type=int, default=128)
    parser.add_argument("--max-images", type=int, default=0)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_label(path: Path) -> list[dict[str, Any]]:
    boxes = []
    if not path.exists():
        return boxes
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        try:
            cls = int(float(parts[0]))
            x, y, w, h = [float(value) for value in parts[1:]]
        except ValueError:
            continue
        if 0 <= cls < len(CLASSES) and 0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1:
            boxes.append({"class_id": cls, "class_name": CLASSES[cls], "box": (x, y, w, h)})
    return boxes


def xywh_to_xyxy(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x, y, w, h = box
    return x - w / 2, y - h / 2, x + w / 2, y + h / 2


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = xywh_to_xyxy(a)
    bx1, by1, bx2, by2 = xywh_to_xyxy(b)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def load_conflict_sets(reviewed: Path) -> tuple[set[str], set[str]]:
    conflict_images = {row.get("archive_image", "") for row in read_csv(reviewed / "meta" / "relabel_duplicate_class_conflicts.csv")}
    invalid_images = {row.get("archive_image", "") for row in read_csv(reviewed / "meta" / "relabel_invalid_labels.csv")}
    return {value for value in conflict_images if value}, {value for value in invalid_images if value}


def top_prediction(result: Any, gt_boxes: list[dict[str, Any]]) -> dict[str, Any]:
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return {
            "top_class_id": -1,
            "top_class": "none",
            "top_conf": 0.0,
            "top_iou": 0.0,
            "top_match_gt": "none",
            "pred_classes": "",
        }
    cls_ids = [int(value) for value in boxes.cls.detach().cpu().tolist()]
    confs = [float(value) for value in boxes.conf.detach().cpu().tolist()]
    xywhn = [tuple(float(v) for v in row) for row in boxes.xywhn.detach().cpu().tolist()]
    best_index = max(range(len(confs)), key=lambda idx: confs[idx])
    best_box = xywhn[best_index]
    best_iou = 0.0
    best_gt = "none"
    for gt in gt_boxes:
        score = iou(best_box, gt["box"])
        if score > best_iou:
            best_iou = score
            best_gt = gt["class_name"]
    return {
        "top_class_id": cls_ids[best_index],
        "top_class": CLASSES[cls_ids[best_index]] if 0 <= cls_ids[best_index] < len(CLASSES) else str(cls_ids[best_index]),
        "top_conf": confs[best_index],
        "top_iou": best_iou,
        "top_match_gt": best_gt,
        "pred_classes": " ".join(CLASSES[cls] if 0 <= cls < len(CLASSES) else str(cls) for cls in cls_ids),
    }


def run_predictions(image_paths: list[Path], args: argparse.Namespace) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for name, model_path in MODELS.items():
        if not model_path.exists():
            raise SystemExit(f"missing model {name}: {model_path}")
        print(f"[predict] {name}: {model_path}")
        model = YOLO(str(model_path))
        rows = []
        for start in range(0, len(image_paths), args.chunk_size):
            chunk = image_paths[start : start + args.chunk_size]
            for result in model.predict(
                source=[str(path) for path in chunk],
                imgsz=args.imgsz,
                conf=args.conf,
                device=args.device,
                batch=args.batch,
                verbose=False,
                stream=True,
            ):
                rows.append(result)
        output[name] = rows
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
    return output


def make_contact_sheet(output: Path, rows: list[dict[str, Any]], reviewed: Path, name: str, limit: int = 60) -> str:
    if not rows:
        return ""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return ""
    output.mkdir(parents=True, exist_ok=True)
    thumbs = []
    for row in rows[:limit]:
        image_path = reviewed / row["archive_image"]
        if not image_path.exists():
            continue
        image = Image.open(image_path).convert("RGB")
        image.thumbnail((240, 160))
        canvas = Image.new("RGB", (260, 225), "white")
        canvas.paste(image, ((260 - image.width) // 2, 0))
        draw = ImageDraw.Draw(canvas)
        lines = [
            row["archive_image"],
            f"GT: {row['gt_classes']}",
            f"Cur: {row['runtime_current_top_class']} {float(row['runtime_current_top_conf']):.2f}",
            f"S1: {row['stage1_top_class']} {float(row['stage1_top_conf']):.2f}",
            f"S2: {row['stage2_top_class']} {float(row['stage2_top_conf']):.2f}",
        ]
        y = 164
        for line in lines:
            draw.text((5, y), line[:42], fill=(0, 0, 0))
            y += 12
        thumbs.append(canvas)
    if not thumbs:
        return ""
    cols = 4
    rows_count = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 260, rows_count * 225), "white")
    for idx, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((idx % cols) * 260, (idx // cols) * 225))
    path = output / f"{name}.jpg"
    sheet.save(path, quality=92)
    return str(path)


def main() -> int:
    args = parse_args()
    reviewed = args.reviewed.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    manifest = read_csv(reviewed / "meta" / "manifest.csv")
    if args.max_images > 0:
        manifest = manifest[: args.max_images]
    conflict_images, invalid_images = load_conflict_sets(reviewed)
    image_paths = [reviewed / row["new_image"] for row in manifest]
    gt_by_image = {Path(row["new_image"]).name: read_label(reviewed / row["new_label"]) for row in manifest}
    predictions = run_predictions(image_paths, args)

    rows: list[dict[str, Any]] = []
    issue_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    confusion: dict[str, Counter[str]] = {model_name: Counter() for model_name in MODELS}

    for idx, row in enumerate(manifest):
        archive_image = Path(row["new_image"]).name
        gt_boxes = gt_by_image[archive_image]
        gt_classes = [box["class_name"] for box in gt_boxes]
        gt_set = set(gt_classes)
        result_row: dict[str, Any] = {
            "index": row.get("index", ""),
            "archive_image": row["new_image"],
            "archive_label": row["new_label"],
            "batch_id": row.get("batch_id", ""),
            "original_image": row.get("original_image", ""),
            "scene": row.get("scene", ""),
            "source_video": row.get("source_video", ""),
            "gt_classes": " ".join(gt_classes) if gt_classes else "empty",
            "known_duplicate_class_conflict": archive_image in conflict_images,
            "known_invalid_label": archive_image in invalid_images,
        }
        top_classes = []
        for model_name, result_list in predictions.items():
            pred = top_prediction(result_list[idx], gt_boxes)
            top_classes.append(pred["top_class"])
            for key, value in pred.items():
                result_row[f"{model_name}_{key}"] = value
            primary_gt = gt_classes[0] if gt_classes else "empty"
            confusion[model_name][f"{primary_gt}->{pred['top_class']}"] += 1

        if len(set(top_classes)) > 1:
            issue_rows["model_disagreement"].append(result_row)

        if (
            result_row["runtime_current_top_class"] == "fallen"
            and gt_set.intersection(ADL_FALL_CONFUSION_CLASSES)
            and "fallen" not in gt_set
        ):
            issue_rows["runtime_current_false_fallen_adl"].append(result_row)

        for model_name in ["stage1", "stage2"]:
            if gt_set.intersection(FALL_CLASSES) and result_row[f"{model_name}_top_class"] not in FALL_CLASSES:
                issue_rows[f"{model_name}_missed_fall"].append(result_row)
            if gt_set.intersection(POSE_HARD_CLASSES) and result_row[f"{model_name}_top_class"] not in gt_set:
                issue_rows[f"{model_name}_poor_kneeling_lying"].append(result_row)

        if not gt_classes:
            for model_name in MODELS:
                if result_row[f"{model_name}_top_class"] != "none":
                    issue_rows[f"{model_name}_false_positive_empty"].append(result_row)

        rows.append(result_row)

    write_csv(out / "all_predictions.csv", rows)
    for name, selected in issue_rows.items():
        selected_sorted = sorted(
            selected,
            key=lambda item: max(
                float(item.get("runtime_current_top_conf", 0.0)),
                float(item.get("stage1_top_conf", 0.0)),
                float(item.get("stage2_top_conf", 0.0)),
            ),
            reverse=True,
        )
        write_csv(out / f"{name}.csv", selected_sorted)
        make_contact_sheet(out / "contact_sheets", selected_sorted, reviewed, name)

    summary = {
        "reviewed_dataset": str(reviewed),
        "output": str(out),
        "image_count": len(rows),
        "known_duplicate_class_conflict_images": len(conflict_images),
        "known_invalid_label_images": len(invalid_images),
        "issue_counts": {name: len(selected) for name, selected in sorted(issue_rows.items())},
        "model_top_class_counts": {
            model_name: Counter(row[f"{model_name}_top_class"] for row in rows) for model_name in MODELS
        },
        "confusion_top_class": {model_name: dict(counter.most_common()) for model_name, counter in confusion.items()},
        "models": {name: str(path) for name, path in MODELS.items()},
    }
    (out / "comparison_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
