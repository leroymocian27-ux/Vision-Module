from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Train and export the Phase 6 fall LSTM ONNX model.")
    parser.add_argument("--input", nargs="+", default=None, help="Frame-level JSONL files from export_temporal_sequences.")
    parser.add_argument("--input-manifest", default=None, help="JSON manifest containing an input_files list.")
    parser.add_argument("--output-dir", default="models")
    parser.add_argument("--model-version", default="", help="Optional suffix such as v2; keeps artifacts versioned.")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--stride", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--max-unknown-adl-ratio",
        type=float,
        default=0.2,
        help="Reject training when unknown_adl dominates non-fall training windows.",
    )
    args = parser.parse_args()
    ensure_onnx_export_dependencies()

    import numpy as np
    from torch.utils.data import DataLoader, TensorDataset

    from app.temporal.feature_vectorizer import FeatureVectorizer

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    vectorizer = FeatureVectorizer()
    schema = vectorizer.schema().model_dump()
    input_paths = resolve_input_paths(args.input, args.input_manifest)
    input_manifest_metadata = manifest_metadata(Path(args.input_manifest)) if args.input_manifest else None
    windows = load_windows(input_paths, schema, stride=max(1, args.stride), seed=args.seed)
    samples = [item["features"] for item in windows if item["split"] == "train"]
    labels = [item["label"] for item in windows if item["split"] == "train"]
    if not samples:
        raise SystemExit("no training windows found")
    validate_training_windows(windows, max_unknown_adl_ratio=args.max_unknown_adl_ratio)

    x = torch.tensor(np.asarray(samples, dtype=np.float32))
    y = torch.tensor(np.asarray(labels, dtype=np.float32)).reshape(-1, 1)
    dataset = TensorDataset(x, y)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True)
    model = FallLSTM(input_dim=schema["input_dim"])
    pos = float(y.sum().item())
    neg = float(len(y) - pos)
    pos_weight = torch.tensor([max(1.0, neg / max(pos, 1.0))])
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)

    model.train()
    last_loss = 0.0
    for _ in range(args.epochs):
        total = 0.0
        count = 0
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            logits = model(batch_x)
            loss = criterion(logits, batch_y)
            loss.backward()
            optimizer.step()
            total += float(loss.item()) * len(batch_x)
            count += len(batch_x)
        last_loss = total / max(count, 1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{args.model_version}" if args.model_version else ""
    onnx_path = output_dir / f"fall_lstm{suffix}.onnx"
    schema_path = output_dir / f"fall_lstm{suffix}_features.json"
    metrics_path = output_dir / f"fall_lstm{suffix}_metrics.json"
    train_config_path = output_dir / f"fall_lstm{suffix}_train_config.json" if suffix else output_dir / "train_config.json"
    threshold_path = (
        output_dir / f"fall_lstm{suffix}_threshold_calibration.json"
        if suffix
        else output_dir / "threshold_calibration.json"
    )

    model.eval()
    export_model = FallProbabilityWrapper(model).eval()
    dummy = torch.zeros(1, schema["window_size"], schema["input_dim"], dtype=torch.float32)
    export_kwargs = {
        "input_names": ["input"],
        "output_names": ["fall_probability"],
        "dynamic_axes": {"input": {0: "batch"}, "fall_probability": {0: "batch"}},
        "opset_version": 17,
    }
    try:
        torch.onnx.export(export_model, dummy, str(onnx_path), dynamo=False, **export_kwargs)
    except TypeError:
        torch.onnx.export(export_model, dummy, str(onnx_path), **export_kwargs)
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    validation = validate_onnx(model, dummy, onnx_path)
    threshold_calibration = calibrate_threshold(model, windows)
    metrics = {
        "samples": len(samples),
        "positive_samples": int(sum(labels)),
        "negative_samples": int(len(labels) - sum(labels)),
        "all_window_count": len(windows),
        "split_counts": split_counts(windows),
        "subtype_counts": subtype_counts(windows),
        "last_loss": round(last_loss, 6),
        "onnx_validation": validation,
        "threshold_calibration": threshold_calibration,
        "trained_from_inputs": [str(Path(path).resolve()) for path in input_paths],
        "input_manifest": input_manifest_metadata,
    }
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    train_config_path.write_text(
        json.dumps(
            {
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "learning_rate": args.learning_rate,
                "stride": args.stride,
                "seed": args.seed,
                "input_manifest": args.input_manifest,
                "input_manifest_sha256": input_manifest_metadata.get("sha256") if input_manifest_metadata else None,
                "input_manifest_metadata": input_manifest_metadata,
                "input_count": len(input_paths),
                "input_file_sha256s": input_file_sha256s(input_paths),
                "model": {"input_dim": schema["input_dim"], "hidden_dim": 64, "layers": 1},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    threshold_path.write_text(json.dumps(threshold_calibration, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"onnx": str(onnx_path), "metrics": metrics}, ensure_ascii=False, indent=2))
    return 0


class FallLSTM(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int = 64) -> None:
        super().__init__()
        self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_dim, num_layers=1, batch_first=True)
        self.dropout = nn.Dropout(0.2)
        self.fall_head = nn.Linear(hidden_dim, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        last = self.dropout(out[:, -1, :])
        return self.fall_head(last)


class FallProbabilityWrapper(nn.Module):
    def __init__(self, model: FallLSTM) -> None:
        super().__init__()
        self.model = model

    def forward(self, x):
        return torch.sigmoid(self.model(x))


def load_windows(paths: list[str], schema: dict, stride: int, seed: int) -> list[dict]:
    by_key = defaultdict(list)
    for path in paths:
        with Path(path).open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("usable_for_training") is False:
                    continue
                validate_row(row, schema)
                by_key[row["sequence_key"]].append(row)

    assign_splits(by_key, seed=seed)
    windows = []
    window_size = int(schema["window_size"])
    for rows in by_key.values():
        rows.sort(key=lambda item: int(item["frame_seq"]))
        if len(rows) < window_size:
            continue
        for start in range(0, len(rows) - window_size + 1, stride):
            window = rows[start : start + window_size]
            split = window[0].get("split", "train")
            subtype = window[0].get("non_fall_subtype")
            windows.append(
                {
                    "features": [item["vector"] for item in window],
                    "label": 1 if any(item.get("label") == "fall" for item in window) else 0,
                    "split": split,
                    "split_group": window[0].get("split_group") or window[0].get("sequence_key"),
                    "non_fall_subtype": subtype,
                }
            )
    return windows


def resolve_input_paths(input_args: list[str] | None, input_manifest: str | None) -> list[str]:
    paths: list[str] = []
    if input_args:
        paths.extend(input_args)
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
            paths.append(str(path))
    if not paths:
        raise SystemExit("at least one --input file or --input-manifest is required")
    return paths


def manifest_metadata(path: Path) -> dict:
    resolved = path if path.is_absolute() else ROOT / path
    return {
        "path": str(path),
        "sha256": sha256_file(resolved),
    }


def input_file_sha256s(paths: list[str]) -> dict[str, str]:
    return {str(Path(path).resolve()): sha256_file(Path(path)) for path in paths}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assign_splits(by_key: dict, seed: int) -> None:
    grouped = defaultdict(list)
    for key, rows in by_key.items():
        group = rows[0].get("split_group") or key
        grouped[group].append(rows)
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


def validate_row(row: dict, schema: dict) -> None:
    if row.get("schema_version") != schema["schema_version"]:
        raise ValueError(f"schema_version mismatch in row {row.get('frame_seq')}")
    if row.get("schema_hash") != schema["schema_hash"]:
        raise ValueError(f"schema_hash mismatch in row {row.get('frame_seq')}")
    vector = row.get("vector")
    if not isinstance(vector, list) or len(vector) != schema["input_dim"]:
        raise ValueError(f"vector dim mismatch in row {row.get('frame_seq')}")


def validate_training_windows(windows: list[dict], *, max_unknown_adl_ratio: float) -> None:
    train = [item for item in windows if item["split"] == "train"]
    if not train:
        raise SystemExit("no train split windows found")
    positive = sum(1 for item in train if item["label"] == 1)
    negative = len(train) - positive
    if positive == 0 or negative == 0:
        raise SystemExit(
            f"training requires both fall and non_fall windows; got positive={positive}, negative={negative}"
        )

    by_group: dict[str, set[str]] = defaultdict(set)
    for item in windows:
        by_group[item["split_group"]].add(item["split"])
    leaked = {group: sorted(splits) for group, splits in by_group.items() if len(splits) > 1}
    if leaked:
        raise SystemExit(f"split_group leakage detected: {leaked}")

    non_fall = [item for item in train if item["label"] == 0]
    unknown = sum(1 for item in non_fall if item.get("non_fall_subtype") == "unknown_adl")
    unknown_ratio = unknown / len(non_fall) if non_fall else 0.0
    if unknown_ratio >= max_unknown_adl_ratio:
        raise SystemExit(
            f"unknown_adl ratio too high in non-fall train windows: "
            f"{unknown_ratio:.4f} >= {max_unknown_adl_ratio:.4f}"
        )


def split_counts(windows: list[dict]) -> dict:
    counts = Counter(item["split"] for item in windows)
    return dict(counts)


def subtype_counts(windows: list[dict]) -> dict:
    counts = Counter(item.get("non_fall_subtype") or "fall" for item in windows)
    return dict(counts)


def calibrate_threshold(model, windows: list[dict]) -> dict:
    candidates = calibration_windows(windows)
    scope = candidates[0]
    selected_windows = candidates[1]
    labels = [int(item["label"]) for item in selected_windows]
    x = torch.tensor([item["features"] for item in selected_windows], dtype=torch.float32)
    with torch.no_grad():
        probabilities = torch.sigmoid(model(x)).reshape(-1).cpu().tolist()

    best = None
    for index in range(30, 86, 5):
        threshold = round(index / 100, 2)
        metrics = threshold_metrics(probabilities, labels, threshold=threshold)
        if best is None or threshold_is_better(metrics, best):
            best = metrics
    assert best is not None
    return {
        "fall_probability": best["threshold"],
        "scope": scope,
        "method": "max_f1_min_fp_highest_threshold_grid_0.30_0.85",
        "sample_count": len(selected_windows),
        "positive_samples": sum(labels),
        "negative_samples": len(labels) - sum(labels),
        "precision": best["precision"],
        "recall": best["recall"],
        "f1": best["f1"],
        "false_positive_count": best["false_positive_count"],
    }


def calibration_windows(windows: list[dict]) -> tuple[str, list[dict]]:
    for scope in ("val", "train"):
        selected = [item for item in windows if item["split"] == scope]
        labels = {int(item["label"]) for item in selected}
        if labels == {0, 1}:
            return scope, selected
    selected = [item for item in windows if item["split"] != "test"]
    labels = {int(item["label"]) for item in selected}
    if labels == {0, 1}:
        return "non_test", selected
    raise SystemExit("threshold calibration requires both fall and non_fall windows")


def threshold_metrics(probabilities: list[float], labels: list[int], *, threshold: float) -> dict:
    tp = fp = fn = tn = 0
    for probability, label in zip(probabilities, labels):
        pred = 1 if probability >= threshold else 0
        if pred == 1 and label == 1:
            tp += 1
        elif pred == 1 and label == 0:
            fp += 1
        elif pred == 0 and label == 1:
            fn += 1
        else:
            tn += 1
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = safe_div(2 * precision * recall, precision + recall) if precision + recall else 0.0
    return {
        "threshold": threshold,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "false_positive_count": fp,
        "true_positive": tp,
        "false_negative": fn,
        "true_negative": tn,
    }


def threshold_is_better(candidate: dict, current: dict) -> bool:
    candidate_key = (
        candidate["f1"],
        -candidate["false_positive_count"],
        candidate["threshold"],
    )
    current_key = (
        current["f1"],
        -current["false_positive_count"],
        current["threshold"],
    )
    return candidate_key > current_key


def safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def validate_onnx(model, dummy, onnx_path: Path) -> dict:
    try:
        import numpy as np
        import onnxruntime as ort
    except Exception as exc:
        return {"passed": False, "reason": f"onnxruntime unavailable: {exc}"}

    with torch.no_grad():
        torch_output = torch.sigmoid(model(dummy)).cpu().numpy()
    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    onnx_output = session.run(None, {"input": dummy.cpu().numpy()})[0]
    max_abs_diff = float(np.max(np.abs(torch_output - onnx_output)))
    return {"passed": max_abs_diff < 1e-4, "max_abs_diff": max_abs_diff}


def ensure_onnx_export_dependencies() -> None:
    if importlib.util.find_spec("onnx") is None:
        raise SystemExit(
            "onnx package is required to export fall_lstm ONNX models; "
            "install it with `python -m pip install onnx>=1.16` before running train_fall_lstm.py"
        )


if __name__ == "__main__":
    raise SystemExit(main())
