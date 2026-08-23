from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "runs" / "fall_hint_v3_c_precision_polish_20260705"
DATASET_ROOT = ROOT / "datasets" / "fall_hint_v3_balanced_hardcase_202607"
DATASET_YAML = DATASET_ROOT / "dataset.yaml"
V3_MANIFEST = DATASET_ROOT / "manifest.csv"
ACCEPTANCE_MANIFEST = DATASET_ROOT / "acceptance" / "manifest.csv"
REVIEWED_ROOT = ROOT / "datasets" / "fall_hint_v2_clean_reviewed_only_noaug_20260703"
REVIEWED_MANIFEST = REVIEWED_ROOT / "meta" / "manifest.csv"
BANK_ROOT = ROOT / "datasets" / "fall_false_positive_bank_202607"
BANK_MANIFEST = BANK_ROOT / "manifest.csv"
BASELINE_MODEL = ROOT / "models" / "7-3testmodel.pt"
CANDIDATE_MODEL = (
    ROOT
    / "runs"
    / "fall_hint_v3_candidates_202607"
    / "candidate_v3_c_temporal_friendly"
    / "weights"
    / "best.pt"
)
ULTRALYTICS_SETTINGS_DIR = ROOT / "runs" / "_ultralytics_settings"
ULTRALYTICS_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_SETTINGS_DIR)

TARGET_CLASS_NAMES = ["standing", "fallen", "sitting", "lying", "falling", "kneeling", "bending"]
OLD_ORDER_NAMES = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
OLD_TO_NEW = {0: 4, 1: 1, 2: 3, 3: 2, 4: 6, 5: 5, 6: 0}
TARGET_TO_OLD = {0: 6, 1: 1, 2: 3, 3: 2, 4: 0, 5: 5, 6: 4}
SUPPLEMENT_REVIEWED_CLASSES = {"sitting", "lying", "kneeling", "bending"}
SUPPLEMENT_BANK_REVIEWED_CLASSES = {"__empty__", "sitting", "kneeling", "bending"}
IOU_MATCH = 0.50
ACCEPTANCE_CONF = 0.25


@dataclass
class AcceptanceRow:
    acceptance_id: str
    category: str
    image_path: Path
    label_path: Path


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


def runtime_device() -> str | int:
    import torch

    return 0 if torch.cuda.is_available() else "cpu"


def read_yaml_path(path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        payload[key.strip()] = value.strip()
    return payload


def ensure_clean_run_root() -> None:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)


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


def copy_train_base(variant_root: Path) -> tuple[int, int]:
    train_image_dir = variant_root / "train" / "images"
    train_label_dir = variant_root / "train" / "labels"
    train_image_dir.mkdir(parents=True, exist_ok=True)
    train_label_dir.mkdir(parents=True, exist_ok=True)
    copied_images = 0
    copied_labels = 0
    for image_path in sorted((DATASET_ROOT / "train" / "images").glob("*")):
        shutil.copy2(image_path, train_image_dir / image_path.name)
        copied_images += 1
    for label_path in sorted((DATASET_ROOT / "train" / "labels").glob("*.txt")):
        shutil.copy2(label_path, train_label_dir / label_path.name)
        copied_labels += 1
    return copied_images, copied_labels


def choose_supplement_rows() -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, object]]:
    v3_rows = read_csv(V3_MANIFEST)
    reviewed_rows = read_csv(REVIEWED_MANIFEST)
    bank_rows = read_csv(BANK_MANIFEST)

    used_reviewed_images = {
        Path(row["source_image_path"]).name
        for row in v3_rows
        if row.get("source_dataset") == "fall_hint_v2_clean_reviewed_only_noaug_20260703"
    }
    used_bank_images = {
        Path(row["source_image_path"]).name
        for row in v3_rows
        if row.get("source_dataset") == "fall_false_positive_bank_202607"
    }
    test_source_files = {
        row["source_file"].lower()
        for row in v3_rows
        if row.get("split") == "test"
    }

    reviewed_selected = [
        row
        for row in reviewed_rows
        if Path(row["source_archive_image"]).name not in used_reviewed_images
        and row["source_video"].lower() not in test_source_files
        and row["class_names"] in SUPPLEMENT_REVIEWED_CLASSES
    ]
    bank_selected = [
        row
        for row in bank_rows
        if Path(row["bank_image_path"]).name not in used_bank_images
        and row.get("is_acceptance_candidate", "").lower() != "true"
        and row["source_file"].lower() not in test_source_files
        and row["reviewed_class"] in SUPPLEMENT_BANK_REVIEWED_CLASSES
    ]

    summary = {
        "reviewed_selected_count": len(reviewed_selected),
        "bank_selected_count": len(bank_selected),
        "reviewed_selected_class_counts": count_by_key(reviewed_selected, "class_names"),
        "bank_selected_reviewed_class_counts": count_by_key(bank_selected, "reviewed_class"),
    }
    return reviewed_selected, bank_selected, summary


def count_by_key(rows: list[dict[str, str]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key, "")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def build_dataset_variant() -> tuple[Path, list[dict[str, object]], dict[str, object]]:
    variant_root = RUN_ROOT / "dataset_variant_candidate_v3_c_polish"
    if variant_root.exists():
        shutil.rmtree(variant_root)
    base_images, base_labels = copy_train_base(variant_root)
    reviewed_selected, bank_selected, selection_summary = choose_supplement_rows()

    supplement_manifest_rows: list[dict[str, object]] = []
    supplement_index = 0

    for row in reviewed_selected:
        supplement_index += 1
        src_image = REVIEWED_ROOT / row["image"]
        src_label = REVIEWED_ROOT / row["label"]
        dst_stem = f"reviewed_polish_{supplement_index:04d}"
        dst_image = variant_root / "train" / "images" / f"{dst_stem}{src_image.suffix.lower()}"
        dst_label = variant_root / "train" / "labels" / f"{dst_stem}.txt"
        shutil.copy2(src_image, dst_image)
        dst_label.write_text(remap_old_order_label_text(src_label.read_text(encoding="utf-8")), encoding="utf-8")
        supplement_manifest_rows.append(
            {
                "supplement_id": dst_stem,
                "source_type": "reviewed_unused_no_leak",
                "image_path": str(dst_image),
                "label_path": str(dst_label),
                "source_video": row["source_video"],
                "source_batch_id": row["source_batch_id"],
                "source_original_image": row["source_original_image"],
                "class_names": row["class_names"],
            }
        )

    for row in bank_selected:
        supplement_index += 1
        src_image = Path(row["bank_image_path"])
        src_label = Path(row["bank_label_path"])
        dst_stem = f"bank_polish_{supplement_index:04d}"
        dst_image = variant_root / "train" / "images" / f"{dst_stem}{src_image.suffix.lower()}"
        dst_label = variant_root / "train" / "labels" / f"{dst_stem}.txt"
        shutil.copy2(src_image, dst_image)
        if row["reviewed_class"] == "__empty__":
            dst_label.write_text("", encoding="utf-8")
        else:
            dst_label.write_text(remap_old_order_label_text(src_label.read_text(encoding="utf-8")), encoding="utf-8")
        supplement_manifest_rows.append(
            {
                "supplement_id": dst_stem,
                "source_type": "bank_unused_no_leak",
                "image_path": str(dst_image),
                "label_path": str(dst_label),
                "source_video": row["source_file"],
                "source_batch_id": row["source_batch"],
                "source_original_image": row["source_image_path"],
                "class_names": row["reviewed_class"],
            }
        )

    dataset_yaml = "\n".join(
        [
            f"path: {variant_root.as_posix()}",
            "train: train/images",
            f"val: {(DATASET_ROOT / 'val' / 'images').as_posix()}",
            f"test: {(DATASET_ROOT / 'test' / 'images').as_posix()}",
            "",
            "names:",
            *[f"  {idx}: {name}" for idx, name in enumerate(TARGET_CLASS_NAMES)],
            "",
        ]
    )
    write_text(variant_root / "dataset.yaml", dataset_yaml)
    write_csv(variant_root / "supplement_manifest.csv", supplement_manifest_rows)
    summary = {
        "variant_root": str(variant_root),
        "base_train_images": base_images,
        "base_train_labels": base_labels,
        "supplement_count": len(supplement_manifest_rows),
        "selection_summary": selection_summary,
    }
    write_json(variant_root / "variant_summary.json", summary)
    return variant_root / "dataset.yaml", supplement_manifest_rows, summary


def train_polish_model(data_yaml: Path) -> dict[str, object]:
    from ultralytics import YOLO

    run_name = "candidate_v3_c_polish"
    start_time = time.time()
    last_error = ""
    for batch_size in (16, 8, 4):
        save_dir = RUN_ROOT / run_name
        if save_dir.exists():
            shutil.rmtree(save_dir)
        try:
            model = YOLO(str(CANDIDATE_MODEL))
            result = model.train(
                data=str(data_yaml),
                project=str(RUN_ROOT),
                name=run_name,
                exist_ok=True,
                device=runtime_device(),
                workers=0,
                batch=batch_size,
                imgsz=640,
                epochs=14,
                patience=5,
                seed=52,
                lr0=0.0002,
                lrf=0.01,
                mosaic=0.0,
                mixup=0.0,
                copy_paste=0.0,
                close_mosaic=0,
                fliplr=0.5,
                translate=0.01,
                scale=0.05,
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
                raise RuntimeError(f"missing best.pt: {best_pt}")
            payload = {
                "train_dir": str(train_dir),
                "best_pt": str(best_pt),
                "last_pt": str(last_pt),
                "duration_sec": round(time.time() - start_time, 2),
                "config": {
                    "epochs": 14,
                    "patience": 5,
                    "lr0": 0.0002,
                    "lrf": 0.01,
                    "mosaic": 0.0,
                    "translate": 0.01,
                    "scale": 0.05,
                    "batch": batch_size,
                    "imgsz": 640,
                },
            }
            write_json(RUN_ROOT / "train_payload.json", payload)
            return payload
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            lowered = last_error.lower()
            if any(token in lowered for token in ("out of memory", "cuda", "cudnn")) and batch_size != 4:
                continue
            raise
    raise RuntimeError(f"candidate_v3_c_polish training failed: {last_error}")


def prepare_baseline_eval_dataset() -> Path:
    baseline_eval_root = RUN_ROOT / "baseline_eval_dataset_old_order"
    if baseline_eval_root.exists():
        return baseline_eval_root / "dataset.yaml"

    (baseline_eval_root / "test" / "images").mkdir(parents=True, exist_ok=True)
    (baseline_eval_root / "test" / "labels").mkdir(parents=True, exist_ok=True)

    for image_path in sorted((DATASET_ROOT / "test" / "images").glob("*")):
        shutil.copy2(image_path, baseline_eval_root / "test" / "images" / image_path.name)

    for label_path in sorted((DATASET_ROOT / "test" / "labels").glob("*.txt")):
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


def normalize_semantic(name: str) -> str:
    return name.strip().lower()


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


def parse_target_label(label_path: Path, image_width: int, image_height: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = label_path.read_text(encoding="utf-8").strip()
    if not text:
        return rows
    for raw in text.splitlines():
        class_id_str, x_str, y_str, w_str, h_str = raw.split()
        class_id = int(class_id_str)
        xc = float(x_str) * image_width
        yc = float(y_str) * image_height
        bw = float(w_str) * image_width
        bh = float(h_str) * image_height
        rows.append(
            {
                "class_name": TARGET_CLASS_NAMES[class_id],
                "bbox_xyxy": [xc - bw / 2.0, yc - bh / 2.0, xc + bw / 2.0, yc + bh / 2.0],
            }
        )
    return rows


def load_acceptance_rows() -> list[AcceptanceRow]:
    rows: list[AcceptanceRow] = []
    for row in read_csv(ACCEPTANCE_MANIFEST):
        rows.append(
            AcceptanceRow(
                acceptance_id=row["v3_id"],
                category=row["source_category"],
                image_path=Path(row["v3_image_path"]),
                label_path=Path(row["v3_label_path"]),
            )
        )
    return rows


def predict_images(model_path: str, image_paths: list[Path]) -> dict[str, list[dict[str, Any]]]:
    from ultralytics import YOLO

    model = YOLO(model_path)
    results = model.predict(
        source=[str(path) for path in image_paths],
        conf=ACCEPTANCE_CONF,
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
            for xyxy, conf, cls_idx in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()):
                class_id = int(cls_idx)
                class_name = normalize_semantic(result.names[class_id])
                preds.append(
                    {
                        "class_name": class_name,
                        "confidence": float(conf),
                        "bbox_xyxy": [float(value) for value in xyxy],
                    }
                )
        preds.sort(key=lambda item: item["confidence"], reverse=True)
        normalized[str(image_path)] = preds
    return normalized


def eval_test_metrics(model_name: str, model_path: str, data_yaml: Path) -> dict[str, Any]:
    from ultralytics import YOLO

    model = YOLO(model_path)
    metrics = model.val(
        data=str(data_yaml),
        split="test",
        imgsz=640,
        device=runtime_device(),
        project=str(RUN_ROOT / f"eval_{model_name}"),
        name="test_eval",
        exist_ok=True,
        workers=0,
        verbose=False,
    )
    per_class_recall: dict[str, float] = {}
    ap_class_index = list(getattr(metrics.box, "ap_class_index", []))
    for idx, class_slot in enumerate(ap_class_index):
        precision, recall, map50, map95 = metrics.box.class_result(idx)
        name = normalize_semantic(metrics.names[int(class_slot)])
        per_class_recall[name] = float(recall)
    return {
        "model_name": model_name,
        "model_path": model_path,
        "precision": float(metrics.box.mp),
        "recall": float(metrics.box.mr),
        "mAP50": float(metrics.box.map50),
        "mAP50-95": float(metrics.box.map),
        "fitness": float(metrics.fitness),
        "per_class_recall": per_class_recall,
    }


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


def evaluate_acceptance_for_model(model_name: str, model_path: str, acceptance_rows: list[AcceptanceRow]) -> dict[str, object]:
    fall_like = {"falling", "fallen"}
    adl_negative_categories = {
        "sitting_as_fall",
        "bending_as_fall",
        "kneeling_as_fall",
        "lying_adl_as_fall",
        "low_posture",
        "normal_standing",
        "edge_cases",
    }
    image_paths = [row.image_path for row in acceptance_rows]
    predictions = predict_images(model_path, image_paths)
    summary = {
        "model_name": model_name,
        "acceptance_total": len(acceptance_rows),
        "empty_false_positive": 0,
        "false_fallen_on_adl": 0,
        "real_fall_miss": 0,
        "repeat_like_risk": 0,
    }

    for row in acceptance_rows:
        preds = predictions[str(row.image_path)]
        width, height = read_image_size(row.image_path)
        targets = parse_target_label(row.label_path, width, height)
        fall_like_preds = [pred for pred in preds if pred["class_name"] in fall_like]
        if len(fall_like_preds) >= 2 and row.category != "real_fall":
            summary["repeat_like_risk"] += 1
        if row.category == "empty_scene" and preds:
            summary["empty_false_positive"] += 1
        if row.category in adl_negative_categories and fall_like_preds:
            summary["false_fallen_on_adl"] += 1
        if row.category == "real_fall":
            matched = acceptance_match(preds, targets, fall_like)
            if not matched:
                summary["real_fall_miss"] += 1
    return summary


def render_report(
    dataset_summary: dict[str, object],
    train_payload: dict[str, object],
    metric_rows: list[dict[str, Any]],
    acceptance_rows: list[dict[str, object]],
) -> str:
    lines = [
        "# Candidate v3 c Precision Polish",
        "",
        f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- base_candidate: `{CANDIDATE_MODEL}`",
        f"- supplement_count: {dataset_summary['supplement_count']}",
        f"- reviewed_unused_added: {dataset_summary['selection_summary']['reviewed_selected_count']}",
        f"- bank_unused_added: {dataset_summary['selection_summary']['bank_selected_count']}",
        "",
        "## Train",
        f"- best_pt: `{train_payload['best_pt']}`",
        f"- duration_sec: {train_payload['duration_sec']}",
        f"- config: `{json.dumps(train_payload['config'], ensure_ascii=False)}`",
        "",
        "## Test Metrics",
    ]
    for row in metric_rows:
        lines.append(
            f"- {row['model_name']}: precision={row['precision']:.4f}, recall={row['recall']:.4f}, mAP50={row['mAP50']:.4f}, mAP50-95={row['mAP50-95']:.4f}"
        )
    lines.extend(["", "## Acceptance"])
    for row in acceptance_rows:
        lines.append(
            f"- {row['model_name']}: empty_fp={row['empty_false_positive']}, false_fallen_on_adl={row['false_fallen_on_adl']}, real_fall_miss={row['real_fall_miss']}, repeat_like_risk={row['repeat_like_risk']}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ensure_clean_run_root()
    data_yaml, supplement_manifest_rows, dataset_summary = build_dataset_variant()
    train_payload = train_polish_model(data_yaml)

    baseline_eval_yaml = prepare_baseline_eval_dataset()
    acceptance_rows = load_acceptance_rows()
    models = {
        "baseline": (str(BASELINE_MODEL), baseline_eval_yaml),
        "candidate_v3_c": (str(CANDIDATE_MODEL), DATASET_YAML),
        "candidate_v3_c_polish": (str(train_payload["best_pt"]), DATASET_YAML),
    }

    metric_rows: list[dict[str, Any]] = []
    acceptance_summary_rows: list[dict[str, object]] = []
    for model_name, (model_path, eval_yaml) in models.items():
        metric_rows.append(eval_test_metrics(model_name, model_path, eval_yaml))
        acceptance_summary_rows.append(evaluate_acceptance_for_model(model_name, model_path, acceptance_rows))

    write_csv(
        RUN_ROOT / "metric_comparison.csv",
        [
            {
                "model_name": row["model_name"],
                "model_path": row["model_path"],
                "precision": row["precision"],
                "recall": row["recall"],
                "mAP50": row["mAP50"],
                "mAP50-95": row["mAP50-95"],
                "fitness": row["fitness"],
            }
            for row in metric_rows
        ],
    )
    write_csv(RUN_ROOT / "acceptance_comparison.csv", acceptance_summary_rows)
    write_json(
        RUN_ROOT / "polish_summary.json",
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "dataset_variant": str(data_yaml),
            "dataset_summary": dataset_summary,
            "supplement_manifest_count": len(supplement_manifest_rows),
            "train_payload": train_payload,
            "metrics": metric_rows,
            "acceptance": acceptance_summary_rows,
            "safety": {
                "replaced_production_model": False,
                "modified_env": False,
                "modified_alarm_chain": False,
            },
        },
    )
    write_text(RUN_ROOT / "README.md", render_report(dataset_summary, train_payload, metric_rows, acceptance_summary_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
