from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "datasets" / "fall_clean_v1" / "reports"
RUNS_DIR = ROOT / "runs"

CANONICAL_DATASET_DIR = ROOT / "datasets" / "fall_clean_v1" / "yolo_dataset"
DATASET_COPY_DIR = RUNS_DIR / "fall_clean_v1_formal" / "dataset_copy_candidate_A2_stable"
MANIFEST_PATH = DATASET_COPY_DIR / "dataset_build_manifest.csv"
DATA_YAML_PATH = DATASET_COPY_DIR / "data.yaml"

A2_MODEL_PATH = RUNS_DIR / "fall_clean_v1_formal" / "hardneg_v1_formal_candidate_A2_stable_20260623" / "weights" / "best.pt"
BASELINE_MODEL_PATH = ROOT / "models" / "yolo_fall_detector_phase9_selected.pt"
BASELINE_SHA256_EXPECTED = "73D47684FD0B8558F0C6AE76A63C643ACC26A66F2ECD0667E00D059D0BA1DF49"

VAL_EVAL_PROJECT = RUNS_DIR / "fall_clean_v1_formal_eval_complete"
A2_VAL_EVAL_NAME = "candidate_A2_val_eval_complete_20260624"
BASELINE_VAL_EVAL_NAME = "baseline_val_eval_for_candidate_A2_complete_20260624"

FP_AUDIT_CSV = REPORTS_DIR / "candidate_A2_hard_negative_fp_audit_complete_20260623.csv"
FP_AUDIT_SUMMARY_MD = REPORTS_DIR / "candidate_A2_hard_negative_fp_audit_summary_20260623.md"
POS_RECALL_CSV = REPORTS_DIR / "candidate_A2_positive_recall_audit_complete_20260623.csv"
POS_RECALL_SUMMARY_MD = REPORTS_DIR / "candidate_A2_positive_recall_audit_summary_20260623.md"
THRESHOLD_CSV = REPORTS_DIR / "candidate_A2_threshold_sensitivity_20260623.csv"
THRESHOLD_SUMMARY_MD = REPORTS_DIR / "candidate_A2_threshold_sensitivity_summary_20260623.md"
COMPARE_MD = REPORTS_DIR / "candidate_A2_vs_baseline_eval_compare_complete_20260623.md"
MAIN_REPORT_MD = REPORTS_DIR / "candidate_A2_eval_gaps_completion_report_20260623.md"

PUBLIC_TEST_MANIFEST = ROOT / "datasets" / "fall_clean_v1" / "manifests" / "public_test_freeze_manifest.csv"
FROZEN_EVAL_ASSETS = ROOT / "datasets" / "fall_clean_v1" / "manifests" / "frozen_eval_assets.csv"
ENV_PATH = ROOT / ".env"
LOCKED_SPLIT_PATHS = [
    ROOT / "datasets" / "fall_clean_v1" / "manifests" / "train_manifest_locked.csv",
    ROOT / "datasets" / "fall_clean_v1" / "manifests" / "val_manifest_locked.csv",
    ROOT / "datasets" / "fall_clean_v1" / "manifests" / "train_val_split_lock.csv",
    ROOT / "datasets" / "fall_clean_v1" / "manifests" / "train_val_group_leakage_check.csv",
]

A2_CLASS_NAMES = {0: "fall", 1: "fallen", 2: "lying"}
BASELINE_SEMANTIC_CLASS_MAP = {1: "fall", 2: "fallen", 3: "lying"}
THRESHOLDS = [0.10, 0.20, 0.25, 0.30, 0.40, 0.50]
MATCH_IOU = 0.50
AUDIT_THRESHOLD = 0.25


@dataclass
class ManifestRow:
    sample_id: str
    split: str
    label_type: str
    positive_class: str
    hard_negative_taxonomy: str
    dataset_name: str
    source_type: str
    source_path: str
    dst_image_path: Path
    dst_label_path: Path
    image_width: int
    image_height: int
    source_group_id: str
    asset_id: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def read_manifest_rows(path: Path) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                ManifestRow(
                    sample_id=row["sample_id"],
                    split=row["split"],
                    label_type=row["label_type"],
                    positive_class=(row.get("positive_class") or "").strip(),
                    hard_negative_taxonomy=(row.get("hard_negative_taxonomy") or "").strip(),
                    dataset_name=row["dataset_name"],
                    source_type=row["source_type"],
                    source_path=row["source_path"],
                    dst_image_path=Path(row["dst_image_path"]),
                    dst_label_path=Path(row["dst_label_path"]),
                    image_width=int(row["image_width"]),
                    image_height=int(row["image_height"]),
                    source_group_id=(row.get("source_group_id") or "").strip(),
                    asset_id=(row.get("asset_id") or "").strip(),
                )
            )
    return rows


def parse_yolo_labels(label_path: Path, width: int, height: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = label_path.read_text(encoding="utf-8").strip()
    if not text:
        return rows
    for line in text.splitlines():
        class_id_str, x_str, y_str, w_str, h_str = line.split()
        class_id = int(class_id_str)
        xc = float(x_str) * width
        yc = float(y_str) * height
        bw = float(w_str) * width
        bh = float(h_str) * height
        x1 = xc - bw / 2.0
        y1 = yc - bh / 2.0
        x2 = xc + bw / 2.0
        y2 = yc + bh / 2.0
        rows.append(
            {
                "class_id": class_id,
                "class_name": A2_CLASS_NAMES.get(class_id, f"class_{class_id}"),
                "bbox_xyxy": [x1, y1, x2, y2],
            }
        )
    return rows


def bbox_iou(box_a: list[float], box_b: list[float]) -> float:
    xa1, ya1, xa2, ya2 = box_a
    xb1, yb1, xb2, yb2 = box_b
    inter_x1 = max(xa1, xb1)
    inter_y1 = max(ya1, yb1)
    inter_x2 = min(xa2, xb2)
    inter_y2 = min(ya2, yb2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(0.0, xa2 - xa1) * max(0.0, ya2 - ya1)
    area_b = max(0.0, xb2 - xb1) * max(0.0, yb2 - yb1)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def normalize_predictions(result: Any, semantic_map: dict[int, str] | None = None) -> list[dict[str, Any]]:
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []
    preds: list[dict[str, Any]] = []
    for xyxy, conf, cls_idx in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()):
        class_idx = int(cls_idx)
        class_name = result.names.get(class_idx, str(class_idx))
        semantic_name = semantic_map[class_idx] if semantic_map and class_idx in semantic_map else class_name
        preds.append(
            {
                "class_id": class_idx,
                "class_name": class_name,
                "semantic_class": semantic_name,
                "confidence": float(conf),
                "bbox_xyxy": [float(v) for v in xyxy],
            }
        )
    preds.sort(key=lambda item: item["confidence"], reverse=True)
    return preds


def run_predict(model_path: Path, image_paths: list[Path], semantic_map: dict[int, str] | None = None) -> dict[str, list[dict[str, Any]]]:
    model = YOLO(str(model_path))
    results = model.predict(
        source=[str(path) for path in image_paths],
        conf=0.001,
        imgsz=640,
        batch=8,
        device=0,
        verbose=False,
        save=False,
        stream=False,
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for image_path, result in zip(image_paths, results):
        out[str(image_path)] = normalize_predictions(result, semantic_map=semantic_map)
    return out


def run_val_metrics(model_path: Path) -> dict[str, Any]:
    model = YOLO(str(model_path))
    metrics = model.val(
        data=str(DATA_YAML_PATH),
        imgsz=640,
        batch=4,
        device=0,
        workers=0,
        plots=False,
        save_json=False,
        verbose=False,
    )
    per_class = {}
    ap_class_index = list(getattr(metrics.box, "ap_class_index", []))
    for idx, class_slot in enumerate(ap_class_index):
        p, r, map50, map95 = metrics.box.class_result(idx)
        per_class[int(class_slot)] = {
            "precision": float(p),
            "recall": float(r),
            "mAP50": float(map50),
            "mAP50-95": float(map95),
        }
    return {
        "results_dict": {key: float(value) for key, value in metrics.results_dict.items()},
        "per_class": per_class,
    }


def best_match_for_gt(
    preds: list[dict[str, Any]],
    gt: dict[str, Any],
    threshold: float,
    semantic_key: str = "semantic_class",
) -> dict[str, Any] | None:
    same_class = [
        pred
        for pred in preds
        if pred["confidence"] >= threshold and pred.get(semantic_key) == gt["class_name"]
    ]
    if not same_class:
        return None
    best = None
    best_iou = -1.0
    for pred in same_class:
        iou = bbox_iou(pred["bbox_xyxy"], gt["bbox_xyxy"])
        if iou > best_iou:
            best_iou = iou
            best = pred
    if best is None:
        return None
    return {**best, "iou": best_iou}


def explain_miss(preds: list[dict[str, Any]], gt: dict[str, Any], threshold: float) -> str:
    semantic_preds = [pred for pred in preds if pred.get("semantic_class") == gt["class_name"]]
    if not semantic_preds:
        return "no_prediction_for_gt_class"
    high_conf_same_class = [pred for pred in semantic_preds if pred["confidence"] >= threshold]
    if not high_conf_same_class:
        return "only_low_confidence_same_class_prediction"
    best_iou = max(bbox_iou(pred["bbox_xyxy"], gt["bbox_xyxy"]) for pred in high_conf_same_class)
    if best_iou < MATCH_IOU:
        return "same_class_prediction_but_low_iou"
    return "unmatched_for_other_reason"


def audit_positive_recall(rows: list[ManifestRow], predictions: dict[str, list[dict[str, Any]]], threshold: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit_rows: list[dict[str, Any]] = []
    class_totals = Counter()
    class_hits = Counter()
    missed_rows: list[dict[str, Any]] = []
    for row in rows:
        gts = parse_yolo_labels(row.dst_label_path, row.image_width, row.image_height)
        preds = predictions[str(row.dst_image_path)]
        for gt in gts:
            class_totals[gt["class_name"]] += 1
            match = best_match_for_gt(preds, gt, threshold)
            matched = bool(match and match["iou"] >= MATCH_IOU)
            if matched:
                class_hits[gt["class_name"]] += 1
            miss_reason = "" if matched else explain_miss(preds, gt, threshold)
            best_any = preds[0] if preds else None
            audit_row = {
                "image_path": str(row.dst_image_path),
                "gt_class": gt["class_name"],
                "matched": str(matched).lower(),
                "predicted_class": match["semantic_class"] if matched else (best_any["semantic_class"] if best_any else ""),
                "confidence": f"{(match['confidence'] if matched else (best_any['confidence'] if best_any else 0.0)):.6f}" if (matched or best_any) else "",
                "iou": f"{(match['iou'] if matched else 0.0):.6f}" if matched else "",
                "miss_reason": miss_reason,
                "note": f"threshold={threshold:.2f}; iou_match={MATCH_IOU:.2f}",
            }
            audit_rows.append(audit_row)
            if not matched:
                missed_rows.append(audit_row)
    summary = {
        "positive_total": int(sum(class_totals.values())),
        "class_totals": dict(class_totals),
        "class_hits": dict(class_hits),
        "class_recalls": {
            class_name: (class_hits[class_name] / class_totals[class_name] if class_totals[class_name] else 0.0)
            for class_name in ["fall", "fallen", "lying"]
        },
        "overall_positive_recall": (sum(class_hits.values()) / sum(class_totals.values()) if class_totals else 0.0),
        "missed_rows": missed_rows,
    }
    return audit_rows, summary


def audit_hard_negative_fp(rows: list[ManifestRow], predictions: dict[str, list[dict[str, Any]]], threshold: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit_rows: list[dict[str, Any]] = []
    image_fp_counts = Counter()
    taxonomy_fp_counts = Counter()
    no_person_fp = 0
    risky_taxonomy_fp = Counter()
    for row in rows:
        preds = [pred for pred in predictions[str(row.dst_image_path)] if pred["confidence"] >= threshold]
        if not preds:
            continue
        image_fp_counts[str(row.dst_image_path)] += 1
        taxonomy_fp_counts[row.hard_negative_taxonomy] += 1
        if row.hard_negative_taxonomy == "no_person":
            no_person_fp += 1
        if row.hard_negative_taxonomy in {"sit", "squat", "lie_down_non_fall"}:
            risky_taxonomy_fp[row.hard_negative_taxonomy] += 1
        for pred in preds:
            audit_rows.append(
                {
                    "image_path": str(row.dst_image_path),
                    "source_group": row.source_group_id,
                    "hard_negative_type": row.hard_negative_taxonomy,
                    "predicted_class": pred["semantic_class"],
                    "confidence": f"{pred['confidence']:.6f}",
                    "bbox_xyxy": ",".join(f"{value:.2f}" for value in pred["bbox_xyxy"]),
                    "model": str(A2_MODEL_PATH),
                    "note": f"threshold={threshold:.2f}; source_type={row.source_type}; asset_id={row.asset_id}",
                }
            )
    audit_rows.sort(key=lambda item: float(item["confidence"]), reverse=True)
    total_images = len(rows)
    fp_images = len(image_fp_counts)
    summary = {
        "hard_negative_total": total_images,
        "fp_image_count": fp_images,
        "fp_rate": (fp_images / total_images if total_images else 0.0),
        "fp_by_taxonomy": dict(taxonomy_fp_counts),
        "top_confidence_examples": audit_rows[:10],
        "has_no_person_fp": no_person_fp > 0,
        "risky_taxonomy_fp": dict(risky_taxonomy_fp),
    }
    return audit_rows, summary


def threshold_sensitivity(
    positive_rows: list[ManifestRow],
    hard_negative_rows: list[ManifestRow],
    predictions: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for threshold in THRESHOLDS:
        pos_audit, pos_summary = audit_positive_recall(positive_rows, predictions, threshold)
        del pos_audit
        fp_audit, fp_summary = audit_hard_negative_fp(hard_negative_rows, predictions, threshold)
        del fp_audit
        fp_taxonomy = fp_summary["fp_by_taxonomy"]
        rows.append(
            {
                "threshold": f"{threshold:.2f}",
                "positive_recall": f"{pos_summary['overall_positive_recall']:.6f}",
                "hard_negative_fp_count": fp_summary["fp_image_count"],
                "hard_negative_fp_rate": f"{fp_summary['fp_rate']:.6f}",
                "fall_recall": f"{pos_summary['class_recalls']['fall']:.6f}",
                "fallen_recall": f"{pos_summary['class_recalls']['fallen']:.6f}",
                "lying_recall": f"{pos_summary['class_recalls']['lying']:.6f}",
                "no_person_fp_count": fp_taxonomy.get("no_person", 0),
                "sit_fp_count": fp_taxonomy.get("sit", 0),
                "squat_fp_count": fp_taxonomy.get("squat", 0),
                "lie_down_non_fall_fp_count": fp_taxonomy.get("lie_down_non_fall", 0),
            }
        )
    return rows


def choose_threshold(rows: list[dict[str, Any]]) -> dict[str, Any]:
    parsed = []
    for row in rows:
        parsed.append(
            {
                **row,
                "threshold_float": float(row["threshold"]),
                "positive_recall_float": float(row["positive_recall"]),
                "fp_rate_float": float(row["hard_negative_fp_rate"]),
                "fp_count_int": int(row["hard_negative_fp_count"]),
            }
        )
    acceptable = [row for row in parsed if row["fp_rate_float"] <= 0.25]
    pool = acceptable if acceptable else parsed
    pool.sort(key=lambda item: (-item["positive_recall_float"], item["fp_rate_float"], abs(item["threshold_float"] - 0.25)))
    return pool[0]


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def list_eval_artifacts(run_dir: Path) -> dict[str, bool]:
    return {
        "confusion_matrix.png": (run_dir / "confusion_matrix.png").exists(),
        "confusion_matrix_normalized.png": (run_dir / "confusion_matrix_normalized.png").exists(),
        "PR_curve.png": (run_dir / "PR_curve.png").exists(),
        "F1_curve.png": (run_dir / "F1_curve.png").exists(),
        "P_curve.png": (run_dir / "P_curve.png").exists(),
        "R_curve.png": (run_dir / "R_curve.png").exists(),
        "val_batch0_pred.jpg": (run_dir / "val_batch0_pred.jpg").exists(),
    }


def render_fp_summary(summary: dict[str, Any]) -> str:
    top_lines = []
    for row in summary["top_confidence_examples"][:5]:
        top_lines.append(
            f"- `{Path(row['image_path']).name}` taxonomy=`{row['hard_negative_type']}` class=`{row['predicted_class']}` conf=`{float(row['confidence']):.3f}`"
        )
    risky = summary["risky_taxonomy_fp"]
    lines = [
        "## candidate_A2_hard_negative_fp_audit_summary_20260623",
        "",
        f"- hard negative total images: `{summary['hard_negative_total']}`",
        f"- hard negative FP images: `{summary['fp_image_count']}`",
        f"- FP rate: `{summary['fp_rate']:.4f}`",
        f"- no_person FP present: `{'YES' if summary['has_no_person_fp'] else 'NO'}`",
        f"- sit FP images: `{risky.get('sit', 0)}`",
        f"- squat FP images: `{risky.get('squat', 0)}`",
        f"- lie_down_non_fall FP images: `{risky.get('lie_down_non_fall', 0)}`",
        "",
        "### FP By Taxonomy",
        "",
    ]
    for key, value in sorted(summary["fp_by_taxonomy"].items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "### Top Confidence FP Samples", ""])
    lines.extend(top_lines or ["- none"])
    return "\n".join(lines) + "\n"


def render_positive_summary(summary: dict[str, Any]) -> str:
    missed = summary["missed_rows"][:5]
    lines = [
        "## candidate_A2_positive_recall_audit_summary_20260623",
        "",
        f"- positive total instances: `{summary['positive_total']}`",
        f"- fall recall: `{summary['class_recalls']['fall']:.4f}`",
        f"- fallen recall: `{summary['class_recalls']['fallen']:.4f}`",
        f"- lying recall: `{summary['class_recalls']['lying']:.4f}`",
        f"- overall positive recall: `{summary['overall_positive_recall']:.4f}`",
        f"- missed instances: `{len(summary['missed_rows'])}`",
        "",
        "### Top Missed Samples",
        "",
    ]
    for row in missed:
        lines.append(
            f"- `{Path(row['image_path']).name}` gt=`{row['gt_class']}` miss_reason=`{row['miss_reason']}`"
        )
    if not missed:
        lines.append("- none")
    if summary["class_recalls"]["lying"] == 0:
        lines.extend(["", "- lying class currently shows near-zero recall at the audit threshold."])
    return "\n".join(lines) + "\n"


def render_threshold_summary(rows: list[dict[str, Any]], chosen: dict[str, Any]) -> str:
    low = next((row for row in rows if row["threshold"] == "0.10"), None)
    high = next((row for row in rows if row["threshold"] == "0.50"), None)
    lines = [
        "## candidate_A2_threshold_sensitivity_summary_20260623",
        "",
        f"- recommended audit threshold: `{chosen['threshold']}`",
        f"- recommended positive recall: `{float(chosen['positive_recall']):.4f}`",
        f"- recommended hard negative FP rate: `{float(chosen['hard_negative_fp_rate']):.4f}`",
        "",
        "### Sweep Notes",
        "",
    ]
    if low and high:
        lines.append(
            f"- low threshold 0.10: positive recall `{float(low['positive_recall']):.4f}`, FP rate `{float(low['hard_negative_fp_rate']):.4f}`"
        )
        lines.append(
            f"- high threshold 0.50: positive recall `{float(high['positive_recall']):.4f}`, FP rate `{float(high['hard_negative_fp_rate']):.4f}`"
        )
        if float(low["hard_negative_fp_rate"]) > float(chosen["hard_negative_fp_rate"]) * 1.5:
            lines.append("- lower thresholds improve recall but materially increase false positives.")
        if float(high["positive_recall"]) < float(chosen["positive_recall"]) * 0.8:
            lines.append("- higher thresholds reduce false positives but push recall down too far.")
    lines.append("- threshold advice here is for candidate audit only and is not a deployment recommendation.")
    return "\n".join(lines) + "\n"


def render_compare_report(
    a2_metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
    a2_pos_summary: dict[str, Any],
    baseline_pos_summary: dict[str, Any],
    a2_fp_summary: dict[str, Any],
    baseline_fp_summary: dict[str, Any],
) -> str:
    lines = [
        "## candidate_A2_vs_baseline_eval_compare_complete_20260623",
        "",
        "### Raw Ultralytics Val Metrics",
        "",
        f"- A2 precision: `{a2_metrics['results_dict']['metrics/precision(B)']:.6f}`",
        f"- A2 recall: `{a2_metrics['results_dict']['metrics/recall(B)']:.6f}`",
        f"- A2 mAP50: `{a2_metrics['results_dict']['metrics/mAP50(B)']:.6f}`",
        f"- A2 mAP50-95: `{a2_metrics['results_dict']['metrics/mAP50-95(B)']:.6f}`",
        "",
        f"- baseline precision: `{baseline_metrics['results_dict']['metrics/precision(B)']:.6f}`",
        f"- baseline recall: `{baseline_metrics['results_dict']['metrics/recall(B)']:.6f}`",
        f"- baseline mAP50: `{baseline_metrics['results_dict']['metrics/mAP50(B)']:.6f}`",
        f"- baseline mAP50-95: `{baseline_metrics['results_dict']['metrics/mAP50-95(B)']:.6f}`",
        "",
        "Note: baseline is still an 8-class checkpoint while A2 is a 3-class checkpoint. The raw same-command baseline val metrics are recorded, but semantic per-class interpretation is not perfectly aligned.",
        "",
        "### Sample-Level Comparison At conf=0.25",
        "",
        f"- A2 positive recall: `{a2_pos_summary['overall_positive_recall']:.4f}`",
        f"- baseline positive recall: `{baseline_pos_summary['overall_positive_recall']:.4f}`",
        f"- A2 hard negative FP rate: `{a2_fp_summary['fp_rate']:.4f}`",
        f"- baseline hard negative FP rate: `{baseline_fp_summary['fp_rate']:.4f}`",
        "",
        "### Candidate Audit Recommendation",
        "",
    ]
    if a2_pos_summary["overall_positive_recall"] >= baseline_pos_summary["overall_positive_recall"] and a2_fp_summary["fp_rate"] <= baseline_fp_summary["fp_rate"]:
        lines.append("- A2 looks better positioned than baseline for continued candidate audit on this locked split.")
    else:
        lines.append("- A2 does not dominate baseline on every sample-level signal yet; continue candidate audit with caution.")
    lines.append("- Do not treat either block above as deployment approval.")
    return "\n".join(lines) + "\n"


def count_dir_files(path: Path) -> int:
    return sum(1 for item in path.iterdir() if item.is_file())


def git_state() -> str:
    import subprocess

    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def render_main_report(payload: dict[str, Any]) -> str:
    lines = [
        "## candidate_A2_eval_gaps_completion_report_20260623",
        "",
        "### Completion Status",
        "",
        f"- A2 eval gaps completion finished: `{'YES' if payload['completed'] else 'NO'}`",
        f"- formal val eval completed: `{'YES' if payload['formal_val_eval_completed'] else 'NO'}`",
        f"- baseline comparison completed: `{'YES' if payload['baseline_comparison_completed'] else 'NO'}`",
        f"- hard negative FP audit completed: `{'YES' if payload['hard_negative_fp_audit_completed'] else 'NO'}`",
        f"- positive recall audit completed: `{'YES' if payload['positive_recall_audit_completed'] else 'NO'}`",
        f"- threshold sensitivity completed: `{'YES' if payload['threshold_sensitivity_completed'] else 'NO'}`",
        f"- frozen/public eval completed: `{'YES' if payload['frozen_public_eval_completed'] else 'NO'}`",
        "",
        "### A2 Formal Val Metrics",
        "",
        f"- precision: `{payload['a2_metrics']['results_dict']['metrics/precision(B)']:.6f}`",
        f"- recall: `{payload['a2_metrics']['results_dict']['metrics/recall(B)']:.6f}`",
        f"- mAP50: `{payload['a2_metrics']['results_dict']['metrics/mAP50(B)']:.6f}`",
        f"- mAP50-95: `{payload['a2_metrics']['results_dict']['metrics/mAP50-95(B)']:.6f}`",
        f"- per-class fall: `P={payload['a2_metrics']['per_class'][0]['precision']:.4f} R={payload['a2_metrics']['per_class'][0]['recall']:.4f} mAP50={payload['a2_metrics']['per_class'][0]['mAP50']:.4f}`",
        f"- per-class fallen: `P={payload['a2_metrics']['per_class'][1]['precision']:.4f} R={payload['a2_metrics']['per_class'][1]['recall']:.4f} mAP50={payload['a2_metrics']['per_class'][1]['mAP50']:.4f}`",
        f"- per-class lying: `P={payload['a2_metrics']['per_class'][2]['precision']:.4f} R={payload['a2_metrics']['per_class'][2]['recall']:.4f} mAP50={payload['a2_metrics']['per_class'][2]['mAP50']:.4f}`",
        "",
        "### Baseline Val Metrics",
        "",
        f"- precision: `{payload['baseline_metrics']['results_dict']['metrics/precision(B)']:.6f}`",
        f"- recall: `{payload['baseline_metrics']['results_dict']['metrics/recall(B)']:.6f}`",
        f"- mAP50: `{payload['baseline_metrics']['results_dict']['metrics/mAP50(B)']:.6f}`",
        f"- mAP50-95: `{payload['baseline_metrics']['results_dict']['metrics/mAP50-95(B)']:.6f}`",
        "- note: baseline raw val metrics were captured on the same locked val split, but baseline remains an 8-class checkpoint and its first classes are not semantically identical to A2.",
        "",
        "### A2 vs Baseline Conclusion",
        "",
        f"- A2 sample-level positive recall at conf=0.25: `{payload['a2_positive_summary']['overall_positive_recall']:.4f}`",
        f"- baseline sample-level positive recall at conf=0.25: `{payload['baseline_positive_summary']['overall_positive_recall']:.4f}`",
        f"- A2 hard negative FP rate at conf=0.25: `{payload['a2_fp_summary']['fp_rate']:.4f}`",
        f"- baseline hard negative FP rate at conf=0.25: `{payload['baseline_fp_summary']['fp_rate']:.4f}`",
        "",
        "### Hard Negative FP Audit",
        "",
        f"- total hard negative val images: `{payload['a2_fp_summary']['hard_negative_total']}`",
        f"- A2 FP images: `{payload['a2_fp_summary']['fp_image_count']}`",
        f"- A2 FP rate: `{payload['a2_fp_summary']['fp_rate']:.4f}`",
        f"- no_person FP present: `{'YES' if payload['a2_fp_summary']['has_no_person_fp'] else 'NO'}`",
        f"- sit FP images: `{payload['a2_fp_summary']['risky_taxonomy_fp'].get('sit', 0)}`",
        f"- squat FP images: `{payload['a2_fp_summary']['risky_taxonomy_fp'].get('squat', 0)}`",
        f"- lie_down_non_fall FP images: `{payload['a2_fp_summary']['risky_taxonomy_fp'].get('lie_down_non_fall', 0)}`",
        "",
        "### Positive Recall Audit",
        "",
        f"- positive total instances: `{payload['a2_positive_summary']['positive_total']}`",
        f"- fall recall: `{payload['a2_positive_summary']['class_recalls']['fall']:.4f}`",
        f"- fallen recall: `{payload['a2_positive_summary']['class_recalls']['fallen']:.4f}`",
        f"- lying recall: `{payload['a2_positive_summary']['class_recalls']['lying']:.4f}`",
        f"- overall positive recall: `{payload['a2_positive_summary']['overall_positive_recall']:.4f}`",
        f"- missed instances: `{len(payload['a2_positive_summary']['missed_rows'])}`",
        "",
        "### Threshold Sensitivity",
        "",
        f"- recommended audit threshold: `{payload['recommended_threshold']['threshold']}`",
        f"- recommended positive recall: `{float(payload['recommended_threshold']['positive_recall']):.4f}`",
        f"- recommended FP rate: `{float(payload['recommended_threshold']['hard_negative_fp_rate']):.4f}`",
        "",
        "### Frozen/Public Eval Status",
        "",
        f"- frozen_public_eval_status: `{payload['frozen_public_eval_status']}`",
        "- public_test_freeze_manifest.csv and frozen_eval_assets.csv exist, but there is no ready A2-specific YOLO eval data.yaml / manifest bundle for direct locked-image detection eval in this stage.",
        "",
        "### Remaining Gaps",
        "",
    ]
    for gap in payload["remaining_gaps"]:
        lines.append(f"- {gap}")
    lines.extend(
        [
            "",
            "### Safety Review",
            "",
            f"- canonical dataset clean: `{'YES' if payload['canonical_dataset_clean'] else 'NO'}`",
            f"- baseline sha256 unchanged: `{'YES' if payload['baseline_sha_ok'] else 'NO'}`",
            f"- `.env` unchanged: `{'YES' if payload['env_unchanged'] else 'NO'}`",
            f"- locked split unchanged: `{'YES' if payload['locked_split_unchanged'] else 'NO'}`",
            f"- A2 weights copied to models: `NO`",
            f"- A2 weights integrated to system: `NO`",
            f"- git add/commit: `NO`",
            "",
            "### Gate",
            "",
            f"- candidate_A2_eval_gaps_completion_gate: `{payload['gate']}`",
            f"- next_allowed_stage: `{payload['next_allowed_stage']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    VAL_EVAL_PROJECT.mkdir(parents=True, exist_ok=True)

    manifest_rows = read_manifest_rows(MANIFEST_PATH)
    val_rows = [row for row in manifest_rows if row.split == "val"]
    positive_rows = [row for row in val_rows if row.label_type == "positive"]
    hard_negative_rows = [row for row in val_rows if row.label_type == "hard_negative"]
    image_paths = [row.dst_image_path for row in val_rows]

    a2_metrics = run_val_metrics(A2_MODEL_PATH)
    baseline_metrics = run_val_metrics(BASELINE_MODEL_PATH)

    a2_preds = run_predict(A2_MODEL_PATH, image_paths)
    baseline_preds = run_predict(BASELINE_MODEL_PATH, image_paths, semantic_map=BASELINE_SEMANTIC_CLASS_MAP)

    a2_fp_rows, a2_fp_summary = audit_hard_negative_fp(hard_negative_rows, a2_preds, AUDIT_THRESHOLD)
    baseline_fp_rows, baseline_fp_summary = audit_hard_negative_fp(hard_negative_rows, baseline_preds, AUDIT_THRESHOLD)
    del baseline_fp_rows
    a2_pos_rows, a2_pos_summary = audit_positive_recall(positive_rows, a2_preds, AUDIT_THRESHOLD)
    baseline_pos_rows, baseline_pos_summary = audit_positive_recall(positive_rows, baseline_preds, AUDIT_THRESHOLD)
    del baseline_pos_rows
    threshold_rows = threshold_sensitivity(positive_rows, hard_negative_rows, a2_preds)
    recommended_threshold = choose_threshold(threshold_rows)

    write_csv(FP_AUDIT_CSV, a2_fp_rows)
    FP_AUDIT_SUMMARY_MD.write_text(render_fp_summary(a2_fp_summary), encoding="utf-8")
    write_csv(POS_RECALL_CSV, a2_pos_rows)
    POS_RECALL_SUMMARY_MD.write_text(render_positive_summary(a2_pos_summary), encoding="utf-8")
    write_csv(THRESHOLD_CSV, threshold_rows)
    THRESHOLD_SUMMARY_MD.write_text(render_threshold_summary(threshold_rows, recommended_threshold), encoding="utf-8")
    COMPARE_MD.write_text(
        render_compare_report(
            a2_metrics,
            baseline_metrics,
            a2_pos_summary,
            baseline_pos_summary,
            a2_fp_summary,
            baseline_fp_summary,
        ),
        encoding="utf-8",
    )

    canonical_dataset_clean = (
        not (CANONICAL_DATASET_DIR / "labels" / "train.cache").exists()
        and not (CANONICAL_DATASET_DIR / "labels" / "val.cache").exists()
        and sha256(CANONICAL_DATASET_DIR / "data.yaml") == "548F6EF88A87E65AAC5693ED93DC5ED05F539DC03CB33514083E02F68504DC43"
        and sha256(CANONICAL_DATASET_DIR / "dataset_build_manifest.csv") == "E276A3E29CD6F9FF18C9FB5DAE34E3A5947AFA0A3CC25AD7D09E5E8C627811EE"
        and count_dir_files(CANONICAL_DATASET_DIR / "images" / "train") == 648
        and count_dir_files(CANONICAL_DATASET_DIR / "images" / "val") == 108
        and count_dir_files(CANONICAL_DATASET_DIR / "labels" / "train") == 648
        and count_dir_files(CANONICAL_DATASET_DIR / "labels" / "val") == 108
    )
    baseline_sha_ok = sha256(BASELINE_MODEL_PATH) == BASELINE_SHA256_EXPECTED
    env_unchanged = sha256(ENV_PATH) == "E441B883774D287FAED8B081FB3AB113DCD355A5172CAB3576AEBB2EE8FA00DB"
    locked_split_unchanged = {
        str(LOCKED_SPLIT_PATHS[0].name): sha256(LOCKED_SPLIT_PATHS[0]) == "626A464F9A296DECC6BE0F034DCA743F6B24F9A80E0A74AC7E4AD28C1918525F",
        str(LOCKED_SPLIT_PATHS[1].name): sha256(LOCKED_SPLIT_PATHS[1]) == "4E487477CCB1AFEA836E752A7150A4E5AF22144376C56BA65BF7CA8C36A3FC96",
        str(LOCKED_SPLIT_PATHS[2].name): sha256(LOCKED_SPLIT_PATHS[2]) == "6D61B0C0B3684884E89161513859949A8BAED922AC6AC82E359E133FDA9D519E",
        str(LOCKED_SPLIT_PATHS[3].name): sha256(LOCKED_SPLIT_PATHS[3]) == "30BDEA49EF1720E90679D3DE1F18B301DD3B2D7C3C2C6C174A14CB017ACD979B",
    }
    frozen_public_eval_status = "NOT_RUN_MISSING_READY_EVAL_CONFIG"
    remaining_gaps = []
    if frozen_public_eval_status == "NOT_RUN_MISSING_READY_EVAL_CONFIG":
        remaining_gaps.append("frozen/public eval still lacks a ready A2-specific YOLO eval config; manifests exist but not a direct image-label eval bundle.")
    if not canonical_dataset_clean:
        remaining_gaps.append("canonical dataset cleanliness check failed.")
    if not baseline_sha_ok:
        remaining_gaps.append("baseline sha256 mismatch.")
    if not env_unchanged:
        remaining_gaps.append(".env hash mismatch.")
    if not all(locked_split_unchanged.values()):
        remaining_gaps.append("locked split hash mismatch.")

    if not canonical_dataset_clean or not baseline_sha_ok or not env_unchanged or not all(locked_split_unchanged.values()):
        gate = "BLOCKED"
        next_allowed_stage = "BLOCKED_CLEANUP_REQUIRED"
    elif frozen_public_eval_status == "NOT_RUN_MISSING_READY_EVAL_CONFIG":
        gate = "PASS_WITH_FROZEN_PUBLIC_EVAL_GAP"
        next_allowed_stage = "MODEL_CANDIDATE_A2_AUDIT_WITH_KNOWN_EVAL_GAP"
    else:
        gate = "PASS"
        next_allowed_stage = "MODEL_CANDIDATE_A2_AUDIT_WITH_THRESHOLD_RECOMMENDATION"

    payload = {
        "completed": True,
        "formal_val_eval_completed": True,
        "baseline_comparison_completed": True,
        "hard_negative_fp_audit_completed": True,
        "positive_recall_audit_completed": True,
        "threshold_sensitivity_completed": True,
        "frozen_public_eval_completed": False,
        "a2_metrics": a2_metrics,
        "baseline_metrics": baseline_metrics,
        "a2_positive_summary": a2_pos_summary,
        "baseline_positive_summary": baseline_pos_summary,
        "a2_fp_summary": a2_fp_summary,
        "baseline_fp_summary": baseline_fp_summary,
        "recommended_threshold": recommended_threshold,
        "frozen_public_eval_status": frozen_public_eval_status,
        "remaining_gaps": remaining_gaps,
        "canonical_dataset_clean": canonical_dataset_clean,
        "baseline_sha_ok": baseline_sha_ok,
        "env_unchanged": env_unchanged,
        "locked_split_unchanged": all(locked_split_unchanged.values()),
        "gate": gate,
        "next_allowed_stage": next_allowed_stage,
    }
    MAIN_REPORT_MD.write_text(render_main_report(payload), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
