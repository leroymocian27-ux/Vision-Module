from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}
FALL_CLASS_ALIASES = {"fall", "fallen", "risk", "fall_risk", "suspected_fall"}
NON_FALL_CLASS_ALIASES = {"non_fall", "non-fall", "normal", "safe"}


@dataclass(frozen=True)
class BinaryFallResult:
    frame_id: str
    camera_id: str | None
    timestamp: str | None
    prediction: str
    fall_probability: float | None
    class_index: int | None
    model_name: str
    model_version: str | None
    model_hash: str
    inference_ms: float | None
    input_width: int | None
    input_height: int | None
    valid: bool
    error_code: str | None
    source: str
    model: str
    input_shape: list[int] | None
    preprocessing_summary: dict[str, Any]
    raw_output_summary: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_sources(*, image: Path | None, directory: Path | None) -> list[Path]:
    if image is None and directory is None:
        raise ValueError("Provide --image or --directory.")
    if image is not None and directory is not None:
        raise ValueError("Provide only one of --image or --directory.")
    if image is not None:
        resolved = image.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Image not found: {resolved}")
        if resolved.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image extension: {resolved.suffix}")
        return [resolved]

    assert directory is not None
    resolved_dir = directory.expanduser().resolve()
    if not resolved_dir.is_dir():
        raise FileNotFoundError(f"Directory not found: {resolved_dir}")
    sources = sorted(path for path in resolved_dir.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
    if not sources:
        raise ValueError(f"No supported images found under: {resolved_dir}")
    return sources


def infer_label_from_path(path: Path) -> str | None:
    parts = [part.lower() for part in path.parts]
    for label in sorted(FALL_CLASS_ALIASES | NON_FALL_CLASS_ALIASES):
        if label.lower() in parts:
            return label
    return None


def normalize_names(names: Any) -> dict[int, str]:
    if isinstance(names, dict):
        return {int(key): str(value) for key, value in names.items()}
    if isinstance(names, (list, tuple)):
        return {index: str(value) for index, value in enumerate(names)}
    return {}


def class_mapping(names: dict[int, str]) -> dict[str, Any]:
    normalized = {index: label.strip().lower() for index, label in names.items()}
    fall_indexes = [index for index, label in normalized.items() if label in FALL_CLASS_ALIASES]
    non_fall_indexes = [index for index, label in normalized.items() if label in NON_FALL_CLASS_ALIASES]
    return {
        "names": names,
        "fall_class_index": fall_indexes[0] if len(fall_indexes) == 1 else None,
        "non_fall_class_index": non_fall_indexes[0] if len(non_fall_indexes) == 1 else None,
        "fall_class_candidates": fall_indexes,
        "non_fall_class_candidates": non_fall_indexes,
        "mapping_status": "confirmed_from_model_names" if len(fall_indexes) == 1 and len(non_fall_indexes) == 1 else "needs_verification",
    }


def build_preprocessing_summary(model: Any, imgsz: int | None) -> dict[str, Any]:
    transforms = getattr(getattr(model, "model", None), "transforms", None)
    transform_items: list[dict[str, Any]] = []
    if transforms is not None and hasattr(transforms, "transforms"):
        for item in transforms.transforms:
            data: dict[str, Any] = {"type": item.__class__.__name__}
            for attr in ("size", "interpolation", "antialias", "mean", "std"):
                if hasattr(item, attr):
                    data[attr] = _json_safe(getattr(item, attr))
            transform_items.append(data)

    return {
        "api": "ultralytics.YOLO.predict",
        "input_color_boundary": "OpenCV BGR source is converted to PIL/RGB inside ClassificationPredictor.preprocess",
        "input_dtype_before_transforms": "uint8 image file decoded by Ultralytics loader",
        "tensor_dtype": "float32 on CPU unless fp16 is enabled by backend",
        "layout": "HWC image -> CHW tensor with batch dimension",
        "imgsz": imgsz,
        "dynamic_input": False if imgsz else None,
        "resize_policy": "torchvision Resize(size=imgsz) preserves aspect ratio by shorter edge",
        "crop_policy": "torchvision CenterCrop(imgsz,imgsz)",
        "letterbox": False,
        "interpolation": "bilinear",
        "scale": "ToTensor scales uint8 values to [0,1]",
        "mean": [0.0, 0.0, 0.0],
        "std": [1.0, 1.0, 1.0],
        "transforms": transform_items,
        "evidence": [
            "model.model.transforms",
            "ultralytics.models.yolo.classify.predict.ClassificationPredictor.preprocess",
            "ultralytics.data.augment.classify_transforms",
        ],
    }


def load_model(model_path: Path) -> Any:
    try:
        from ultralytics import YOLO
    except Exception as exc:  # pragma: no cover - environment-specific
        raise RuntimeError("ultralytics is not importable") from exc
    return YOLO(str(model_path))


def inspect_model(model_path: Path, model: Any, model_hash: str) -> dict[str, Any]:
    names = normalize_names(getattr(model, "names", None))
    model_args = getattr(getattr(model, "model", None), "args", {}) or {}
    overrides = getattr(model, "overrides", {}) or {}
    imgsz = _coerce_int(overrides.get("imgsz") or model_args.get("imgsz"))
    return {
        "model_path": str(model_path),
        "model_hash": model_hash,
        "framework": "ultralytics",
        "model_type": getattr(getattr(model, "model", None), "__class__", type(None)).__name__,
        "task": getattr(model, "task", None),
        "names": names,
        "class_mapping": class_mapping(names),
        "imgsz": imgsz,
        "overrides": _json_safe(overrides),
        "model_args": _json_safe(model_args),
        "preprocessing_summary": build_preprocessing_summary(model, imgsz),
    }


def run_inference(model: Any, source: Path, *, model_path: Path, model_hash: str, device: str) -> BinaryFallResult:
    names = normalize_names(getattr(model, "names", None))
    mapping = class_mapping(names)
    model_args = getattr(getattr(model, "model", None), "args", {}) or {}
    overrides = getattr(model, "overrides", {}) or {}
    imgsz = _coerce_int(overrides.get("imgsz") or model_args.get("imgsz"))

    started = time.perf_counter()
    predict_kwargs: dict[str, Any] = {"verbose": False, "device": device}
    if imgsz:
        predict_kwargs["imgsz"] = imgsz
    result = model.predict(str(source), **predict_kwargs)[0]
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    probs = getattr(result, "probs", None)
    vector = _tensor_to_list(getattr(probs, "data", None))
    top1 = _coerce_int(getattr(probs, "top1", None))
    top1conf = _coerce_float(getattr(probs, "top1conf", None))
    fall_index = mapping["fall_class_index"]
    fall_probability = _coerce_float(vector[fall_index]) if fall_index is not None and 0 <= fall_index < len(vector) else None
    predicted_name = names.get(top1, str(top1)) if top1 is not None else "unknown"
    orig_shape = list(getattr(result, "orig_shape", []) or [])
    input_height = int(orig_shape[0]) if len(orig_shape) >= 1 else None
    input_width = int(orig_shape[1]) if len(orig_shape) >= 2 else None
    valid = bool(vector) and all(_is_probability(value) for value in vector)

    raw_output_summary = {
        "available_output": "ultralytics Results.probs",
        "probabilities": vector,
        "top1": top1,
        "top1conf": top1conf,
        "top5": _json_safe(getattr(probs, "top5", None)),
        "top5conf": _tensor_to_list(getattr(probs, "top5conf", None)),
        "names": names,
        "fall_class_index": fall_index,
        "non_fall_class_index": mapping["non_fall_class_index"],
        "probability_sum": round(sum(vector), 8) if vector else None,
        "speed": _json_safe(getattr(result, "speed", None)),
    }

    return BinaryFallResult(
        frame_id=source.stem,
        camera_id=None,
        timestamp=None,
        prediction=str(predicted_name),
        fall_probability=fall_probability,
        class_index=top1,
        model_name=model_path.name,
        model_version=None,
        model_hash=model_hash,
        inference_ms=round(elapsed_ms, 3),
        input_width=input_width,
        input_height=input_height,
        valid=valid,
        error_code=None if valid else "INVALID_PROBABILITY_VECTOR",
        source=str(source),
        model=str(model_path),
        input_shape=orig_shape,
        preprocessing_summary=build_preprocessing_summary(model, imgsz),
        raw_output_summary=raw_output_summary,
    )


def threshold_sweep(records: list[dict[str, Any]], thresholds: Iterable[float]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    usable = [row for row in records if row.get("label") in FALL_CLASS_ALIASES | NON_FALL_CLASS_ALIASES and row.get("fall_probability") is not None]
    for threshold in thresholds:
        tp = fp = tn = fn = 0
        for row in usable:
            expected_fall = str(row["label"]).lower() in FALL_CLASS_ALIASES
            predicted_fall = float(row["fall_probability"]) >= threshold
            if predicted_fall and expected_fall:
                tp += 1
            elif predicted_fall and not expected_fall:
                fp += 1
            elif not predicted_fall and not expected_fall:
                tn += 1
            else:
                fn += 1
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        specificity = tn / (tn + fp) if tn + fp else 0.0
        fpr = fp / (fp + tn) if fp + tn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append(
            {
                "threshold": round(float(threshold), 4),
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "precision": round(precision, 6),
                "recall": round(recall, 6),
                "f1": round(f1, 6),
                "specificity": round(specificity, 6),
                "false_positive_rate": round(fpr, 6),
            }
        )
    return rows


def operating_points(sweep: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    if not sweep:
        return {"best_f1": None, "high_recall": None, "balanced_precision_recall": None}
    best_f1 = max(sweep, key=lambda row: (row["f1"], row["recall"], -row["threshold"]))
    high_recall_candidates = [row for row in sweep if row["recall"] >= 0.95] or sweep
    high_recall = max(high_recall_candidates, key=lambda row: (row["precision"], row["recall"], -row["threshold"]))
    balanced = min(sweep, key=lambda row: (abs(row["precision"] - row["recall"]), -row["f1"]))
    return {"best_f1": best_f1, "high_recall": high_recall, "balanced_precision_recall": balanced}


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    probs = [float(row["fall_probability"]) for row in records if row.get("fall_probability") is not None]
    labels: dict[str, int] = {}
    predictions: dict[str, int] = {}
    for row in records:
        label = row.get("label")
        if label:
            labels[str(label)] = labels.get(str(label), 0) + 1
        pred = row.get("prediction")
        if pred:
            predictions[str(pred)] = predictions.get(str(pred), 0) + 1
    return {
        "count": len(records),
        "labels": labels,
        "predictions": predictions,
        "fall_probability_min": round(min(probs), 6) if probs else None,
        "fall_probability_max": round(max(probs), 6) if probs else None,
        "fall_probability_mean": round(statistics.fmean(probs), 6) if probs else None,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the post-fall binary classifier contract without Runtime integration.")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--save-json", type=Path)
    parser.add_argument("--save-csv", type=Path)
    parser.add_argument("--max-samples", type=int, default=0)
    args = parser.parse_args(argv)

    model_path = args.model.expanduser().resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"Model not found: {model_path}")
    sources = collect_sources(image=args.image, directory=args.directory)
    if args.max_samples > 0:
        sources = sources[: args.max_samples]

    model_hash = sha256_file(model_path)
    model = load_model(model_path)
    model_info = inspect_model(model_path, model, model_hash)
    records = []
    for source in sources:
        result = asdict(run_inference(model, source, model_path=model_path, model_hash=model_hash, device=args.device))
        result["label"] = infer_label_from_path(source)
        records.append(result)

    thresholds = [round(i / 100.0, 2) for i in range(5, 100, 5)]
    sweep = threshold_sweep(records, thresholds)
    payload = {
        "schema_version": "post_fall_binary_contract_verification.v1",
        "model": model_info,
        "device": args.device,
        "sources": [str(source) for source in sources],
        "summary": summarize_records(records),
        "records": records,
        "threshold_sweep": sweep,
        "operating_points": operating_points(sweep),
        "gate": "POST_FALL_V2_BINARY_CONTRACT_BLOCKED",
        "gate_reasons": [
            "Threshold evidence is not repo-controlled unless the external training dataset/artifacts are promoted into the project.",
            "The class mapping is risk/safe; risk is usable as a candidate fall-risk score but is not by itself a final fall incident verdict.",
        ],
    }

    if args.save_json:
        write_json(args.save_json.expanduser().resolve(), payload)
    if args.save_csv:
        write_csv(args.save_csv.expanduser().resolve(), records)
    print(json.dumps(payload if len(records) <= 10 else {k: v for k, v in payload.items() if k != "records"}, ensure_ascii=False, indent=2))
    return 0


def _tensor_to_list(value: Any) -> list[float]:
    if value is None:
        return []
    if hasattr(value, "detach"):
        value = value.detach().cpu().tolist()
    elif hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list):
        value = [value]
    return [float(item) for item in value]


def _json_safe(value: Any) -> Any:
    if hasattr(value, "detach"):
        value = value.detach().cpu().tolist()
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _is_probability(value: float) -> bool:
    return math.isfinite(float(value)) and 0.0 <= float(value) <= 1.0


if __name__ == "__main__":
    raise SystemExit(main())
