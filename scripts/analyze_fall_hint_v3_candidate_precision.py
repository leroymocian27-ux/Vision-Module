from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "runs" / "fall_hint_v3_c_precision_polish_20260705"
DATASET_ROOT = ROOT / "datasets" / "fall_hint_v3_balanced_hardcase_202607"
DATASET_YAML = DATASET_ROOT / "dataset.yaml"
MANIFEST_CSV = DATASET_ROOT / "manifest.csv"
ULTRALYTICS_SETTINGS_DIR = ROOT / "runs" / "_ultralytics_settings"
ULTRALYTICS_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_SETTINGS_DIR)

BASELINE_MODEL = ROOT / "models" / "7-3testmodel.pt"
CANDIDATE_MODEL = (
    ROOT
    / "runs"
    / "fall_hint_v3_candidates_202607"
    / "candidate_v3_c_temporal_friendly"
    / "weights"
    / "best.pt"
)

TARGET_CLASS_NAMES = ["standing", "fallen", "sitting", "lying", "falling", "kneeling", "bending"]
BASELINE_CLASS_NAMES = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
SEMANTIC_TO_TARGET = {name: idx for idx, name in enumerate(TARGET_CLASS_NAMES)}
IOU_MATCH = 0.50
ANALYSIS_CONF = 0.25
ANALYSIS_IOU = 0.70


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def runtime_device() -> str | int:
    import torch

    return 0 if torch.cuda.is_available() else "cpu"


def read_image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return image.size


def bbox_iou(box_a: list[float], box_b: list[float]) -> float:
    xa1, ya1, xa2, ya2 = box_a
    xb1, yb1, xb2, yb2 = box_b
    ix1 = max(xa1, xb1)
    iy1 = max(ya1, yb1)
    ix2 = min(xa2, xb2)
    iy2 = min(ya2, yb2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, xa2 - xa1) * max(0.0, ya2 - ya1)
    area_b = max(0.0, xb2 - xb1) * max(0.0, yb2 - yb1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def parse_label(label_path: Path, image_width: int, image_height: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not label_path.exists():
        return items
    text = label_path.read_text(encoding="utf-8").strip()
    if not text:
        return items
    for index, raw in enumerate(text.splitlines(), start=1):
        parts = raw.strip().split()
        if len(parts) != 5:
            continue
        cls_id = int(parts[0])
        xc = float(parts[1]) * image_width
        yc = float(parts[2]) * image_height
        bw = float(parts[3]) * image_width
        bh = float(parts[4]) * image_height
        items.append(
            {
                "gt_index": index,
                "class_id": cls_id,
                "class_name": TARGET_CLASS_NAMES[cls_id],
                "bbox_xyxy": [xc - bw / 2.0, yc - bh / 2.0, xc + bw / 2.0, yc + bh / 2.0],
            }
        )
    return items


def load_test_rows() -> list[dict[str, Any]]:
    manifest_rows = read_csv(MANIFEST_CSV)
    test_rows: list[dict[str, Any]] = []
    for row in manifest_rows:
        if row.get("split") != "test":
            continue
        image_path = Path(row["v3_image_path"])
        label_path = Path(row["v3_label_path"])
        width, height = read_image_size(image_path)
        gt_boxes = parse_label(label_path, width, height)
        test_rows.append(
            {
                "v3_id": row["v3_id"],
                "image_path": image_path,
                "label_path": label_path,
                "source_dataset": row.get("source_dataset", ""),
                "source_batch": row.get("source_batch", ""),
                "source_file": row.get("source_file", ""),
                "source_category": row.get("source_category", ""),
                "group_id": row.get("group_id", ""),
                "width": width,
                "height": height,
                "gt_boxes": gt_boxes,
                "gt_classes": ",".join(gt["class_name"] for gt in gt_boxes) if gt_boxes else "__empty__",
            }
        )
    return test_rows


def normalize_prediction_name(model_label: str, pred_name: str) -> str:
    name = str(pred_name).strip().lower()
    if model_label == "baseline":
        if name not in BASELINE_CLASS_NAMES:
            return name
        return TARGET_CLASS_NAMES[SEMANTIC_TO_TARGET[name]]
    return name


def predict_rows(model_path: Path, rows: list[dict[str, Any]], model_label: str) -> dict[str, list[dict[str, Any]]]:
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    results = model.predict(
        source=[str(row["image_path"]) for row in rows],
        conf=ANALYSIS_CONF,
        iou=ANALYSIS_IOU,
        imgsz=640,
        device=runtime_device(),
        batch=8,
        verbose=False,
        stream=False,
    )
    normalized: dict[str, list[dict[str, Any]]] = {}
    for row, result in zip(rows, results):
        preds: list[dict[str, Any]] = []
        boxes = result.boxes
        if boxes is not None and len(boxes) > 0:
            xyxy_values = boxes.xyxy.tolist()
            conf_values = boxes.conf.tolist()
            cls_values = boxes.cls.tolist()
            for pred_index, (xyxy, conf_value, cls_value) in enumerate(
                zip(xyxy_values, conf_values, cls_values),
                start=1,
            ):
                class_id = int(cls_value)
                raw_name = result.names[class_id]
                class_name = normalize_prediction_name(model_label, raw_name)
                preds.append(
                    {
                        "pred_index": pred_index,
                        "class_name": class_name,
                        "confidence": float(conf_value),
                        "bbox_xyxy": [float(value) for value in xyxy],
                    }
                )
        preds.sort(key=lambda item: item["confidence"], reverse=True)
        normalized[row["v3_id"]] = preds
    return normalized


def classify_unmatched_prediction(
    pred: dict[str, Any],
    gt_boxes: list[dict[str, Any]],
    used_gt_indices: set[int],
) -> tuple[str, str, float]:
    best_iou = 0.0
    best_gt_class = "__none__"
    best_gt_index = -1
    best_same_class_iou = 0.0
    best_same_class_used = False
    for gt in gt_boxes:
        overlap = bbox_iou(pred["bbox_xyxy"], gt["bbox_xyxy"])
        if overlap > best_iou:
            best_iou = overlap
            best_gt_class = gt["class_name"]
            best_gt_index = int(gt["gt_index"])
        if gt["class_name"] == pred["class_name"] and overlap > best_same_class_iou:
            best_same_class_iou = overlap
            best_same_class_used = int(gt["gt_index"]) in used_gt_indices

    if best_iou < 0.10:
        return "background_fp", best_gt_class, best_iou
    if best_gt_class == pred["class_name"] and best_iou >= IOU_MATCH and best_gt_index in used_gt_indices:
        return "duplicate_fp", best_gt_class, best_iou
    if best_gt_class != pred["class_name"] and best_iou >= IOU_MATCH:
        return "wrong_class_fp", best_gt_class, best_iou
    if best_same_class_iou > 0 and best_same_class_iou < IOU_MATCH:
        return "localization_fp", pred["class_name"], best_same_class_iou
    if best_iou >= 0.10:
        return "near_object_fp", best_gt_class, best_iou
    return "background_fp", best_gt_class, best_iou


def evaluate_predictions(
    model_name: str,
    rows: list[dict[str, Any]],
    predictions_by_id: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    per_prediction_rows: list[dict[str, object]] = []
    bucket_counter: Counter[str] = Counter()
    pred_class_counter: Counter[str] = Counter()
    confusion_counter: Counter[str] = Counter()
    source_file_counter: Counter[str] = Counter()
    source_category_counter: Counter[str] = Counter()
    per_image_fp_counter: Counter[str] = Counter()
    metric_tp = 0
    metric_fp = 0
    metric_fn = 0
    total_gt = 0

    for row in rows:
        gt_boxes = row["gt_boxes"]
        preds = predictions_by_id[row["v3_id"]]
        total_gt += len(gt_boxes)
        matched_gt: set[int] = set()

        for pred in preds:
            pred_class_counter[pred["class_name"]] += 1
            best_match = None
            best_iou = 0.0
            for gt in gt_boxes:
                if gt["gt_index"] in matched_gt:
                    continue
                if gt["class_name"] != pred["class_name"]:
                    continue
                overlap = bbox_iou(pred["bbox_xyxy"], gt["bbox_xyxy"])
                if overlap >= IOU_MATCH and overlap > best_iou:
                    best_iou = overlap
                    best_match = gt

            if best_match is not None:
                matched_gt.add(int(best_match["gt_index"]))
                metric_tp += 1
                per_prediction_rows.append(
                    {
                        "model_name": model_name,
                        "v3_id": row["v3_id"],
                        "image_path": str(row["image_path"]),
                        "source_file": row["source_file"],
                        "source_category": row["source_category"],
                        "gt_classes": row["gt_classes"],
                        "pred_index": pred["pred_index"],
                        "pred_class": pred["class_name"],
                        "pred_conf": round(pred["confidence"], 6),
                        "match_type": "tp",
                        "matched_gt_class": best_match["class_name"],
                        "matched_gt_index": best_match["gt_index"],
                        "matched_iou": round(best_iou, 6),
                    }
                )
                continue

            metric_fp += 1
            fp_type, matched_gt_class, matched_iou = classify_unmatched_prediction(pred, gt_boxes, matched_gt)
            bucket_counter[fp_type] += 1
            per_image_fp_counter[row["v3_id"]] += 1
            confusion_counter[f"{pred['class_name']}->{matched_gt_class}"] += 1
            source_file_counter[row["source_file"]] += 1
            source_category_counter[row["source_category"]] += 1
            per_prediction_rows.append(
                {
                    "model_name": model_name,
                    "v3_id": row["v3_id"],
                    "image_path": str(row["image_path"]),
                    "source_file": row["source_file"],
                    "source_category": row["source_category"],
                    "gt_classes": row["gt_classes"],
                    "pred_index": pred["pred_index"],
                    "pred_class": pred["class_name"],
                    "pred_conf": round(pred["confidence"], 6),
                    "match_type": fp_type,
                    "matched_gt_class": matched_gt_class,
                    "matched_gt_index": "",
                    "matched_iou": round(matched_iou, 6),
                }
            )

        missed = [gt for gt in gt_boxes if gt["gt_index"] not in matched_gt]
        metric_fn += len(missed)
        for gt in missed:
            per_prediction_rows.append(
                {
                    "model_name": model_name,
                    "v3_id": row["v3_id"],
                    "image_path": str(row["image_path"]),
                    "source_file": row["source_file"],
                    "source_category": row["source_category"],
                    "gt_classes": row["gt_classes"],
                    "pred_index": "",
                    "pred_class": "",
                    "pred_conf": "",
                    "match_type": "fn",
                    "matched_gt_class": gt["class_name"],
                    "matched_gt_index": gt["gt_index"],
                    "matched_iou": 0.0,
                }
            )

    precision = metric_tp / (metric_tp + metric_fp) if (metric_tp + metric_fp) else 0.0
    recall = metric_tp / total_gt if total_gt else 0.0
    summary = {
        "model_name": model_name,
        "analysis_conf": ANALYSIS_CONF,
        "analysis_iou": ANALYSIS_IOU,
        "tp": metric_tp,
        "fp": metric_fp,
        "fn": metric_fn,
        "gt_boxes": total_gt,
        "precision_at_conf_0_25": precision,
        "recall_at_conf_0_25": recall,
        "fp_bucket_counts": dict(bucket_counter),
        "fp_predicted_class_counts": dict(pred_class_counter),
        "fp_confusion_counts": dict(confusion_counter.most_common(50)),
        "fp_source_file_counts": dict(source_file_counter.most_common(30)),
        "fp_source_category_counts": dict(source_category_counter.most_common(30)),
        "images_with_fp": sum(1 for value in per_image_fp_counter.values() if value > 0),
        "top_fp_images": dict(per_image_fp_counter.most_common(30)),
    }
    return per_prediction_rows, summary


def build_fp_image_summary(per_prediction_rows: list[dict[str, object]], rows_by_id: dict[str, dict[str, Any]]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for row in per_prediction_rows:
        if row["match_type"] in {"tp", "fn"}:
            continue
        key = str(row["v3_id"])
        bucket = grouped.setdefault(
            key,
            {
                "v3_id": key,
                "image_path": row["image_path"],
                "source_file": row["source_file"],
                "source_category": row["source_category"],
                "gt_classes": row["gt_classes"],
                "fp_count": 0,
                "fp_types": Counter(),
                "pred_classes": Counter(),
                "max_conf": 0.0,
            },
        )
        bucket["fp_count"] = int(bucket["fp_count"]) + 1
        bucket["fp_types"][str(row["match_type"])] += 1
        bucket["pred_classes"][str(row["pred_class"])] += 1
        bucket["max_conf"] = max(float(bucket["max_conf"]), float(row["pred_conf"]))

    output: list[dict[str, object]] = []
    for key, item in grouped.items():
        output.append(
            {
                "v3_id": key,
                "image_path": item["image_path"],
                "source_file": item["source_file"],
                "source_category": item["source_category"],
                "gt_classes": item["gt_classes"],
                "fp_count": item["fp_count"],
                "fp_types": ",".join(f"{name}:{count}" for name, count in item["fp_types"].most_common()),
                "pred_classes": ",".join(f"{name}:{count}" for name, count in item["pred_classes"].most_common()),
                "max_conf": round(float(item["max_conf"]), 6),
                "source_batch": rows_by_id[key]["source_batch"],
                "source_dataset": rows_by_id[key]["source_dataset"],
            }
        )
    output.sort(key=lambda row: (-int(row["fp_count"]), -float(row["max_conf"]), str(row["v3_id"])))
    return output


def build_source_delta(
    baseline_fp_images: list[dict[str, object]],
    candidate_fp_images: list[dict[str, object]],
) -> list[dict[str, object]]:
    source_map: defaultdict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"baseline": 0, "candidate": 0})
    for row in baseline_fp_images:
        source_map[(str(row["source_category"]), str(row["source_file"]))]["baseline"] += int(row["fp_count"])
    for row in candidate_fp_images:
        source_map[(str(row["source_category"]), str(row["source_file"]))]["candidate"] += int(row["fp_count"])

    rows: list[dict[str, object]] = []
    for (source_category, source_file), values in source_map.items():
        rows.append(
            {
                "source_category": source_category,
                "source_file": source_file,
                "baseline_fp": values["baseline"],
                "candidate_fp": values["candidate"],
                "delta_candidate_minus_baseline": values["candidate"] - values["baseline"],
            }
        )
    rows.sort(key=lambda row: (-int(row["delta_candidate_minus_baseline"]), -int(row["candidate_fp"]), str(row["source_file"])))
    return rows


def main() -> int:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    test_rows = load_test_rows()
    rows_by_id = {row["v3_id"]: row for row in test_rows}

    baseline_predictions = predict_rows(BASELINE_MODEL, test_rows, "baseline")
    candidate_predictions = predict_rows(CANDIDATE_MODEL, test_rows, "candidate_v3_c")

    baseline_detail_rows, baseline_summary = evaluate_predictions("baseline", test_rows, baseline_predictions)
    candidate_detail_rows, candidate_summary = evaluate_predictions("candidate_v3_c", test_rows, candidate_predictions)

    baseline_fp_images = build_fp_image_summary(baseline_detail_rows, rows_by_id)
    candidate_fp_images = build_fp_image_summary(candidate_detail_rows, rows_by_id)
    source_delta_rows = build_source_delta(baseline_fp_images, candidate_fp_images)

    write_csv(RUN_ROOT / "baseline_per_prediction.csv", baseline_detail_rows)
    write_csv(RUN_ROOT / "candidate_v3_c_per_prediction.csv", candidate_detail_rows)
    write_csv(RUN_ROOT / "baseline_fp_images.csv", baseline_fp_images)
    write_csv(RUN_ROOT / "candidate_v3_c_fp_images.csv", candidate_fp_images)
    write_csv(RUN_ROOT / "source_fp_delta.csv", source_delta_rows)

    comparison = {
        "created_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "dataset": str(DATASET_YAML),
        "test_image_count": len(test_rows),
        "baseline_model": str(BASELINE_MODEL),
        "candidate_model": str(CANDIDATE_MODEL),
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
        "precision_delta_candidate_minus_baseline": round(
            float(candidate_summary["precision_at_conf_0_25"]) - float(baseline_summary["precision_at_conf_0_25"]),
            6,
        ),
        "recall_delta_candidate_minus_baseline": round(
            float(candidate_summary["recall_at_conf_0_25"]) - float(baseline_summary["recall_at_conf_0_25"]),
            6,
        ),
        "top_candidate_source_deltas": source_delta_rows[:20],
    }
    write_json(RUN_ROOT / "analysis_summary.json", comparison)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
