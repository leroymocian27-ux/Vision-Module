from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "datasets" / "fall_hint_v2_finetune_seed_7_3testmodel_v1" / "data.yaml"
DEFAULT_EMPTY_HOLDOUT = ROOT / "datasets" / "fall_hint_v2_finetune_seed_7_3testmodel_v1" / "meta" / "empty_holdout_manifest.csv"
DEFAULT_PROJECT = ROOT / "runs" / "fall_hint_seed_finetune_20260703_v2" / "threshold_sweep"
DEFAULT_BASELINE = ROOT / "models" / "yolo_fall_hint_v2_plus_b012_best.pt"
ULTRALYTICS_SETTINGS_DIR = ROOT / "runs" / "_ultralytics_settings"
ULTRALYTICS_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(ULTRALYTICS_SETTINGS_DIR)

from ultralytics import YOLO

CLASS_NAMES = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
ADL_CLASSES = {"sitting", "kneeling", "lying"}
HARD_KL_CLASSES = {"kneeling", "lying"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep confidence thresholds for Fall Hint candidate comparison.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--empty-holdout-manifest", type=Path, default=DEFAULT_EMPTY_HOLDOUT)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--device", default="0")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--thresholds", default="0.25,0.30,0.35,0.40,0.45,0.50")
    parser.add_argument("--baseline-name", default="runtime_current")
    parser.add_argument("--baseline-model", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--candidate", action="append", default=[])
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def persist_sweep_progress(
    *,
    summary_csv: Path,
    details_csv: Path,
    summary_rows: list[dict[str, object]],
    detail_rows: list[dict[str, object]],
) -> None:
    write_csv(summary_csv, summary_rows)
    write_csv(details_csv, detail_rows)


def parse_candidates(raw_candidates: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for raw in raw_candidates:
        if "=" not in raw:
            raise SystemExit(f"candidate must be name=path, got: {raw}")
        name, model = raw.split("=", 1)
        parsed[name.strip()] = Path(model.strip()).resolve()
    return parsed


def parse_thresholds(raw: str) -> list[float]:
    values: list[float] = []
    for item in raw.split(","):
        value = float(item.strip())
        if not 0.0 <= value <= 1.0:
            raise SystemExit(f"threshold must be within [0,1], got {value}")
        values.append(value)
    if not values:
        raise SystemExit("at least one threshold is required")
    return values


def detect_dataset_root(data_yaml: Path) -> Path:
    path_value = ""
    for raw in data_yaml.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("path:"):
            path_value = line.split(":", 1)[1].strip()
            break
    if not path_value:
        raise SystemExit(f"could not resolve dataset root from {data_yaml}")
    return Path(path_value)


def top_prediction(result: Any) -> str:
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return "none"
    confs = [float(value) for value in boxes.conf.detach().cpu().tolist()]
    cls_ids = [int(value) for value in boxes.cls.detach().cpu().tolist()]
    best_index = max(range(len(confs)), key=lambda idx: confs[idx])
    cls_id = cls_ids[best_index]
    return CLASS_NAMES[cls_id] if 0 <= cls_id < len(CLASS_NAMES) else str(cls_id)


def load_diagnostic_rows(dataset_root: Path) -> list[dict[str, object]]:
    manifest = read_csv(dataset_root / "meta" / "manifest.csv")
    rows: list[dict[str, object]] = []
    for row in manifest:
        if row.get("split") not in {"val", "test"}:
            continue
        classes = tuple(filter(None, row.get("class_names", "").split()))
        rows.append(
            {
                "split": row.get("split", ""),
                "image_rel": row.get("image", ""),
                "image_path": dataset_root / row.get("image", ""),
                "gt_classes": classes,
                "source_role": row.get("source_role", ""),
                "source_batch_id": row.get("source_batch_id", ""),
                "source_original_image": row.get("source_original_image", ""),
            }
        )
    return rows


def run_predictions(
    model: YOLO,
    image_paths: list[str],
    imgsz: int,
    conf: float,
    device: str,
) -> list[Any]:
    return list(
        model.predict(
            source=image_paths,
            imgsz=imgsz,
            conf=conf,
            device=device,
            batch=8,
            verbose=False,
            stream=True,
        )
    )


def run_diagnostic_predictions(
    model: YOLO,
    rows: list[dict[str, object]],
    imgsz: int,
    conf: float,
    device: str,
) -> tuple[dict[str, int], list[dict[str, object]]]:
    images = [str(row["image_path"]) for row in rows]
    predictions = run_predictions(model, images, imgsz, conf, device)
    issues = {
        "false_fallen_on_adl": 0,
        "kneeling_lying_confusion": 0,
        "predicted_none": 0,
    }
    details: list[dict[str, object]] = []
    for row, result in zip(rows, predictions):
        top_class = top_prediction(result)
        gt_set = set(row["gt_classes"])
        false_fallen = bool(gt_set & ADL_CLASSES) and "fallen" not in gt_set and top_class == "fallen"
        kl_confusion = bool(gt_set & HARD_KL_CLASSES) and top_class not in gt_set and top_class != "none"
        predicted_none = top_class == "none"
        if false_fallen:
            issues["false_fallen_on_adl"] += 1
        if kl_confusion:
            issues["kneeling_lying_confusion"] += 1
        if predicted_none:
            issues["predicted_none"] += 1
        details.append(
            {
                "split": row["split"],
                "image": row["image_rel"],
                "gt_classes": " ".join(row["gt_classes"]),
                "top_class": top_class,
                "false_fallen_on_adl": false_fallen,
                "kneeling_lying_confusion": kl_confusion,
                "predicted_none": predicted_none,
                "source_batch_id": row["source_batch_id"],
                "source_original_image": row["source_original_image"],
            }
        )
    return issues, details


def run_empty_holdout_audit(
    model: YOLO,
    manifest_path: Path,
    imgsz: int,
    conf: float,
    device: str,
) -> tuple[dict[str, int], list[dict[str, object]]]:
    rows = read_csv(manifest_path)
    image_paths = [str((manifest_path.parent.parent / row["image"]).resolve()) for row in rows]
    predictions = run_predictions(model, image_paths, imgsz, conf, device)
    false_positive_images = 0
    details: list[dict[str, object]] = []
    for row, result in zip(rows, predictions):
        boxes = result.boxes
        box_count = int(len(boxes)) if boxes is not None else 0
        if box_count > 0:
            false_positive_images += 1
        details.append(
            {
                "image": row["image"],
                "source_batch_id": row.get("source_batch_id", ""),
                "source_original_image": row.get("source_original_image", ""),
                "prediction_box_count": box_count,
                "top_class": top_prediction(result),
            }
        )
    summary = {
        "images": len(rows),
        "false_positive_images": false_positive_images,
    }
    return summary, details


def collect_test_images(dataset_root: Path) -> list[str]:
    test_dir = dataset_root / "images" / "test"
    return [str(path) for path in sorted(test_dir.glob("*")) if path.is_file()]


def eval_test_metrics(
    model_path: Path,
    data: Path,
    project: Path,
    name: str,
    device: str,
    imgsz: int,
    conf: float,
) -> dict[str, Any]:
    model = YOLO(str(model_path))
    metrics = model.val(
        data=str(data),
        split="test",
        imgsz=imgsz,
        device=device,
        project=str(project),
        name=name,
        exist_ok=True,
        workers=0,
        verbose=False,
        conf=conf,
    )
    return {
        "metrics/precision(B)": float(metrics.box.mp),
        "metrics/recall(B)": float(metrics.box.mr),
        "metrics/mAP50(B)": float(metrics.box.map50),
        "metrics/mAP50-95(B)": float(metrics.box.map),
        "fitness": float(metrics.fitness),
        "save_dir": str(metrics.save_dir),
    }


def main() -> int:
    args = parse_args()
    data = args.data.resolve()
    empty_holdout_manifest = args.empty_holdout_manifest.resolve()
    project = args.project.resolve()
    project.mkdir(parents=True, exist_ok=True)

    models = {args.baseline_name: args.baseline_model.resolve()}
    models.update(parse_candidates(args.candidate))
    thresholds = parse_thresholds(args.thresholds)
    for name, path in models.items():
        if not path.exists():
            raise SystemExit(f"missing model for {name}: {path}")

    dataset_root = detect_dataset_root(data)
    diagnostic_rows = load_diagnostic_rows(dataset_root)
    test_images = collect_test_images(dataset_root)
    baseline_name = args.baseline_name

    summary_rows: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    per_model_best: dict[str, dict[str, object]] = {}
    summary_csv = project / "threshold_sweep_summary.csv"
    details_csv = project / "threshold_sweep_details.csv"
    if summary_csv.exists():
        summary_rows = [
            {key: value for key, value in row.items()}
            for row in read_csv(summary_csv)
        ]
    if details_csv.exists():
        detail_rows = [
            {key: value for key, value in row.items()}
            for row in read_csv(details_csv)
        ]

    for model_name, model_path in models.items():
        model = YOLO(str(model_path))
        best_row: dict[str, object] | None = None
        for threshold in thresholds:
            existing_row = next(
                (
                    row for row in summary_rows
                    if str(row.get("model_name", "")) == model_name
                    and str(row.get("threshold", "")) == str(threshold)
                ),
                None,
            )
            if existing_row is not None:
                row = existing_row
                score = (
                    float(row["test_precision"]),
                    -int(row["empty_holdout_fp_images"]),
                    float(row["test_map50_95"]),
                )
                if best_row is None:
                    best_row = row
                else:
                    best_score = (
                        float(best_row["test_precision"]),
                        -int(best_row["empty_holdout_fp_images"]),
                        float(best_row["test_map50_95"]),
                    )
                    if score > best_score:
                        best_row = row
                continue

            metrics = eval_test_metrics(
                model_path=model_path,
                data=data,
                project=project / model_name,
                name=f"test_conf_{str(threshold).replace('.', '_')}",
                device=args.device,
                imgsz=args.imgsz,
                conf=threshold,
            )
            empty_summary, empty_details = run_empty_holdout_audit(
                model=model,
                manifest_path=empty_holdout_manifest,
                imgsz=args.imgsz,
                conf=threshold,
                device=args.device,
            )
            diag_summary, diag_details = run_diagnostic_predictions(
                model=model,
                rows=diagnostic_rows,
                imgsz=args.imgsz,
                conf=threshold,
                device=args.device,
            )

            row = {
                "model_name": model_name,
                "model_path": str(model_path),
                "threshold": threshold,
                "test_precision": metrics["metrics/precision(B)"],
                "test_recall": metrics["metrics/recall(B)"],
                "test_map50": metrics["metrics/mAP50(B)"],
                "test_map50_95": metrics["metrics/mAP50-95(B)"],
                "empty_holdout_fp_images": empty_summary["false_positive_images"],
                "false_fallen_on_adl": diag_summary["false_fallen_on_adl"],
                "kneeling_lying_confusion": diag_summary["kneeling_lying_confusion"],
                "diagnostic_predicted_none": diag_summary["predicted_none"],
                "test_image_count": len(test_images),
                "diagnostic_image_count": len(diagnostic_rows),
                "empty_holdout_image_count": empty_summary["images"],
                "save_dir": metrics["save_dir"],
            }
            summary_rows.append(row)
            if best_row is None:
                best_row = row
            else:
                best_score = (
                    float(best_row["test_precision"]),
                    -int(best_row["empty_holdout_fp_images"]),
                    float(best_row["test_map50_95"]),
                )
                new_score = (
                    float(row["test_precision"]),
                    -int(row["empty_holdout_fp_images"]),
                    float(row["test_map50_95"]),
                )
                if new_score > best_score:
                    best_row = row

            for detail in empty_details:
                payload = {
                    "model_name": model_name,
                    "threshold": threshold,
                    "detail_type": "empty_holdout",
                    **detail,
                }
                detail_rows.append(payload)
            for detail in diag_details:
                payload = {
                    "model_name": model_name,
                    "threshold": threshold,
                    "detail_type": "diagnostic",
                    **detail,
                }
                detail_rows.append(payload)
            persist_sweep_progress(
                summary_csv=summary_csv,
                details_csv=details_csv,
                summary_rows=summary_rows,
                detail_rows=detail_rows,
            )
        if best_row is not None:
            per_model_best[model_name] = best_row

    baseline_rows = [row for row in summary_rows if row["model_name"] == baseline_name]
    if not baseline_rows:
        raise SystemExit("baseline rows missing from threshold sweep")

    recommended_rows: list[dict[str, object]] = []
    for model_name, row in per_model_best.items():
        if model_name == baseline_name:
            continue
        accepted = False
        baseline_match = next(
            (
                base
                for base in baseline_rows
                if abs(float(base["threshold"]) - float(row["threshold"])) < 1e-9
            ),
            None,
        )
        if baseline_match is not None:
            accepted = (
                float(row["test_precision"]) >= float(baseline_match["test_precision"]) - 0.03
                and float(row["test_map50_95"]) >= float(baseline_match["test_map50_95"])
                and int(row["empty_holdout_fp_images"]) <= int(baseline_match["empty_holdout_fp_images"])
                and int(row["false_fallen_on_adl"]) <= int(baseline_match["false_fallen_on_adl"])
                and int(row["kneeling_lying_confusion"]) <= int(baseline_match["kneeling_lying_confusion"])
            )
        recommended_rows.append(
            {
                "model_name": model_name,
                "best_threshold": row["threshold"],
                "accepted_against_baseline_same_threshold": accepted,
                "test_precision": row["test_precision"],
                "test_map50_95": row["test_map50_95"],
                "empty_holdout_fp_images": row["empty_holdout_fp_images"],
                "false_fallen_on_adl": row["false_fallen_on_adl"],
                "kneeling_lying_confusion": row["kneeling_lying_confusion"],
            }
        )

    write_csv(summary_csv, summary_rows)
    write_csv(details_csv, detail_rows)
    write_csv(project / "threshold_sweep_recommendations.csv", recommended_rows)

    payload = {
        "data": str(data),
        "empty_holdout_manifest": str(empty_holdout_manifest),
        "baseline_name": baseline_name,
        "thresholds": thresholds,
        "models": {name: str(path) for name, path in models.items()},
        "per_model_best": per_model_best,
        "recommendations": recommended_rows,
    }
    (project / "threshold_sweep_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
