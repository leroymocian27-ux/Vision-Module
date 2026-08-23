from __future__ import annotations

import csv
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "runs" / "fall_hint_v3_candidates_202607"
DATASET_ROOT = ROOT / "datasets" / "fall_hint_v3_balanced_hardcase_202607"
DATASET_YAML = DATASET_ROOT / "dataset.yaml"
ACCEPTANCE_MANIFEST = DATASET_ROOT / "acceptance" / "manifest.csv"
BASELINE_SOURCE_JSON = OUTPUT_ROOT / "baseline_model_source.json"
CANDIDATE_MANIFEST_JSON = OUTPUT_ROOT / "candidate_manifest.json"
ULTRALYTICS_SETTINGS_DIR = ROOT / "runs" / "_ultralytics_settings"
ULTRALYTICS_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_SETTINGS_DIR)

TARGET_CLASS_NAMES = ["standing", "fallen", "sitting", "lying", "falling", "kneeling", "bending"]
OLD_ORDER_NAMES = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
TARGET_TO_OLD = {0: 6, 1: 1, 2: 3, 3: 2, 4: 0, 5: 5, 6: 4}
CRITICAL_CLASSES = ["falling", "fallen", "sitting", "lying", "kneeling", "bending"]
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
IOU_MATCH = 0.50
ACCEPTANCE_CONF = 0.25


@dataclass
class AcceptanceRow:
    acceptance_id: str
    category: str
    image_path: Path
    label_path: Path
    expected_behavior: str
    should_trigger_fall_alarm: bool


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


def load_candidate_manifest() -> tuple[dict[str, Any], dict[str, str]]:
    baseline_source = json.loads(BASELINE_SOURCE_JSON.read_text(encoding="utf-8"))
    candidate_manifest = json.loads(CANDIDATE_MANIFEST_JSON.read_text(encoding="utf-8"))
    models = {
        "baseline": str(baseline_source["baseline_model"]),
    }
    for name, payload in candidate_manifest["candidates"].items():
        models[name] = payload["best_pt"]
    return candidate_manifest, models


def prepare_baseline_eval_dataset() -> Path:
    baseline_eval_root = OUTPUT_ROOT / "baseline_eval_dataset_old_order"
    if baseline_eval_root.exists():
        return baseline_eval_root / "dataset.yaml"

    (baseline_eval_root / "test" / "images").mkdir(parents=True, exist_ok=True)
    (baseline_eval_root / "test" / "labels").mkdir(parents=True, exist_ok=True)

    for image_path in sorted((DATASET_ROOT / "test" / "images").glob("*")):
        target = baseline_eval_root / "test" / "images" / image_path.name
        target.write_bytes(image_path.read_bytes())

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
    with path.open("rb") as handle:
        header = handle.read(26)
    if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        return width, height
    if header[:2] == b"\xff\xd8":
        return read_jpeg_size(path)
    return 1, 1


def read_jpeg_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        handle.read(2)
        while True:
            prefix = handle.read(1)
            if not prefix:
                return 1, 1
            if prefix != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if marker in {b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"}:
                _length = int.from_bytes(handle.read(2), "big")
                handle.read(1)
                height = int.from_bytes(handle.read(2), "big")
                width = int.from_bytes(handle.read(2), "big")
                return width, height
            if marker in {b"\xd8", b"\xd9"}:
                continue
            length_bytes = handle.read(2)
            if len(length_bytes) != 2:
                return 1, 1
            length = int.from_bytes(length_bytes, "big")
            if length < 2:
                return 1, 1
            handle.seek(length - 2, 1)


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
                expected_behavior="fall_alarm_allowed" if row["source_category"] == "real_fall" else "no_fall_alarm",
                should_trigger_fall_alarm=row["source_category"] == "real_fall",
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
        project=str(OUTPUT_ROOT / f"eval_{model_name}"),
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
        "test_images": len(list((Path(read_yaml_path(data_yaml)["path"]) / "test" / "images").glob("*"))),
        "per_class_recall": per_class_recall,
    }


def read_yaml_path(path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        payload[key.strip()] = value.strip()
    return payload


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


def evaluate_acceptance_for_model(model_name: str, model_path: str, acceptance_rows: list[AcceptanceRow]) -> tuple[dict[str, object], list[dict[str, object]]]:
    image_paths = [row.image_path for row in acceptance_rows]
    predictions = predict_images(model_path, image_paths)
    summary = {
        "model_name": model_name,
        "acceptance_total": len(acceptance_rows),
        "empty_false_positive": 0,
        "sitting_false_fallen": 0,
        "bending_false_fallen": 0,
        "kneeling_false_fallen": 0,
        "lying_false_fallen": 0,
        "slow_fall_miss": 0,
        "real_fall_miss": 0,
        "false_fallen_on_adl": 0,
        "repeat_like_risk": 0,
        "accepted_for_shadow_mode": False,
        "reject_reason": "",
    }
    details: list[dict[str, object]] = []

    for row in acceptance_rows:
        preds = predictions[str(row.image_path)]
        width, height = read_image_size(row.image_path)
        targets = parse_target_label(row.label_path, width, height)
        fall_like_preds = [pred for pred in preds if pred["class_name"] in FALL_LIKE]
        top_class = preds[0]["class_name"] if preds else "none"
        repeat_like = len(fall_like_preds) >= 2
        if repeat_like and row.category != "real_fall":
            summary["repeat_like_risk"] += 1

        if row.category == "empty_scene" and preds:
            summary["empty_false_positive"] += 1
        elif row.category == "sitting_as_fall" and fall_like_preds:
            summary["sitting_false_fallen"] += 1
        elif row.category == "bending_as_fall" and fall_like_preds:
            summary["bending_false_fallen"] += 1
        elif row.category == "kneeling_as_fall" and fall_like_preds:
            summary["kneeling_false_fallen"] += 1
        elif row.category == "lying_adl_as_fall" and fall_like_preds:
            summary["lying_false_fallen"] += 1

        if row.category in ADL_NEGATIVE_CATEGORIES and fall_like_preds:
            summary["false_fallen_on_adl"] += 1

        if row.category == "real_fall":
            matched = acceptance_match(preds, targets, FALL_LIKE)
            if not matched:
                summary["real_fall_miss"] += 1
        elif row.category == "slow_fall_like":
            matched = acceptance_match(preds, targets, FALL_LIKE)
            if not matched:
                summary["slow_fall_miss"] += 1

        details.append(
            {
                "model_name": model_name,
                "acceptance_id": row.acceptance_id,
                "category": row.category,
                "top_class": top_class,
                "prediction_count": len(preds),
                "fall_like_prediction_count": len(fall_like_preds),
                "repeat_like_risk": repeat_like,
                "real_fall_match": acceptance_match(preds, targets, FALL_LIKE) if row.category == "real_fall" else "",
                "slow_fall_match": acceptance_match(preds, targets, FALL_LIKE) if row.category == "slow_fall_like" else "",
            }
        )
    return summary, details


def obvious_class_collapse(candidate_recalls: dict[str, float], baseline_recalls: dict[str, float]) -> bool:
    for class_name in CRITICAL_CLASSES:
        baseline_value = float(baseline_recalls.get(class_name, 0.0))
        candidate_value = float(candidate_recalls.get(class_name, 0.0))
        if baseline_value > 0.05 and candidate_value == 0.0:
            return True
    return False


def compare_candidates(
    test_rows: list[dict[str, Any]],
    acceptance_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, Any], str, list[str]]:
    baseline_test = next(row for row in test_rows if row["model_name"] == "baseline")
    baseline_acceptance = next(row for row in acceptance_rows if row["model_name"] == "baseline")
    recommended = "NONE"
    rejected_models: list[str] = []
    accepted_models: list[dict[str, object]] = []

    for row in acceptance_rows:
        if row["model_name"] == "baseline":
            row["accepted_for_shadow_mode"] = False
            row["reject_reason"] = "baseline_reference"
            continue
        test_row = next(item for item in test_rows if item["model_name"] == row["model_name"])
        reasons: list[str] = []
        if int(row["empty_false_positive"]) > int(baseline_acceptance["empty_false_positive"]):
            reasons.append("empty_false_positive_above_baseline")
        if int(row["false_fallen_on_adl"]) > int(baseline_acceptance["false_fallen_on_adl"]):
            reasons.append("false_fallen_on_adl_above_baseline")
        if int(row["real_fall_miss"]) > int(baseline_acceptance["real_fall_miss"]):
            reasons.append("real_fall_miss_above_baseline")
        if int(row["slow_fall_miss"]) > int(baseline_acceptance["slow_fall_miss"]) + 1:
            reasons.append("slow_fall_miss_significantly_above_baseline")
        if float(test_row["precision"]) < float(baseline_test["precision"]) - 0.10:
            reasons.append("precision_collapse_vs_baseline")
        if obvious_class_collapse(test_row["per_class_recall"], baseline_test["per_class_recall"]):
            reasons.append("obvious_class_collapse")

        row["accepted_for_shadow_mode"] = not reasons
        row["reject_reason"] = ",".join(reasons)
        if reasons:
            rejected_models.append(row["model_name"])
        else:
            accepted_models.append(
                {
                    "model_name": row["model_name"],
                    "false_fallen_on_adl": int(row["false_fallen_on_adl"]),
                    "empty_false_positive": int(row["empty_false_positive"]),
                    "real_fall_miss": int(row["real_fall_miss"]),
                    "mAP50-95": float(test_row["mAP50-95"]),
                }
            )

    if accepted_models:
        accepted_models.sort(
            key=lambda item: (
                item["real_fall_miss"],
                item["false_fallen_on_adl"],
                item["empty_false_positive"],
                -item["mAP50-95"],
                item["model_name"],
            )
        )
        recommended = accepted_models[0]["model_name"]

    decision = {
        "baseline": {
            "model_name": "baseline",
            "precision": baseline_test["precision"],
            "acceptance": baseline_acceptance,
        },
        "accepted_models": accepted_models,
        "recommended_model_for_shadow_mode": recommended,
        "rejected_models": rejected_models,
        "allow_shadow_mode": recommended != "NONE",
    }
    return acceptance_rows, decision, recommended, rejected_models


def render_model_comparison_md(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Model Comparison",
        "",
        "| model | precision | recall | mAP50 | mAP50-95 | fitness | test_images |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['model_name']} | {row['precision']:.4f} | {row['recall']:.4f} | {row['mAP50']:.4f} | {row['mAP50-95']:.4f} | {row['fitness']:.4f} | {row['test_images']} |"
        )
    return "\n".join(lines) + "\n"


def render_promotion_readiness(
    test_rows: list[dict[str, Any]],
    acceptance_rows: list[dict[str, object]],
    candidate_manifest: dict[str, Any],
    recommended: str,
    rejected_models: list[str],
) -> str:
    lines = [
        "# Promotion Readiness",
        "",
        "## 1. 本轮训练目标",
        "训练并比较 v3 三个候选模型，评估是否有模型允许进入 shadow mode。",
        "",
        "## 2. 使用的数据集",
        f"- {DATASET_YAML}",
        "",
        "## 3. 基线模型路径",
        f"- {json.loads(BASELINE_SOURCE_JSON.read_text(encoding='utf-8'))['baseline_model']}",
        "",
        "## 4. 候选模型路径",
    ]
    for name, payload in candidate_manifest["candidates"].items():
        lines.append(f"- {name}: `{payload['best_pt']}`")
    lines.extend(["", "## 5. 标准 test 结果"])
    for row in test_rows:
        lines.append(
            f"- {row['model_name']}: precision={row['precision']:.4f}, recall={row['recall']:.4f}, mAP50={row['mAP50']:.4f}, mAP50-95={row['mAP50-95']:.4f}"
        )
    lines.extend(["", "## 6. acceptance 结果"])
    for row in acceptance_rows:
        lines.append(
            f"- {row['model_name']}: empty_fp={row['empty_false_positive']}, false_fallen_on_adl={row['false_fallen_on_adl']}, real_fall_miss={row['real_fall_miss']}, slow_fall_miss={row['slow_fall_miss']}, accepted_for_shadow_mode={row['accepted_for_shadow_mode']}"
        )
    lines.extend(
        [
            "",
            "## 7. 最适合进入 shadow mode 的模型",
            f"- {recommended}",
            "",
            "## 8. 明确不建议使用的模型",
            f"- {', '.join(rejected_models) if rejected_models else 'none'}",
            "",
            "## 9. 是否允许替换正式模型",
            "- NO",
            "",
            "## 10. 下一步操作建议",
            f"- {'允许进入 shadow mode' if recommended != 'NONE' else '暂不允许进入 shadow mode'}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    candidate_manifest, model_paths = load_candidate_manifest()
    baseline_eval_yaml = prepare_baseline_eval_dataset()
    acceptance_rows = load_acceptance_rows()

    test_metric_rows: list[dict[str, Any]] = []
    for model_name, model_path in model_paths.items():
        data_yaml = baseline_eval_yaml if model_name == "baseline" else DATASET_YAML
        test_metric_rows.append(eval_test_metrics(model_name, model_path, data_yaml))

    acceptance_summary_rows: list[dict[str, object]] = []
    acceptance_detail_rows: list[dict[str, object]] = []
    for model_name, model_path in model_paths.items():
        summary, details = evaluate_acceptance_for_model(model_name, model_path, acceptance_rows)
        acceptance_summary_rows.append(summary)
        acceptance_detail_rows.extend(details)

    acceptance_summary_rows, decision, recommended, rejected_models = compare_candidates(
        test_metric_rows,
        acceptance_summary_rows,
    )

    model_comparison_rows = [
        {
            "model_name": row["model_name"],
            "model_path": row["model_path"],
            "precision": row["precision"],
            "recall": row["recall"],
            "mAP50": row["mAP50"],
            "mAP50-95": row["mAP50-95"],
            "fitness": row["fitness"],
            "test_images": row["test_images"],
        }
        for row in test_metric_rows
    ]
    write_csv(OUTPUT_ROOT / "model_comparison.csv", model_comparison_rows)
    write_text(OUTPUT_ROOT / "model_comparison.md", render_model_comparison_md(model_comparison_rows))
    write_csv(OUTPUT_ROOT / "acceptance_eval_summary.csv", acceptance_summary_rows)
    write_csv(OUTPUT_ROOT / "acceptance_eval_details.csv", acceptance_detail_rows)
    write_json(OUTPUT_ROOT / "acceptance_decision.json", decision)
    write_text(
        OUTPUT_ROOT / "promotion_readiness.md",
        render_promotion_readiness(
            test_metric_rows,
            acceptance_summary_rows,
            candidate_manifest,
            recommended,
            rejected_models,
        ),
    )
    safety_lines = [
        "# Safety Check",
        "",
        "- 是否训练候选模型：YES",
        "- 是否替换正式权重：NO",
        "- 是否修改 .env：NO",
        "- 是否修改正式告警链路：NO",
        "- 是否把 acceptance 加入训练：NO",
        "- 是否删除原始数据：NO",
        "- 是否可直接上线：NO",
        f"- 是否只允许进入 shadow mode：{'YES' if recommended != 'NONE' else 'NO'}",
    ]
    write_text(OUTPUT_ROOT / "safety_check.md", "\n".join(safety_lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
