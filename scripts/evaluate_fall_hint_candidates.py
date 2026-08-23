from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "datasets" / "fall_hint_v2_finetune_seed_7_3testmodel_v1" / "data.yaml"
DEFAULT_EMPTY_HOLDOUT = ROOT / "datasets" / "fall_hint_v2_finetune_seed_7_3testmodel_v1" / "meta" / "empty_holdout_manifest.csv"
DEFAULT_BASELINE = ROOT / "models" / "yolo_fall_hint_v2_plus_b012_best.pt"
DEFAULT_PROJECT = ROOT / "runs" / "fall_hint_seed_finetune_20260703" / "eval_acceptance"
CLASS_NAMES = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
ADL_CLASSES = {"sitting", "kneeling", "lying"}
HARD_KL_CLASSES = {"kneeling", "lying"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Fall Hint finetune candidates against the runtime baseline.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--empty-holdout-manifest", type=Path, default=DEFAULT_EMPTY_HOLDOUT)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--device", default="0")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
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


def parse_candidates(raw_candidates: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for raw in raw_candidates:
        if "=" not in raw:
            raise SystemExit(f"candidate must be name=path, got: {raw}")
        name, model = raw.split("=", 1)
        parsed[name.strip()] = Path(model.strip()).resolve()
    return parsed


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


def eval_split(model_path: Path, data: Path, split: str, project: Path, name: str, device: str, imgsz: int) -> dict[str, Any]:
    model = YOLO(str(model_path))
    metrics = model.val(
        data=str(data),
        split=split,
        imgsz=imgsz,
        device=device,
        project=str(project),
        name=name,
        exist_ok=True,
        workers=0,
        verbose=True,
    )
    return {
        "model": str(model_path),
        "data": str(data),
        "split": split,
        "save_dir": str(metrics.save_dir),
        "metrics/precision(B)": float(metrics.box.mp),
        "metrics/recall(B)": float(metrics.box.mr),
        "metrics/mAP50(B)": float(metrics.box.map50),
        "metrics/mAP50-95(B)": float(metrics.box.map),
        "fitness": float(metrics.fitness),
    }


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


def run_diagnostic_predictions(
    model_path: Path,
    rows: list[dict[str, object]],
    imgsz: int,
    conf: float,
    device: str,
) -> tuple[dict[str, int], list[dict[str, object]]]:
    model = YOLO(str(model_path))
    images = [str(row["image_path"]) for row in rows]
    predictions = model.predict(
        source=images,
        imgsz=imgsz,
        conf=conf,
        device=device,
        batch=8,
        verbose=False,
        stream=True,
    )
    issues = {
        "false_fallen_on_adl": 0,
        "kneeling_lying_confusion": 0,
    }
    details: list[dict[str, object]] = []
    for row, result in zip(rows, predictions):
        top_class = top_prediction(result)
        gt_set = set(row["gt_classes"])
        false_fallen = bool(gt_set & ADL_CLASSES) and "fallen" not in gt_set and top_class == "fallen"
        kl_confusion = bool(gt_set & HARD_KL_CLASSES) and top_class not in gt_set
        if false_fallen:
            issues["false_fallen_on_adl"] += 1
        if kl_confusion:
            issues["kneeling_lying_confusion"] += 1
        details.append(
            {
                "split": row["split"],
                "image": row["image_rel"],
                "gt_classes": " ".join(row["gt_classes"]),
                "top_class": top_class,
                "false_fallen_on_adl": false_fallen,
                "kneeling_lying_confusion": kl_confusion,
                "source_batch_id": row["source_batch_id"],
                "source_original_image": row["source_original_image"],
            }
        )
    return issues, details


def run_empty_holdout_audit(
    model_path: Path,
    manifest_path: Path,
    imgsz: int,
    conf: float,
    device: str,
) -> tuple[dict[str, int], list[dict[str, object]]]:
    rows = read_csv(manifest_path)
    model = YOLO(str(model_path))
    image_paths = [str((manifest_path.parent.parent / row["image"]).resolve()) for row in rows]
    predictions = model.predict(
        source=image_paths,
        imgsz=imgsz,
        conf=conf,
        device=device,
        batch=8,
        verbose=False,
        stream=True,
    )
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


def main() -> int:
    args = parse_args()
    data = args.data.resolve()
    empty_holdout_manifest = args.empty_holdout_manifest.resolve()
    project = args.project.resolve()
    project.mkdir(parents=True, exist_ok=True)

    models = {args.baseline_name: args.baseline_model.resolve()}
    models.update(parse_candidates(args.candidate))
    for name, path in models.items():
        if not path.exists():
            raise SystemExit(f"missing model for {name}: {path}")

    dataset_root = detect_dataset_root(data)
    diagnostic_rows = load_diagnostic_rows(dataset_root)
    eval_summary: dict[str, Any] = {}
    bucket_rows: dict[str, list[dict[str, object]]] = {}

    for name, model_path in models.items():
        eval_summary[name] = {
            "val": eval_split(model_path, data, "val", project, f"{name}_val", args.device, args.imgsz),
            "test": eval_split(model_path, data, "test", project, f"{name}_test", args.device, args.imgsz),
        }
        empty_summary, empty_details = run_empty_holdout_audit(
            model_path, empty_holdout_manifest, args.imgsz, args.conf, args.device
        )
        diag_summary, diag_details = run_diagnostic_predictions(
            model_path, diagnostic_rows, args.imgsz, args.conf, args.device
        )
        eval_summary[name]["empty_holdout"] = empty_summary
        eval_summary[name]["diagnostic"] = diag_summary
        bucket_rows[f"{name}_empty_holdout"] = empty_details
        bucket_rows[f"{name}_diagnostic"] = diag_details

    baseline = eval_summary[args.baseline_name]
    decisions: dict[str, Any] = {}
    accepted_candidates: list[str] = []
    for name, metrics in eval_summary.items():
        if name == args.baseline_name:
            continue
        test_pass = (
            metrics["test"]["metrics/mAP50-95(B)"] >= baseline["test"]["metrics/mAP50-95(B)"]
            and metrics["test"]["metrics/precision(B)"] >= baseline["test"]["metrics/precision(B)"] - 0.03
        )
        empty_pass = (
            metrics["empty_holdout"]["false_positive_images"]
            <= baseline["empty_holdout"]["false_positive_images"]
        )
        bucket_improvements = {
            "false_fallen_on_adl": metrics["diagnostic"]["false_fallen_on_adl"]
            < baseline["diagnostic"]["false_fallen_on_adl"],
            "false_positive_on_empty": metrics["empty_holdout"]["false_positive_images"]
            < baseline["empty_holdout"]["false_positive_images"],
            "kneeling_lying_confusion": metrics["diagnostic"]["kneeling_lying_confusion"]
            < baseline["diagnostic"]["kneeling_lying_confusion"],
        }
        improved_bucket_count = sum(1 for value in bucket_improvements.values() if value)
        accepted = test_pass and empty_pass and improved_bucket_count >= 2
        decisions[name] = {
            "test_gate_pass": test_pass,
            "empty_holdout_gate_pass": empty_pass,
            "bucket_improvements": bucket_improvements,
            "improved_bucket_count": improved_bucket_count,
            "accepted_for_runtime_replacement": accepted,
        }
        if accepted:
            accepted_candidates.append(name)

    decision_payload = {
        "baseline_name": args.baseline_name,
        "baseline_model": str(models[args.baseline_name]),
        "data": str(data),
        "empty_holdout_manifest": str(empty_holdout_manifest),
        "summary": eval_summary,
        "decisions": decisions,
        "accepted_candidates": accepted_candidates,
        "recommended_candidate": accepted_candidates[0] if accepted_candidates else "",
        "rejected_for_runtime_replacement": len(accepted_candidates) == 0,
    }

    (project / "eval_summary.json").write_text(
        json.dumps(eval_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (project / "acceptance_decision.json").write_text(
        json.dumps(decision_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for name, rows in bucket_rows.items():
        write_csv(project / f"{name}.csv", rows)
    print(json.dumps(decision_payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
