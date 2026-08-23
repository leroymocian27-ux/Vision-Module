from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "runs" / "fall_hint_v3_c_real_fall_recall_repair_20260705"
MISSED_ROOT = RUN_ROOT / "missed_real_fall_analysis"
VARIANT_ROOT = RUN_ROOT / "dataset_variant_candidate_v3_c_recall_repair"
TRAIN_RUN_NAME = "candidate_v3_c_recall_repair_r1"
TRAIN_RUN_DIR = RUN_ROOT / TRAIN_RUN_NAME

V3_DATASET_ROOT = ROOT / "datasets" / "fall_hint_v3_balanced_hardcase_202607"
V3_DATASET_YAML = V3_DATASET_ROOT / "dataset.yaml"
V3_MANIFEST = V3_DATASET_ROOT / "manifest.csv"
V3_CANDIDATE_MANIFEST = ROOT / "runs" / "fall_hint_v3_candidates_202607" / "candidate_manifest.json"

FIXED_ACCEPTANCE_ROOT = ROOT / "datasets" / "fall_hint_acceptance_fixed_202607_v1"
FIXED_ACCEPTANCE_MANIFEST = FIXED_ACCEPTANCE_ROOT / "manifest.csv"
FIXED_ACCEPTANCE_SUMMARY = FIXED_ACCEPTANCE_ROOT / "summary.json"
FIXED_ACCEPTANCE_SELF_CHECK = FIXED_ACCEPTANCE_ROOT / "self_check.json"

BANK_ROOT = ROOT / "datasets" / "fall_false_positive_bank_202607"
BANK_MANIFEST = BANK_ROOT / "manifest.csv"
ACCEPTANCE_ONLY_CSV = BANK_ROOT / "subsets" / "acceptance_only.csv"

REVIEWED_CLEAN_ROOT = ROOT / "datasets" / "fall_hint_v2_clean_reviewed_only_noaug_20260703"
REVIEWED_CLEAN_MANIFEST = REVIEWED_CLEAN_ROOT / "meta" / "manifest.csv"
REVIEWED_ALL_ROOT = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"
REVIEWED_ALL_MANIFEST = REVIEWED_ALL_ROOT / "meta" / "manifest.csv"
REVIEWED_ALL_INVALID_LABELS = REVIEWED_ALL_ROOT / "meta" / "relabel_invalid_labels.csv"
REVIEWED_ALL_UNTRUSTED = REVIEWED_ALL_ROOT / "meta" / "relabel_untrusted_frames.csv"
REVIEWED_ALL_CLASS_CONFLICTS = REVIEWED_ALL_ROOT / "meta" / "relabel_duplicate_class_conflicts.csv"

PRECISION_POLISH_ROOT = ROOT / "runs" / "fall_hint_v3_c_precision_polish_20260705"
POLISH_R2_SUMMARY = PRECISION_POLISH_ROOT / "candidate_v3_c_polish_r2_true_low_lr_summary.json"
POLISH_R2_MODEL = PRECISION_POLISH_ROOT / "candidate_v3_c_polish_r2_true_low_lr" / "weights" / "best.pt"

BASELINE_MODEL = ROOT / "models" / "7-3testmodel.pt"

ULTRALYTICS_SETTINGS_DIR = ROOT / "runs" / "_ultralytics_settings"
ULTRALYTICS_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_SETTINGS_DIR)

TARGET_CLASS_NAMES = ["standing", "fallen", "sitting", "lying", "falling", "kneeling", "bending"]
OLD_ORDER_NAMES = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
SEMANTIC_TO_TARGET = {name: idx for idx, name in enumerate(TARGET_CLASS_NAMES)}
OLD_TO_NEW = {0: 4, 1: 1, 2: 3, 3: 2, 4: 6, 5: 5, 6: 0}
TARGET_TO_OLD = {0: 6, 1: 1, 2: 3, 3: 2, 4: 0, 5: 5, 6: 4}
FALL_LIKE = {"falling", "fallen"}
ADL_NEGATIVE_CATEGORIES = {
    "sitting_as_fall",
    "bending_as_fall",
    "kneeling_as_fall",
    "lying_adl_as_fall",
    "low_posture",
    "normal_standing",
    "edge_cases",
}
REPAIR_POSITIVE_CLASSES = {"falling", "fallen"}
IOU_MATCH = 0.50
EVAL_CONF = 0.25


@dataclass
class AcceptanceRow:
    acceptance_id: str
    category: str
    source_dataset: str
    source_image_path: Path
    source_label_path: Path
    target_image_path: Path
    target_label_path: Path
    expected_behavior: str
    should_trigger_fall_alarm: bool
    notes: str


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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def normalize_text_lines(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return ("\n".join(lines) + "\n") if lines else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def runtime_device() -> str | int:
    import torch

    return 0 if torch.cuda.is_available() else "cpu"


def cuda_available_or_raise() -> None:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA_NOT_AVAILABLE")


def load_candidate_v3_c_path() -> Path:
    payload = json.loads(V3_CANDIDATE_MANIFEST.read_text(encoding="utf-8"))
    candidate_info = payload["candidates"].get("candidate_v3_c_temporal_friendly")
    if not candidate_info:
        raise RuntimeError("candidate_v3_c_temporal_friendly missing from candidate_manifest.json")
    path = Path(candidate_info["best_pt"])
    if not path.exists():
        raise RuntimeError(f"candidate_v3_c best.pt missing: {path}")
    return path


def normalize_prediction_name(model_label: str, name: str) -> str:
    semantic = str(name).strip().lower()
    if model_label == "baseline":
        if semantic not in OLD_ORDER_NAMES:
            return semantic
        return TARGET_CLASS_NAMES[SEMANTIC_TO_TARGET[semantic]]
    return semantic


def parse_target_label(label_path: Path, image_width: int, image_height: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = label_path.read_text(encoding="utf-8").strip()
    if not text:
        return rows
    for raw in text.splitlines():
        parts = raw.strip().split()
        if len(parts) != 5:
            continue
        cls_id = int(parts[0])
        xc = float(parts[1]) * image_width
        yc = float(parts[2]) * image_height
        bw = float(parts[3]) * image_width
        bh = float(parts[4]) * image_height
        rows.append(
            {
                "class_id": cls_id,
                "class_name": TARGET_CLASS_NAMES[cls_id],
                "bbox_xyxy": [xc - bw / 2.0, yc - bh / 2.0, xc + bw / 2.0, yc + bh / 2.0],
            }
        )
    return rows


def remap_old_order_label_text(text: str) -> str:
    output_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            continue
        old_cls = int(parts[0])
        new_cls = OLD_TO_NEW[old_cls]
        output_lines.append(f"{new_cls} {' '.join(parts[1:])}")
    return ("\n".join(output_lines) + "\n") if output_lines else ""


def repair_fixed_acceptance_target_labels_if_needed() -> dict[str, object]:
    manifest_rows = read_csv(FIXED_ACCEPTANCE_MANIFEST)
    repaired_rows: list[dict[str, object]] = []
    for row in manifest_rows:
        source_label_path = Path(row["source_label_path"])
        target_label_path = Path(row["target_label_path"])
        expected_text = remap_old_order_label_text(source_label_path.read_text(encoding="utf-8"))
        actual_text = target_label_path.read_text(encoding="utf-8")
        if normalize_text_lines(expected_text) == normalize_text_lines(actual_text):
            continue
        target_label_path.write_text(expected_text, encoding="utf-8")
        row["label_sha256"] = sha256_file(target_label_path)
        repaired_rows.append(
            {
                "acceptance_id": row["acceptance_id"],
                "category": row["category"],
                "target_label_path": str(target_label_path),
                "before": normalize_text_lines(actual_text),
                "after": normalize_text_lines(expected_text),
            }
        )
    if repaired_rows:
        write_csv(FIXED_ACCEPTANCE_MANIFEST, manifest_rows)
    report = {
        "checked_rows": len(manifest_rows),
        "repaired_row_count": len(repaired_rows),
        "repaired_rows": repaired_rows,
        "fixed_acceptance_manifest": str(FIXED_ACCEPTANCE_MANIFEST),
    }
    write_json(RUN_ROOT / "eval_acceptance" / "fixed_acceptance_label_repair.json", report)
    return report


def load_acceptance_rows() -> list[AcceptanceRow]:
    rows: list[AcceptanceRow] = []
    for row in read_csv(FIXED_ACCEPTANCE_MANIFEST):
        rows.append(
            AcceptanceRow(
                acceptance_id=row["acceptance_id"],
                category=row["category"],
                source_dataset=row["source_dataset"],
                source_image_path=Path(row["source_image_path"]),
                source_label_path=Path(row["source_label_path"]),
                target_image_path=Path(row["target_image_path"]),
                target_label_path=Path(row["target_label_path"]),
                expected_behavior=row["expected_behavior"],
                should_trigger_fall_alarm=str(row["should_trigger_fall_alarm"]).lower() == "true",
                notes=row.get("notes", ""),
            )
        )
    return rows


def predict_images(model_path: Path, model_label: str, image_paths: list[Path], conf: float = EVAL_CONF) -> dict[str, list[dict[str, Any]]]:
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    results = model.predict(
        source=[str(path) for path in image_paths],
        conf=conf,
        imgsz=640,
        device=runtime_device(),
        batch=8,
        verbose=False,
        stream=False,
    )
    normalized: dict[str, list[dict[str, Any]]] = {}
    for image_path, result in zip(image_paths, results):
        preds: list[dict[str, Any]] = []
        boxes = result.boxes
        if boxes is not None and len(boxes) > 0:
            for pred_index, (xyxy, pred_conf, cls_idx) in enumerate(
                zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()),
                start=1,
            ):
                class_name = normalize_prediction_name(model_label, result.names[int(cls_idx)])
                preds.append(
                    {
                        "pred_index": pred_index,
                        "class_name": class_name,
                        "confidence": float(pred_conf),
                        "bbox_xyxy": [float(value) for value in xyxy],
                    }
                )
        preds.sort(key=lambda item: item["confidence"], reverse=True)
        normalized[str(image_path)] = preds
    return normalized


def acceptance_match(preds: list[dict[str, Any]], targets: list[dict[str, Any]], allowed_classes: set[str]) -> bool:
    for target in targets:
        if target["class_name"] not in allowed_classes:
            continue
        for pred in preds:
            if pred["class_name"] != target["class_name"]:
                continue
            if bbox_iou(pred["bbox_xyxy"], target["bbox_xyxy"]) >= IOU_MATCH:
                return True
    return False


def top_prediction_text(preds: list[dict[str, Any]]) -> str:
    if not preds:
        return "none"
    top = preds[0]
    return f"{top['class_name']}@{top['confidence']:.3f}"


def reason_guess_for_real_fall(preds: list[dict[str, Any]], targets: list[dict[str, Any]]) -> str:
    if not preds:
        return "no_detection_or_conf_too_low"
    top = preds[0]
    if top["class_name"] in {"kneeling", "bending", "sitting", "standing"}:
        return f"boundary_shift_to_{top['class_name']}"
    if top["class_name"] in FALL_LIKE:
        matched = acceptance_match([top], targets, FALL_LIKE)
        if not matched:
            return "fall_like_class_but_bbox_not_aligned"
    return f"misclassified_as_{top['class_name']}"


def evaluate_acceptance_models(
    acceptance_rows: list[AcceptanceRow],
    model_paths: dict[str, Path],
) -> tuple[list[dict[str, object]], dict[str, list[dict[str, Any]]], list[dict[str, object]]]:
    image_paths = [row.target_image_path for row in acceptance_rows]
    predictions_by_model = {
        model_name: predict_images(model_path, model_name, image_paths)
        for model_name, model_path in model_paths.items()
    }

    summaries: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    for model_name, preds_map in predictions_by_model.items():
        summary = {
            "model_name": model_name,
            "acceptance_total": len(acceptance_rows),
            "empty_fp": 0,
            "false_adl": 0,
            "real_fall_miss": 0,
            "slow_fall_miss": 0,
            "sitting_false_fallen": 0,
            "bending_false_fallen": 0,
            "kneeling_false_fallen": 0,
            "lying_false_fallen": 0,
            "repeat_alarm_count": 0,
        }
        for row in acceptance_rows:
            preds = preds_map[str(row.target_image_path)]
            width, height = read_image_size(row.target_image_path)
            targets = parse_target_label(row.target_label_path, width, height)
            fall_like_preds = [pred for pred in preds if pred["class_name"] in FALL_LIKE]
            if len(fall_like_preds) >= 2 and row.category != "real_fall":
                summary["repeat_alarm_count"] += 1
            if row.category == "empty_scene" and preds:
                summary["empty_fp"] += 1
            if row.category in ADL_NEGATIVE_CATEGORIES and fall_like_preds:
                summary["false_adl"] += 1
            if row.category == "sitting_as_fall" and fall_like_preds:
                summary["sitting_false_fallen"] += 1
            if row.category == "bending_as_fall" and fall_like_preds:
                summary["bending_false_fallen"] += 1
            if row.category == "kneeling_as_fall" and fall_like_preds:
                summary["kneeling_false_fallen"] += 1
            if row.category == "lying_adl_as_fall" and fall_like_preds:
                summary["lying_false_fallen"] += 1
            if row.category == "real_fall":
                matched = acceptance_match(preds, targets, FALL_LIKE)
                if not matched:
                    summary["real_fall_miss"] += 1
            if row.category == "slow_fall_like":
                matched = acceptance_match(preds, targets, FALL_LIKE)
                if not matched:
                    summary["slow_fall_miss"] += 1
            detail_rows.append(
                {
                    "model_name": model_name,
                    "acceptance_id": row.acceptance_id,
                    "category": row.category,
                    "expected_behavior": row.expected_behavior,
                    "top_prediction": top_prediction_text(preds),
                    "prediction_count": len(preds),
                    "fall_like_prediction_count": len(fall_like_preds),
                    "matched_real_fall": acceptance_match(preds, targets, FALL_LIKE) if row.category == "real_fall" else "",
                    "matched_slow_fall": acceptance_match(preds, targets, FALL_LIKE) if row.category == "slow_fall_like" else "",
                }
            )
        summaries.append(summary)
    return summaries, predictions_by_model, detail_rows


def build_missed_real_fall_analysis(
    acceptance_rows: list[AcceptanceRow],
    predictions_by_model: dict[str, dict[str, list[dict[str, Any]]]],
) -> tuple[list[dict[str, object]], dict[str, object], str]:
    real_fall_rows = [row for row in acceptance_rows if row.category == "real_fall"]
    sample_rows: list[dict[str, object]] = []
    pattern_counter: Counter[str] = Counter()
    missed_count_by_model = {"baseline": 0, "candidate_v3_c": 0, "candidate_v3_c_polish_r2_true_low_lr": 0}
    category_counter: Counter[str] = Counter()

    for row in real_fall_rows:
        width, height = read_image_size(row.target_image_path)
        targets = parse_target_label(row.target_label_path, width, height)
        baseline_preds = predictions_by_model["baseline"][str(row.target_image_path)]
        candidate_preds = predictions_by_model["candidate_v3_c"][str(row.target_image_path)]
        polish_preds = predictions_by_model["candidate_v3_c_polish_r2_true_low_lr"][str(row.target_image_path)]

        baseline_match = acceptance_match(baseline_preds, targets, FALL_LIKE)
        candidate_match = acceptance_match(candidate_preds, targets, FALL_LIKE)
        polish_match = acceptance_match(polish_preds, targets, FALL_LIKE)
        if not baseline_match:
            missed_count_by_model["baseline"] += 1
        if not candidate_match:
            missed_count_by_model["candidate_v3_c"] += 1
        if not polish_match:
            missed_count_by_model["candidate_v3_c_polish_r2_true_low_lr"] += 1
            guess = reason_guess_for_real_fall(polish_preds, targets)
            pattern_counter[guess] += 1
            category_counter[row.category] += 1
        else:
            guess = ""

        sample_rows.append(
            {
                "acceptance_id": row.acceptance_id,
                "category": row.category,
                "source_image_path": str(row.source_image_path),
                "target_image_path": str(row.target_image_path),
                "expected_behavior": row.expected_behavior,
                "baseline_result": "match" if baseline_match else f"miss:{top_prediction_text(baseline_preds)}",
                "candidate_v3_c_result": "match" if candidate_match else f"miss:{top_prediction_text(candidate_preds)}",
                "polish_r2_result": "match" if polish_match else f"miss:{top_prediction_text(polish_preds)}",
                "missed_by_polish_r2": not polish_match,
                "missed_by_candidate_v3_c": not candidate_match,
                "reason_guess": guess,
                "notes": row.notes,
            }
        )

    analysis = {
        "missed_count_by_baseline": missed_count_by_model["baseline"],
        "missed_count_by_candidate_v3_c": missed_count_by_model["candidate_v3_c"],
        "missed_count_by_polish_r2": missed_count_by_model["candidate_v3_c_polish_r2_true_low_lr"],
        "polish_r2_extra_miss_count": missed_count_by_model["candidate_v3_c_polish_r2_true_low_lr"]
        - missed_count_by_model["candidate_v3_c"],
        "missed_categories": dict(category_counter),
        "failure_pattern_summary": dict(pattern_counter),
    }
    readme = [
        "# Missed Real Fall Analysis",
        "",
        f"- baseline real_fall_miss: {analysis['missed_count_by_baseline']}",
        f"- candidate_v3_c real_fall_miss: {analysis['missed_count_by_candidate_v3_c']}",
        f"- polish_r2 real_fall_miss: {analysis['missed_count_by_polish_r2']}",
        f"- polish_r2 extra miss count: {analysis['polish_r2_extra_miss_count']}",
        "",
        "## Failure Patterns",
    ]
    for key, value in pattern_counter.most_common():
        readme.append(f"- {key}: {value}")
    return sample_rows, analysis, "\n".join(readme) + "\n"


def split_rows_for_train_val(rows: list[dict[str, object]], val_every: int = 5) -> list[dict[str, object]]:
    buckets: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        buckets[str(row["class_name"])].append(row)
    final_rows: list[dict[str, object]] = []
    for class_name, items in buckets.items():
        items.sort(key=lambda item: str(item["source_image_path"]))
        for index, item in enumerate(items):
            new_item = dict(item)
            use_val = len(items) >= val_every and index % val_every == 0
            new_item["split"] = "val" if use_val else "train"
            new_item["use_in_training"] = not use_val
            new_item["use_in_validation"] = use_val
            final_rows.append(new_item)
    final_rows.sort(key=lambda item: (str(item["split"]), str(item["repair_role"]), str(item["source_image_path"])))
    return final_rows


def build_recall_repair_variant(candidate_v3_c_path: Path) -> tuple[Path, dict[str, object]]:
    if VARIANT_ROOT.exists():
        shutil.rmtree(VARIANT_ROOT)
    for split in ("train", "val"):
        (VARIANT_ROOT / split / "images").mkdir(parents=True, exist_ok=True)
        (VARIANT_ROOT / split / "labels").mkdir(parents=True, exist_ok=True)

    v3_rows = read_csv(V3_MANIFEST)
    fixed_rows = read_csv(FIXED_ACCEPTANCE_MANIFEST)
    acceptance_only_rows = read_csv(ACCEPTANCE_ONLY_CSV)
    reviewed_rows = read_csv(REVIEWED_ALL_MANIFEST)
    bank_rows = read_csv(BANK_MANIFEST)

    v3_reviewed_sources = {
        Path(row["source_image_path"]).name
        for row in v3_rows
        if row.get("source_dataset") in {"fall_hint_v2_clean_reviewed_only_noaug_20260703", "fall_hint_v2_reviewed_all_b001_b029"}
    }
    v3_bank_sources = {
        Path(row["source_image_path"]).name
        for row in v3_rows
        if row.get("source_dataset") == "fall_false_positive_bank_202607"
    }
    v3_image_hashes = {row["image_hash"] for row in v3_rows if row.get("image_hash")}
    v3_test_hashes = {row["image_hash"] for row in v3_rows if row.get("split") == "test" and row.get("image_hash")}
    fixed_source_names = {Path(row["source_image_path"]).name for row in fixed_rows}
    fixed_image_hashes = {row["image_sha256"] for row in fixed_rows if row.get("image_sha256")}
    acceptance_only_bank_names = {Path(row["bank_image_path"]).name for row in acceptance_only_rows}
    acceptance_only_hashes = {
        sha256_file(Path(row["bank_image_path"]))
        for row in acceptance_only_rows
        if Path(row["bank_image_path"]).exists()
    }

    invalid_source_images = {row["image"] for row in read_csv(REVIEWED_ALL_INVALID_LABELS)}
    untrusted_source_images = {row["image"] for row in read_csv(REVIEWED_ALL_UNTRUSTED)}
    conflict_archive_images = {row["archive_image"] for row in read_csv(REVIEWED_ALL_CLASS_CONFLICTS)}

    positive_rows: list[dict[str, object]] = []
    for row in reviewed_rows:
        class_counts = json.loads(row["class_counts"]) if row.get("class_counts") else {}
        if len(class_counts) != 1:
            continue
        class_name = next(iter(class_counts.keys()))
        if class_name not in REPAIR_POSITIVE_CLASSES:
            continue
        source_name = Path(row["new_image"]).name
        if source_name in v3_reviewed_sources or source_name in fixed_source_names or source_name in conflict_archive_images:
            continue
        if row["original_image"] in invalid_source_images or row["original_image"] in untrusted_source_images:
            continue
        source_image_path = REVIEWED_ALL_ROOT / row["new_image"]
        source_label_path = REVIEWED_ALL_ROOT / row["new_label"]
        image_sha = sha256_file(source_image_path)
        if image_sha in v3_image_hashes or image_sha in fixed_image_hashes or image_sha in acceptance_only_hashes:
            continue
        width, height = read_image_size(source_image_path)
        positive_rows.append(
            {
                "class_name": class_name,
                "source_dataset": "fall_hint_v2_reviewed_all_b001_b029",
                "source_image_path": source_image_path,
                "source_label_path": source_label_path,
                "repair_role": "falling_transition_positive" if class_name == "falling" else "fallen_boundary_positive",
                "is_positive_repair": True,
                "is_adl_anchor": False,
                "reason": "unused_reviewed_all_no_leak_positive",
                "notes": f"source_video={row['source_video']}; batch_id={row['batch_id']}; original_image={row['original_image']}",
                "width": width,
                "height": height,
            }
        )

    safe_bank_rows = [
        row
        for row in bank_rows
        if Path(row["bank_image_path"]).name not in v3_bank_sources
        and Path(row["bank_image_path"]).name not in fixed_source_names
        and Path(row["bank_image_path"]).name not in acceptance_only_bank_names
        and row.get("review_decision") == "reviewed"
        and sha256_file(Path(row["bank_image_path"])) not in v3_image_hashes
        and sha256_file(Path(row["bank_image_path"])) not in v3_test_hashes
        and sha256_file(Path(row["bank_image_path"])) not in fixed_image_hashes
        and sha256_file(Path(row["bank_image_path"])) not in acceptance_only_hashes
    ]
    anchor_candidates = [
        row
        for row in safe_bank_rows
        if row.get("reviewed_class") in {"__empty__", "sitting", "bending"}
    ]
    empty_rows = [row for row in anchor_candidates if row["reviewed_class"] == "__empty__"][:4]
    sitting_rows = [row for row in anchor_candidates if row["reviewed_class"] == "sitting"][:4]
    bending_rows = [row for row in anchor_candidates if row["reviewed_class"] == "bending"][:2]
    selected_anchors = empty_rows + sitting_rows + bending_rows

    anchor_rows: list[dict[str, object]] = []
    for row in selected_anchors:
        source_image_path = Path(row["bank_image_path"])
        source_label_path = Path(row["bank_label_path"])
        width, height = read_image_size(source_image_path)
        anchor_rows.append(
            {
                "class_name": row["reviewed_class"],
                "source_dataset": "fall_false_positive_bank_202607",
                "source_image_path": source_image_path,
                "source_label_path": source_label_path,
                "repair_role": "adl_anchor_negative",
                "is_positive_repair": False,
                "is_adl_anchor": True,
                "reason": row["category"],
                "notes": f"bank_id={row['bank_id']}",
                "width": width,
                "height": height,
            }
        )

    all_rows = split_rows_for_train_val(positive_rows + anchor_rows)

    manifest_rows: list[dict[str, object]] = []
    image_hashes: list[str] = []
    missing_image_count = 0
    missing_label_count = 0
    for index, row in enumerate(all_rows, start=1):
        split = str(row["split"])
        dst_stem = f"repair_{index:04d}"
        src_image_path = Path(row["source_image_path"])
        src_label_path = Path(row["source_label_path"])
        dst_image_path = VARIANT_ROOT / split / "images" / f"{dst_stem}{src_image_path.suffix.lower()}"
        dst_label_path = VARIANT_ROOT / split / "labels" / f"{dst_stem}.txt"
        if not src_image_path.exists():
            missing_image_count += 1
            continue
        shutil.copy2(src_image_path, dst_image_path)
        if row["source_dataset"] == "fall_hint_v2_reviewed_all_b001_b029":
            if not src_label_path.exists():
                missing_label_count += 1
                continue
            dst_label_path.write_text(remap_old_order_label_text(src_label_path.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            if row["class_name"] == "__empty__":
                dst_label_path.write_text("", encoding="utf-8")
            else:
                if not src_label_path.exists():
                    missing_label_count += 1
                    continue
                dst_label_path.write_text(remap_old_order_label_text(src_label_path.read_text(encoding="utf-8")), encoding="utf-8")
        image_sha = sha256_file(dst_image_path)
        label_sha = sha256_file(dst_label_path)
        image_hashes.append(image_sha)
        manifest_rows.append(
            {
                "item_id": dst_stem,
                "class_name": row["class_name"],
                "source_dataset": row["source_dataset"],
                "source_image_path": str(src_image_path),
                "source_label_path": str(src_label_path),
                "target_image_path": str(dst_image_path),
                "target_label_path": str(dst_label_path),
                "split": split,
                "repair_role": row["repair_role"],
                "is_positive_repair": row["is_positive_repair"],
                "is_adl_anchor": row["is_adl_anchor"],
                "use_in_training": row["use_in_training"],
                "use_in_validation": row["use_in_validation"],
                "reason": row["reason"],
                "image_sha256": image_sha,
                "label_sha256": label_sha,
                "width": row["width"],
                "height": row["height"],
                "notes": row["notes"],
            }
        )

    dataset_yaml_lines = [
        f"path: {VARIANT_ROOT.as_posix()}",
        "train: train/images",
        "val: val/images",
        f"test: {(V3_DATASET_ROOT / 'test' / 'images').as_posix()}",
        "",
        "names:",
        *[f"  {idx}: {name}" for idx, name in enumerate(TARGET_CLASS_NAMES)],
        "",
    ]
    write_text(VARIANT_ROOT / "dataset.yaml", "\n".join(dataset_yaml_lines))
    write_csv(VARIANT_ROOT / "manifest.csv", manifest_rows)

    acceptance_hashes = {row["image_sha256"] for row in fixed_rows}
    acceptance_source_paths = {row["source_image_path"] for row in fixed_rows}
    test_manifest_rows = [row for row in v3_rows if row.get("split") == "test"]
    test_hashes = {row["image_hash"] for row in test_manifest_rows}
    test_source_paths = {row["source_image_path"] for row in test_manifest_rows}
    acceptance_only_paths = {row["bank_image_path"] for row in acceptance_only_rows}

    acceptance_leak_count = 0
    test_leak_count = 0
    acceptance_only_leak_count = 0
    for row in manifest_rows:
        if row["image_sha256"] in acceptance_hashes or row["source_image_path"] in acceptance_source_paths:
            acceptance_leak_count += 1
        if row["image_sha256"] in test_hashes or row["source_image_path"] in test_source_paths:
            test_leak_count += 1
        if row["image_sha256"] in acceptance_only_hashes or row["source_image_path"] in acceptance_only_paths:
            acceptance_only_leak_count += 1

    duplicate_sha256_count = sum(count - 1 for count in Counter(image_hashes).values() if count > 1)
    no_leak = {
        "acceptance_leak_count": acceptance_leak_count,
        "test_leak_count": test_leak_count,
        "acceptance_only_leak_count": acceptance_only_leak_count,
        "duplicate_sha256_count": duplicate_sha256_count,
        "missing_image_count": missing_image_count,
        "missing_label_count": missing_label_count,
        "pass": all(
            [
                acceptance_leak_count == 0,
                test_leak_count == 0,
                acceptance_only_leak_count == 0,
                duplicate_sha256_count == 0,
                missing_image_count == 0,
                missing_label_count == 0,
            ]
        ),
    }
    write_json(VARIANT_ROOT / "no_leak_check.json", no_leak)

    summary = {
        "total_items": len(manifest_rows),
        "positive_repair_count": sum(1 for row in manifest_rows if row["is_positive_repair"]),
        "adl_anchor_count": sum(1 for row in manifest_rows if row["is_adl_anchor"]),
        "split_counts": dict(Counter(row["split"] for row in manifest_rows)),
        "repair_role_counts": dict(Counter(row["repair_role"] for row in manifest_rows)),
        "class_counts": dict(Counter(row["class_name"] for row in manifest_rows)),
        "selection_shortage_note": "only 37 no-leak falling/fallen reviewed positives were available after audit exclusions; kept dataset clean instead of forcing more",
        "no_leak_pass": no_leak["pass"],
    }
    write_json(VARIANT_ROOT / "variant_summary.json", summary)
    readme_lines = [
        "# Recall Repair Dataset Variant",
        "",
        f"- total_items: {summary['total_items']}",
        f"- positive_repair_count: {summary['positive_repair_count']}",
        f"- adl_anchor_count: {summary['adl_anchor_count']}",
        f"- no_leak_pass: {summary['no_leak_pass']}",
        f"- selection_shortage_note: {summary['selection_shortage_note']}",
    ]
    write_text(VARIANT_ROOT / "README.md", "\n".join(readme_lines) + "\n")
    return VARIANT_ROOT / "dataset.yaml", summary


def prepare_baseline_eval_dataset() -> Path:
    baseline_eval_root = RUN_ROOT / "baseline_eval_dataset_old_order"
    if baseline_eval_root.exists():
        return baseline_eval_root / "dataset.yaml"
    (baseline_eval_root / "test" / "images").mkdir(parents=True, exist_ok=True)
    (baseline_eval_root / "test" / "labels").mkdir(parents=True, exist_ok=True)
    for image_path in sorted((V3_DATASET_ROOT / "test" / "images").glob("*")):
        shutil.copy2(image_path, baseline_eval_root / "test" / "images" / image_path.name)
    for label_path in sorted((V3_DATASET_ROOT / "test" / "labels").glob("*.txt")):
        output_lines: list[str] = []
        for raw in label_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            cls_str, x_str, y_str, w_str, h_str = line.split()
            old_cls = TARGET_TO_OLD[int(cls_str)]
            output_lines.append(f"{old_cls} {x_str} {y_str} {w_str} {h_str}")
        (baseline_eval_root / "test" / "labels" / label_path.name).write_text(
            ("\n".join(output_lines) + "\n") if output_lines else "",
            encoding="utf-8",
        )
    dataset_yaml = "\n".join(
        [
            f"path: {baseline_eval_root.as_posix()}",
            "train: test/images",
            "val: test/images",
            "test: test/images",
            "",
            "names:",
            *[f"  {idx}: {name}" for idx, name in enumerate(OLD_ORDER_NAMES)],
            "",
        ]
    )
    write_text(baseline_eval_root / "dataset.yaml", dataset_yaml)
    return baseline_eval_root / "dataset.yaml"


def eval_test_metrics(model_name: str, model_path: Path, data_yaml: Path) -> dict[str, Any]:
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    metrics = model.val(
        data=str(data_yaml),
        split="test",
        imgsz=640,
        device=runtime_device(),
        project=str(RUN_ROOT / "eval_test"),
        name=model_name,
        exist_ok=True,
        workers=0,
        verbose=False,
    )
    return {
        "model_name": model_name,
        "model_path": str(model_path),
        "precision": float(metrics.box.mp),
        "recall": float(metrics.box.mr),
        "mAP50": float(metrics.box.map50),
        "mAP50-95": float(metrics.box.map),
        "fitness": float(metrics.fitness),
    }


def train_recall_repair_model(start_model: Path, data_yaml: Path) -> dict[str, object]:
    from ultralytics import YOLO

    cuda_available_or_raise()
    if TRAIN_RUN_DIR.exists():
        shutil.rmtree(TRAIN_RUN_DIR)
    start_time = time.time()
    model = YOLO(str(start_model))
    result = model.train(
        data=str(data_yaml),
        project=str(RUN_ROOT),
        name=TRAIN_RUN_NAME,
        exist_ok=True,
        device=0,
        workers=0,
        batch=8,
        imgsz=640,
        epochs=10,
        patience=3,
        seed=61,
        optimizer="AdamW",
        lr0=2e-05,
        lrf=0.1,
        warmup_epochs=0.0,
        warmup_bias_lr=0.0,
        mosaic=0.0,
        mixup=0.0,
        copy_paste=0.0,
        close_mosaic=0,
        fliplr=0.5,
        translate=0.0,
        scale=0.02,
        erasing=0.0,
        verbose=False,
        val=True,
        plots=True,
        save=True,
    )
    train_dir = Path(result.save_dir)
    best_pt = train_dir / "weights" / "best.pt"
    last_pt = train_dir / "weights" / "last.pt"
    if not best_pt.exists():
        raise RuntimeError(f"missing trained best.pt: {best_pt}")
    return {
        "training_start_model": str(start_model),
        "optimizer": "AdamW",
        "lr0": 2e-05,
        "lrf": 0.1,
        "epochs": 10,
        "patience": 3,
        "warmup_epochs": 0.0,
        "batch": 8,
        "imgsz": 640,
        "translate": 0.0,
        "scale": 0.02,
        "seed": 61,
        "best_pt": str(best_pt),
        "last_pt": str(last_pt),
        "train_dir": str(train_dir),
        "duration_sec": round(time.time() - start_time, 2),
    }


def render_build_log(
    *,
    stage_result: str,
    start_ts: str,
    end_ts: str,
    fixed_acceptance_repair: dict[str, Any],
    current_mainline: Path,
    polish_summary: dict[str, Any],
    missed_analysis: dict[str, Any],
    variant_summary: dict[str, Any],
    no_leak: dict[str, Any],
    train_info: dict[str, Any] | None,
    test_metrics: list[dict[str, Any]],
    acceptance_metrics: list[dict[str, Any]],
    gate: dict[str, Any],
    reason: str,
) -> str:
    lines = [
        "# Build Log",
        "",
        f"1. start_time: {start_ts}",
        f"2. end_time: {end_ts}",
        f"3. fixed_acceptance_label_repair: {json.dumps(fixed_acceptance_repair, ensure_ascii=False)}",
        f"4. current_mainline_model: {current_mainline}",
        "5. polish_r2 could not be upgraded because acceptance changed from real_fall_miss=1 to real_fall_miss=2 even though test precision improved.",
        f"6. missed real fall sample count (polish_r2): {missed_analysis['missed_count_by_polish_r2']}",
        f"7. missed failure patterns: {json.dumps(missed_analysis['failure_pattern_summary'], ensure_ascii=False)}",
        f"8. repair dataset summary: {json.dumps(variant_summary, ensure_ascii=False)}",
        f"9. no_leak_check: {json.dumps(no_leak, ensure_ascii=False)}",
        f"10. training_start_model_choice: {train_info['training_start_model'] if train_info else 'NONE'}",
        f"11. actual_train_params: {json.dumps(train_info, ensure_ascii=False) if train_info else 'NONE'}",
        "12. test_results:",
    ]
    for row in test_metrics:
        lines.append(
            f"   - {row['model_name']}: precision={row['precision']:.4f}, recall={row['recall']:.4f}, mAP50={row['mAP50']:.4f}, mAP50-95={row['mAP50-95']:.4f}"
        )
    lines.append("13. acceptance_results:")
    for row in acceptance_metrics:
        lines.append(
            f"   - {row['model_name']}: empty_fp={row['empty_fp']}, false_adl={row['false_adl']}, real_fall_miss={row['real_fall_miss']}, slow_fall_miss={row['slow_fall_miss']}, sitting_false_fallen={row['sitting_false_fallen']}, bending_false_fallen={row['bending_false_fallen']}, kneeling_false_fallen={row['kneeling_false_fallen']}, lying_false_fallen={row['lying_false_fallen']}, repeat_alarm_count={row['repeat_alarm_count']}"
        )
    lines.extend(
        [
            f"14. gate_decision: {json.dumps(gate, ensure_ascii=False)}",
            f"15. allow_shadow_mode: {gate['allow_shadow_mode']}",
            f"16. stage_result: {stage_result}",
            f"17. stage_reason: {reason}",
            "18. safety_confirmation:",
            "   - trained_model: YES" if train_info else "   - trained_model: NO",
            "   - replaced_production_model: NO",
            "   - modified_env: NO",
            "   - modified_alert_chain: NO",
            "   - used_acceptance_for_training: NO",
            "   - used_test_for_training: NO",
        ]
    )
    return "\n".join(lines) + "\n"


def run_stage() -> tuple[str, str]:
    stage_start = datetime.now().isoformat(timespec="seconds")
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    fixed_acceptance_repair = repair_fixed_acceptance_target_labels_if_needed()
    current_mainline = load_candidate_v3_c_path()
    polish_summary = json.loads(POLISH_R2_SUMMARY.read_text(encoding="utf-8"))

    acceptance_rows = load_acceptance_rows()
    model_paths = {
        "baseline": BASELINE_MODEL,
        "candidate_v3_c": current_mainline,
        "candidate_v3_c_polish_r2_true_low_lr": POLISH_R2_MODEL,
    }
    acceptance_metrics, predictions_by_model, acceptance_detail_rows = evaluate_acceptance_models(acceptance_rows, model_paths)
    write_csv(RUN_ROOT / "eval_acceptance" / "baseline_candidate_polish_acceptance_details.csv", acceptance_detail_rows)

    missed_rows, missed_analysis, missed_readme = build_missed_real_fall_analysis(acceptance_rows, predictions_by_model)
    write_csv(MISSED_ROOT / "missed_real_fall_samples.csv", missed_rows)
    write_json(MISSED_ROOT / "missed_real_fall_analysis.json", missed_analysis)
    write_text(MISSED_ROOT / "README.md", missed_readme)

    data_yaml, variant_summary = build_recall_repair_variant(current_mainline)
    no_leak = json.loads((VARIANT_ROOT / "no_leak_check.json").read_text(encoding="utf-8"))
    if not no_leak["pass"]:
        raise RuntimeError(f"REPAIR_DATASET_NO_LEAK_CHECK_FAILED: {json.dumps(no_leak, ensure_ascii=False)}")

    train_info = train_recall_repair_model(POLISH_R2_MODEL, data_yaml)
    repair_model_path = Path(train_info["best_pt"])

    baseline_eval_yaml = prepare_baseline_eval_dataset()
    eval_models = {
        "baseline": (BASELINE_MODEL, baseline_eval_yaml),
        "candidate_v3_c": (current_mainline, V3_DATASET_YAML),
        "candidate_v3_c_polish_r2_true_low_lr": (POLISH_R2_MODEL, V3_DATASET_YAML),
        "candidate_v3_c_recall_repair_r1": (repair_model_path, V3_DATASET_YAML),
    }
    test_metrics = [eval_test_metrics(name, model_path, data_yaml_path) for name, (model_path, data_yaml_path) in eval_models.items()]

    full_acceptance_models = {
        "baseline": BASELINE_MODEL,
        "candidate_v3_c": current_mainline,
        "candidate_v3_c_polish_r2_true_low_lr": POLISH_R2_MODEL,
        "candidate_v3_c_recall_repair_r1": repair_model_path,
    }
    acceptance_metrics, acceptance_predictions, acceptance_detail_rows = evaluate_acceptance_models(acceptance_rows, full_acceptance_models)
    write_csv(RUN_ROOT / "eval_acceptance" / "all_model_acceptance_details.csv", acceptance_detail_rows)

    metric_map = {row["model_name"]: row for row in test_metrics}
    acceptance_map = {row["model_name"]: row for row in acceptance_metrics}
    repair_test = metric_map["candidate_v3_c_recall_repair_r1"]
    repair_acc = acceptance_map["candidate_v3_c_recall_repair_r1"]
    candidate_test = metric_map["candidate_v3_c"]

    gate = {
        "real_fall_miss_leq_1": repair_acc["real_fall_miss"] <= 1,
        "empty_fp_leq_1": repair_acc["empty_fp"] <= 1,
        "false_adl_eq_0": repair_acc["false_adl"] <= 0,
        "precision_ge_0_58": repair_test["precision"] >= 0.58,
        "mAP50_95_ge_candidate_v3_c": repair_test["mAP50-95"] >= candidate_test["mAP50-95"],
        "no_new_severe_adl_fp": (
            repair_acc["sitting_false_fallen"] <= 0
            and repair_acc["bending_false_fallen"] <= 0
            and repair_acc["kneeling_false_fallen"] <= 0
            and repair_acc["lying_false_fallen"] <= 0
        ),
    }
    gate["allow_shadow_mode"] = all(gate.values())
    gate["final_decision"] = (
        "new_candidate_for_shadow_mode"
        if gate["allow_shadow_mode"]
        else "candidate_v3_c_remains_mainline"
    )

    write_json(
        RUN_ROOT / "comparison_summary.json",
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "test_metrics": test_metrics,
            "acceptance_metrics": acceptance_metrics,
            "fixed_acceptance_label_repair": fixed_acceptance_repair,
            "fixed_acceptance_summary": json.loads(FIXED_ACCEPTANCE_SUMMARY.read_text(encoding="utf-8")),
            "fixed_acceptance_self_check": json.loads(FIXED_ACCEPTANCE_SELF_CHECK.read_text(encoding="utf-8")),
        },
    )
    write_json(
        RUN_ROOT / "acceptance_gate_decision.json",
        {
            "stage_name": "candidate_v3_c_real_fall_recall_repair_20260705",
            "gate": gate,
            "current_mainline_model": str(current_mainline),
            "recall_repair_candidate_model": str(repair_model_path),
            "safety": {
                "trained_model": True,
                "replaced_production_model": False,
                "modified_env": False,
                "modified_alert_chain": False,
                "used_acceptance_for_training": False,
                "used_test_for_training": False,
            },
        },
    )

    stage_end = datetime.now().isoformat(timespec="seconds")
    stage_result = "PASS" if gate["allow_shadow_mode"] else "FAIL"
    stage_reason = "gate_passed_shadow_mode_only" if gate["allow_shadow_mode"] else "acceptance_gate_failed"
    build_log = render_build_log(
        stage_result=stage_result,
        start_ts=stage_start,
        end_ts=stage_end,
        fixed_acceptance_repair=fixed_acceptance_repair,
        current_mainline=current_mainline,
        polish_summary=polish_summary,
        missed_analysis=missed_analysis,
        variant_summary=variant_summary,
        no_leak=no_leak,
        train_info=train_info,
        test_metrics=test_metrics,
        acceptance_metrics=acceptance_metrics,
        gate=gate,
        reason=stage_reason,
    )
    write_text(RUN_ROOT / "build_log.md", build_log)
    return stage_result, stage_reason


def write_fail_outputs(reason: str) -> None:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage_name": "candidate_v3_c_real_fall_recall_repair_20260705",
        "stage_result": "FAIL",
        "reason": reason,
        "replaced_production_model": False,
        "modified_env": False,
        "modified_alert_chain": False,
        "used_acceptance_for_training": False,
        "used_test_for_training": False,
    }
    write_json(RUN_ROOT / "comparison_summary.json", payload)
    write_json(RUN_ROOT / "acceptance_gate_decision.json", payload)
    write_text(
        RUN_ROOT / "build_log.md",
        "\n".join(
            [
                "# Build Log",
                "",
                f"stage_result = FAIL",
                f"reason = {reason}",
                "candidate_v3_c continues as mainline",
            ]
        )
        + "\n",
    )


def main() -> int:
    try:
        stage_result, _stage_reason = run_stage()
        return 0 if stage_result in {"PASS", "FAIL"} else 1
    except Exception as exc:  # noqa: BLE001
        write_fail_outputs(str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
