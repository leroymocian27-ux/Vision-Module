from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_THRESHOLD = 0.65


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate fall LSTM ONNX metrics for baseline/pose comparison.")
    parser.add_argument("--input", nargs="+", default=None, help="Temporal sequence JSONL files.")
    parser.add_argument("--input-manifest", default=None, help="JSON manifest containing input_files.")
    parser.add_argument("--model", required=True, help="ONNX LSTM model path.")
    parser.add_argument("--schema", required=True, help="Feature schema JSON used by the ONNX model.")
    parser.add_argument("--train-config", default=None, help="Optional train_config JSON for the evaluated ONNX model.")
    parser.add_argument("--output", required=True, help="Output metrics JSON.")
    parser.add_argument("--split", default="test", choices=("train", "val", "test", "all"))
    parser.add_argument("--stride", type=int, default=4)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--threshold-calibration", default=None, help="JSON containing fall_probability threshold.")
    parser.add_argument("--providers", default="CPUExecutionProvider")
    parser.add_argument(
        "--zero-pose-features",
        action="store_true",
        help="Ablate pose feature columns during evaluation. Use only for diagnostic ablations, not a formal trained baseline.",
    )
    args = parser.parse_args()

    threshold = selected_threshold(args.threshold, args.threshold_calibration)
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    input_paths = resolve_input_paths(args.input, args.input_manifest)
    windows = load_windows(
        input_paths,
        schema,
        stride=max(1, args.stride),
        split=args.split,
        seed=42,
        zero_pose_features=args.zero_pose_features,
    )
    if not windows:
        raise SystemExit(f"no {args.split} windows found for evaluation")
    probabilities = predict_onnx(Path(args.model), windows, providers=args.providers)
    report = build_report(
        probabilities=probabilities,
        windows=windows,
        model_path=Path(args.model),
        schema_path=Path(args.schema),
        train_config_path=Path(args.train_config) if args.train_config else None,
        input_paths=input_paths,
        input_manifest_path=Path(args.input_manifest) if args.input_manifest else None,
        split=args.split,
        stride=max(1, args.stride),
        threshold=threshold,
        zero_pose_features=args.zero_pose_features,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


def build_report(
    *,
    probabilities: np.ndarray,
    windows: list[dict[str, Any]],
    model_path: Path,
    schema_path: Path,
    train_config_path: Path | None,
    input_paths: list[Path],
    input_manifest_path: Path | None,
    split: str,
    stride: int,
    threshold: float,
    zero_pose_features: bool,
) -> dict[str, Any]:
    labels = np.asarray([item["label"] for item in windows], dtype=np.int32)
    subtypes = [str(item.get("non_fall_subtype") or "fall") for item in windows]
    selected = metrics_at_threshold(probabilities, labels, subtypes, threshold=threshold)
    sweep = threshold_sweep(probabilities, labels, subtypes)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": str(model_path),
        "schema": str(schema_path),
        "train_config": train_config_metadata(train_config_path),
        "input_files": [str(path) for path in input_paths],
        "input_manifest": manifest_metadata(input_manifest_path),
        "eval_config": {
            "split": split,
            "stride": stride,
            "threshold": threshold,
            "zero_pose_features": zero_pose_features,
        },
        "summary": {
            "sample_count": len(windows),
            "positive_samples": int(labels.sum()),
            "negative_samples": int(len(labels) - labels.sum()),
            "split_counts": dict(Counter(str(item.get("split")) for item in windows)),
            "subtype_counts": dict(Counter(subtypes)),
            "threshold": threshold,
            "precision": selected["precision"],
            "recall": selected["recall"],
            "f1": selected["f1"],
            "false_positive_count": selected["confusion"]["false_positive"],
        },
        "event_metrics": {
            "threshold": threshold,
            "fall_event_precision": selected["precision"],
            "fall_event_recall": selected["recall"],
            "fall_event_f1": selected["f1"],
            "false_positive_count": selected["confusion"]["false_positive"],
            "confusion": selected["confusion"],
            "subtype_false_positive_counts": selected["subtype_false_positive_counts"],
        },
        "threshold_sweep": sweep,
        "probability_summary": probability_summary(probabilities),
    }


def load_windows(
    paths: list[Path],
    schema: dict[str, Any],
    *,
    stride: int,
    split: str,
    seed: int,
    zero_pose_features: bool,
) -> list[dict[str, Any]]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("usable_for_training") is False:
                    continue
                validate_row(row, schema, path=path)
                by_key[str(row["sequence_key"])].append(row)
    assign_splits(by_key, seed=seed)
    windows: list[dict[str, Any]] = []
    window_size = int(schema["window_size"])
    for rows in by_key.values():
        rows.sort(key=lambda item: int(item["frame_seq"]))
        if len(rows) < window_size:
            continue
        row_split = rows[0].get("split", "train")
        if split != "all" and row_split != split:
            continue
        for start in range(0, len(rows) - window_size + 1, stride):
            window = rows[start : start + window_size]
            vectors = [list(item["vector"]) for item in window]
            if zero_pose_features:
                vectors = [zero_pose_vector(vector, schema) for vector in vectors]
            windows.append(
                {
                    "x": vectors,
                    "label": 1 if any(item.get("label") == "fall" for item in window) else 0,
                    "split": row_split,
                    "split_group": window[0].get("split_group") or window[0].get("sequence_key"),
                    "sequence_key": window[0].get("sequence_key"),
                    "non_fall_subtype": window[0].get("non_fall_subtype"),
                }
            )
    return windows


def validate_row(row: dict[str, Any], schema: dict[str, Any], *, path: Path) -> None:
    if row.get("schema_version") != schema.get("schema_version"):
        raise ValueError(f"schema_version mismatch in {path}: {row.get('schema_version')}")
    if row.get("schema_hash") != schema.get("schema_hash"):
        raise ValueError(f"schema_hash mismatch in {path}: {row.get('schema_hash')}")
    vector = row.get("vector")
    if not isinstance(vector, list) or len(vector) != int(schema.get("input_dim") or 0):
        raise ValueError(f"vector dim mismatch in {path}: {len(vector) if isinstance(vector, list) else 'missing'}")


def zero_pose_vector(vector: list[Any], schema: dict[str, Any]) -> list[float]:
    result = [float(item) for item in vector]
    feature_names = list(schema.get("feature_names") or [])
    fill = schema.get("missing_pose_fill") if isinstance(schema.get("missing_pose_fill"), dict) else {}
    for name in ("pose_available", "pose_confidence", "torso_angle_norm", "head_height_ratio_filled", "hip_height_ratio_filled"):
        if name in feature_names:
            index = feature_names.index(name)
            result[index] = float(fill.get(name, 0.0))
    return result


def assign_splits(by_key: dict[str, list[dict[str, Any]]], seed: int) -> None:
    grouped: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for key, rows in by_key.items():
        if not rows:
            continue
        group = rows[0].get("split_group") or key
        grouped[str(group)].append(rows)
    groups = sorted(grouped)
    random.Random(seed).shuffle(groups)
    total = len(groups)
    train_cut = max(1, math.ceil(total * 0.7))
    val_cut = max(train_cut, math.ceil(total * 0.85))
    split_by_group = {}
    for index, group in enumerate(groups):
        if index < train_cut:
            split = "train"
        elif index < val_cut:
            split = "val"
        else:
            split = "test"
        split_by_group[group] = split
    for group, row_sets in grouped.items():
        for rows in row_sets:
            for row in rows:
                if row.get("split") in {None, "", "unassigned"}:
                    row["split"] = split_by_group[group]


def predict_onnx(model_path: Path, windows: list[dict[str, Any]], *, providers: str) -> np.ndarray:
    import onnxruntime as ort  # type: ignore

    requested = [item.strip() for item in providers.split(",") if item.strip()]
    session = ort.InferenceSession(str(model_path), providers=requested or ["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    x = np.asarray([item["x"] for item in windows], dtype=np.float32)
    outputs = session.run(None, {input_name: x})
    return decode_probabilities(outputs)


def decode_probabilities(outputs: list[Any]) -> np.ndarray:
    if not outputs:
        raise ValueError("ONNX model returned no outputs")
    first = np.asarray(outputs[0], dtype=np.float32)
    if first.ndim == 0:
        first = first.reshape(1)
    if first.shape[-1:] == (1,):
        values = first.reshape(-1)
        if np.all((0.0 <= values) & (values <= 1.0)):
            return values.astype(np.float32)
        return (1.0 / (1.0 + np.exp(-values))).astype(np.float32)
    if first.ndim >= 2 and first.shape[-1] >= 2:
        flat = first.reshape(-1, first.shape[-1])
        shifted = flat - np.max(flat, axis=1, keepdims=True)
        probs = np.exp(shifted) / np.sum(np.exp(shifted), axis=1, keepdims=True)
        return probs[:, 1].astype(np.float32)
    values = first.reshape(-1)
    return np.clip(values, 0.0, 1.0).astype(np.float32)


def metrics_at_threshold(
    probabilities: np.ndarray,
    labels: np.ndarray,
    subtypes: list[str],
    *,
    threshold: float,
) -> dict[str, Any]:
    pred = probabilities >= threshold
    tp = int(np.sum((pred == 1) & (labels == 1)))
    fp = int(np.sum((pred == 1) & (labels == 0)))
    tn = int(np.sum((pred == 0) & (labels == 0)))
    fn = int(np.sum((pred == 0) & (labels == 1)))
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = safe_div(2 * precision * recall, precision + recall) if precision + recall else 0.0
    subtype_fp = Counter(subtypes[i] for i, value in enumerate(pred) if value and labels[i] == 0)
    return {
        "threshold": threshold,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "confusion": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
        },
        "subtype_false_positive_counts": dict(subtype_fp),
    }


def threshold_sweep(probabilities: np.ndarray, labels: np.ndarray, subtypes: list[str]) -> list[dict[str, Any]]:
    return [
        metrics_at_threshold(probabilities, labels, subtypes, threshold=round(float(threshold), 2))
        for threshold in np.arange(0.30, 0.851, 0.05)
    ]


def probability_summary(probabilities: np.ndarray) -> dict[str, float | None]:
    if probabilities.size == 0:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": round(float(np.min(probabilities)), 6),
        "max": round(float(np.max(probabilities)), 6),
        "mean": round(float(np.mean(probabilities)), 6),
    }


def selected_threshold(threshold: float | None, calibration_path: str | None) -> float:
    if threshold is not None:
        return float(threshold)
    if calibration_path:
        payload = json.loads(Path(calibration_path).read_text(encoding="utf-8"))
        value = payload.get("fall_probability")
        if value is None:
            raise SystemExit(f"threshold calibration missing fall_probability: {calibration_path}")
        return float(value)
    return DEFAULT_THRESHOLD


def resolve_input_paths(input_args: list[str] | None, input_manifest: str | None) -> list[Path]:
    paths: list[Path] = []
    if input_args:
        paths.extend(Path(item) for item in input_args)
    if input_manifest:
        manifest_path = Path(input_manifest)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw_inputs = payload.get("input_files")
        if not isinstance(raw_inputs, list):
            raise SystemExit("input manifest must contain input_files list")
        for item in raw_inputs:
            path = Path(str(item))
            if not path.is_absolute():
                path = ROOT / path
            paths.append(path)
    if not paths:
        raise SystemExit("at least one --input file or --input-manifest is required")
    return paths


def manifest_metadata(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path if path.is_absolute() else ROOT / path
    return {
        "path": str(path),
        "sha256": sha256_file(resolved),
    }


def train_config_metadata(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path if path.is_absolute() else ROOT / path
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "sha256": sha256_file(resolved),
        "input_manifest": payload.get("input_manifest"),
        "input_manifest_sha256": payload.get("input_manifest_sha256")
        or nested_input_manifest_sha256(payload.get("input_manifest_metadata")),
        "input_count": payload.get("input_count"),
    }


def nested_input_manifest_sha256(value: Any) -> str | None:
    if isinstance(value, dict):
        sha256 = value.get("sha256")
        return str(sha256) if sha256 else None
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


if __name__ == "__main__":
    raise SystemExit(main())
