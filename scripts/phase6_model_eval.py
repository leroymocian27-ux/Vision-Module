from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Phase 6 ONNX LSTM windows.")
    parser.add_argument("--input", required=True, nargs="+")
    parser.add_argument("--model", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--stride", type=int, default=2)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    windows = load_windows(args.input, schema, stride=max(1, args.stride), split=args.split)
    probabilities = predict(args.model, windows)
    labels = np.asarray([item["label"] for item in windows], dtype=np.int32)
    subtypes = [item["non_fall_subtype"] or "fall" for item in windows]
    result = summarize(probabilities, labels, subtypes)
    result["model"] = args.model
    result["schema"] = args.schema
    result["split"] = args.split
    result["windows"] = len(windows)
    result["label_counts"] = dict(Counter(int(x) for x in labels))
    result["subtype_counts"] = dict(Counter(subtypes))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def load_windows(paths: list[str], schema: dict, *, stride: int, split: str) -> list[dict]:
    by_key = defaultdict(list)
    for path in paths:
        with Path(path).open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("schema_version") != schema["schema_version"] or row.get("schema_hash") != schema["schema_hash"]:
                    raise ValueError(f"schema mismatch in {path}")
                if len(row.get("vector") or []) != schema["input_dim"]:
                    raise ValueError(f"vector dim mismatch in {path}")
                by_key[row["sequence_key"]].append(row)
    assign_splits(by_key, seed=42)
    windows = []
    size = int(schema["window_size"])
    for rows in by_key.values():
        rows.sort(key=lambda item: int(item["frame_seq"]))
        if rows and rows[0].get("split") != split:
            continue
        for start in range(0, len(rows) - size + 1, stride):
            window = rows[start : start + size]
            windows.append(
                {
                    "x": [item["vector"] for item in window],
                    "label": 1 if any(item.get("label") == "fall" for item in window) else 0,
                    "non_fall_subtype": window[0].get("non_fall_subtype"),
                }
            )
    return windows


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
    for index, group in enumerate(groups):
        if index < train_cut:
            split = "train"
        elif index < val_cut:
            split = "val"
        else:
            split = "test"
        for rows in grouped[group]:
            for row in rows:
                if row.get("split") in {None, "", "unassigned"}:
                    row["split"] = split


def predict(model_path: str, windows: list[dict]) -> np.ndarray:
    import onnxruntime as ort

    if not windows:
        return np.asarray([], dtype=np.float32)
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    x = np.asarray([item["x"] for item in windows], dtype=np.float32)
    output = np.asarray(session.run(None, {input_name: x})[0], dtype=np.float32).reshape(-1)
    return np.clip(output, 0.0, 1.0)


def summarize(probabilities: np.ndarray, labels: np.ndarray, subtypes: list[str]) -> dict:
    thresholds = [round(x, 2) for x in np.arange(0.30, 0.851, 0.05)]
    sweep = []
    for threshold in thresholds:
        pred = probabilities >= threshold
        tp = int(np.sum((pred == 1) & (labels == 1)))
        fp = int(np.sum((pred == 1) & (labels == 0)))
        tn = int(np.sum((pred == 0) & (labels == 0)))
        fn = int(np.sum((pred == 0) & (labels == 1)))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        subtype_fp = Counter(subtypes[i] for i, value in enumerate(pred) if value and labels[i] == 0)
        sweep.append(
            {
                "threshold": threshold,
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "subtype_fp": dict(subtype_fp),
            }
        )
    best = max(sweep, key=lambda item: (item["f1"], item["recall"], -item["fp"])) if sweep else {}
    return {
        "auc": round(auc(probabilities, labels), 4),
        "best_threshold": best,
        "threshold_sweep": sweep,
        "probability_min": float(np.min(probabilities)) if probabilities.size else None,
        "probability_max": float(np.max(probabilities)) if probabilities.size else None,
        "probability_mean": float(np.mean(probabilities)) if probabilities.size else None,
    }


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    pos = scores[labels == 1]
    neg = scores[labels == 0]
    if len(pos) == 0 or len(neg) == 0:
        return 0.0
    wins = 0.0
    for value in pos:
        wins += float(np.sum(value > neg))
        wins += 0.5 * float(np.sum(value == neg))
    return wins / (len(pos) * len(neg))


if __name__ == "__main__":
    raise SystemExit(main())
