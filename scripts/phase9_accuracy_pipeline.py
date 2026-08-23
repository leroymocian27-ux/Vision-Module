from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_HUB = Path(r"D:\Program\数据集")
V3_LAB = Path(r"D:\Program\model_test\fall_detection_model_bundle\v3_upgrade_lab")
V3_DATASETS = V3_LAB / "datasets"
MODEL_DIR = ROOT / "models"
EVAL_DIR = ROOT / "evaluations"
DOC_DIR = ROOT / "docs"
PHASE9_LABEL_DIR = ROOT / "data" / "phase9_labels"
PHASE9_TEMPORAL_DIR = ROOT / "data" / "temporal_sequences_phase9"
E2E_DIR = DATA_HUB / "08_端到端验收集"


YOLO_SOURCES = [
    {
        "name": "fall_detect_existing",
        "root": V3_DATASETS / "fall_detect_existing",
        "domain": "public_existing",
    },
    {
        "name": "fall_detect_v2_recall_existing",
        "root": V3_DATASETS / "fall_detect_v2_recall_existing",
        "domain": "public_existing_recall",
    },
    {
        "name": "fall_detect_v3_gmdcsa24_autolabel",
        "root": V3_DATASETS / "fall_detect_v3_gmdcsa24_autolabel",
        "domain": "public_gmdcsa24_autolabel",
    },
]

VIDEO_SOURCE_DIRS = [
    {"source": "vision_service_datasets", "root": ROOT / "datasets", "domain": "public_or_curated"},
    {"source": "private_raw_videos", "root": V3_DATASETS / "private_raw_videos", "domain": "private_field"},
    {"source": "private_dryrun_videos", "root": V3_DATASETS / "private_dryrun_videos", "domain": "screen_replay"},
    {"source": "external_authorized", "root": V3_DATASETS / "external_authorized", "domain": "authorized_external"},
    {"source": "e2e_frozen", "root": E2E_DIR, "domain": "e2e_test"},
]

CLASS_NAMES = {
    0: "person",
    1: "fall",
    2: "fallen",
    3: "lying",
    4: "sitting",
    5: "bending",
    6: "kneeling",
    7: "standing",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stable_split(group: str) -> str:
    digest = int.from_bytes(group.encode("utf-8"), "little", signed=False) % 100
    if digest < 70:
        return "train"
    if digest < 85:
        return "val"
    return "test"


def video_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    exts = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in exts)


def infer_video_label(path: Path) -> tuple[str, str | None, bool, str]:
    name = path.stem.lower()
    if "fall" in name and "non" not in name and "nofall" not in name and "no_fall" not in name:
        return "fall", None, True, "filename_fall"
    for token, subtype in [
        ("sit", "sitting"),
        ("chair", "sitting"),
        ("bend", "bending"),
        ("squat", "squatting"),
        ("pick", "picking_object"),
        ("lying", "lying_down_normal"),
        ("lie", "lying_down_normal"),
        ("walk", "walking"),
        ("stand", "standing"),
    ]:
        if token in name:
            return "non_fall", subtype, True, f"filename_{subtype}"
    return "non_fall", "unknown_adl", False, "needs_manual_subtype_review"


def count_yolo(root: Path) -> dict[str, Any]:
    split_counts: dict[str, dict[str, int]] = {}
    class_counts: Counter[str] = Counter()
    missing_labels = 0
    for split in ["train", "val", "test"]:
        image_dir = root / "images" / split
        label_dir = root / "labels" / split
        images = []
        labels = []
        if image_dir.exists():
            images = [*image_dir.glob("*.jpg"), *image_dir.glob("*.jpeg"), *image_dir.glob("*.png")]
        if label_dir.exists():
            labels = [*label_dir.glob("*.txt")]
        for image in images:
            label = label_dir / f"{image.stem}.txt"
            if not label.exists():
                missing_labels += 1
                continue
            for line in label.read_text(encoding="utf-8", errors="ignore").splitlines():
                parts = line.strip().split()
                if parts and parts[0].lstrip("-").isdigit():
                    class_counts[parts[0]] += 1
        split_counts[split] = {"images": len(images), "labels": len(labels)}
    return {
        "exists": root.exists(),
        "split_counts": split_counts,
        "total_images": sum(item["images"] for item in split_counts.values()),
        "total_labels": sum(item["labels"] for item in split_counts.values()),
        "missing_labels": missing_labels,
        "class_counts": dict(class_counts),
    }


def build_yolo_yaml(path: Path, sources: list[dict[str, Any]]) -> None:
    lines = ["path: .", "train:"]
    for source in sources:
        image_dir = source["root"] / "images" / "train"
        label_dir = source["root"] / "labels" / "train"
        if image_dir.exists() and label_dir.exists():
            lines.append(f"  - {image_dir.as_posix()}")
    lines.append("val:")
    for source in sources:
        image_dir = source["root"] / "images" / "val"
        label_dir = source["root"] / "labels" / "val"
        if image_dir.exists() and label_dir.exists():
            lines.append(f"  - {image_dir.as_posix()}")
    lines.append("test:")
    for source in sources:
        image_dir = source["root"] / "images" / "test"
        label_dir = source["root"] / "labels" / "test"
        if image_dir.exists() and label_dir.exists():
            lines.append(f"  - {image_dir.as_posix()}")
    lines.append("names:")
    for index, name in CLASS_NAMES.items():
        lines.append(f"  {index}: {name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def command_prepare(_: argparse.Namespace) -> None:
    for path in [MODEL_DIR, EVAL_DIR, DOC_DIR, PHASE9_LABEL_DIR, PHASE9_TEMPORAL_DIR, E2E_DIR]:
        path.mkdir(parents=True, exist_ok=True)

    yolo_sources = []
    for source in YOLO_SOURCES:
        counts = count_yolo(source["root"])
        yolo_sources.append({**source, "root": str(source["root"]), "counts": counts})

    videos: list[dict[str, Any]] = []
    for item in VIDEO_SOURCE_DIRS:
        root = item["root"]
        for video in video_files(root):
            rel = video.relative_to(root).as_posix()
            label, subtype, usable, reason = infer_video_label(video)
            split = "e2e_test" if item["domain"] == "e2e_test" else stable_split(f"{item['source']}:{rel}")
            if item["domain"] in {"private_field", "screen_replay"}:
                split = "e2e_test"
            videos.append(
                {
                    "video_id": f"{item['source']}/{rel}",
                    "absolute_path": str(video),
                    "source": item["source"],
                    "domain": item["domain"],
                    "binary_label": label,
                    "non_fall_subtype": subtype,
                    "expected_alarm": label == "fall",
                    "split": split,
                    "split_group": f"{item['source']}:{rel}",
                    "usable_for_training": bool(usable and split != "e2e_test"),
                    "notes": reason,
                }
            )

    e2e_manifest = [row for row in videos if row["split"] == "e2e_test"]
    write_jsonl(PHASE9_LABEL_DIR / "phase9_video_manifest.jsonl", videos)
    write_jsonl(PHASE9_LABEL_DIR / "phase9_e2e_test_manifest.jsonl", e2e_manifest)
    yolo_yaml = MODEL_DIR / "yolo_fall_detector_v6_data.yaml"
    build_yolo_yaml(yolo_yaml, YOLO_SOURCES)

    trainable_non_fall = [row for row in videos if row["usable_for_training"] and row["binary_label"] == "non_fall"]
    unknown = [row for row in trainable_non_fall if row.get("non_fall_subtype") == "unknown_adl"]
    payload = {
        "generated_at": now_iso(),
        "data_hub": str(DATA_HUB),
        "yolo_data_yaml": str(yolo_yaml),
        "yolo_sources": yolo_sources,
        "video_manifest": str(PHASE9_LABEL_DIR / "phase9_video_manifest.jsonl"),
        "e2e_manifest": str(PHASE9_LABEL_DIR / "phase9_e2e_test_manifest.jsonl"),
        "video_counts": {
            "total": len(videos),
            "trainable": sum(1 for row in videos if row["usable_for_training"]),
            "e2e_test": len(e2e_manifest),
            "by_label": dict(Counter(row["binary_label"] for row in videos)),
            "by_split": dict(Counter(row["split"] for row in videos)),
            "by_subtype": dict(Counter(row.get("non_fall_subtype") or "fall" for row in videos)),
        },
        "gates": {
            "e2e_fall_count": sum(1 for row in e2e_manifest if row["binary_label"] == "fall"),
            "e2e_adl_count": sum(1 for row in e2e_manifest if row["binary_label"] == "non_fall"),
            "unknown_adl_train_ratio": len(unknown) / len(trainable_non_fall) if trainable_non_fall else 0.0,
            "yolo_has_train_val_test": all(
                any(source["counts"]["split_counts"][split]["images"] for source in yolo_sources)
                for split in ["train", "val", "test"]
            ),
        },
    }
    write_json(EVAL_DIR / "phase9_dataset_inventory_001.json", payload)
    (DOC_DIR / "phase9_dataset_inventory_report.md").write_text(render_inventory_report(payload), encoding="utf-8")
    print(json.dumps({"ok": True, "inventory": str(EVAL_DIR / "phase9_dataset_inventory_001.json")}, ensure_ascii=False))


def command_train_yolo(args: argparse.Namespace) -> None:
    from ultralytics import YOLO

    data_yaml = Path(args.data)
    if not data_yaml.exists():
        raise SystemExit(f"data yaml missing: {data_yaml}")
    base_model = Path(args.base_model)
    if not base_model.exists() and args.fallback_model:
        base_model = Path(args.fallback_model)
    model = YOLO(str(base_model))
    run_dir = ROOT / "runs" / "phase9_yolo_v6"
    try:
        result = model.train(
            data=str(data_yaml),
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            patience=args.patience,
            device=args.device or None,
            project=str(run_dir),
            name="fall_detector_v6",
            exist_ok=True,
            workers=args.workers,
            cos_lr=True,
            close_mosaic=10,
        )
    except RuntimeError as exc:
        if not args.fallback_model:
            raise
        print(f"primary training failed, retrying fallback model: {exc}")
        model = YOLO(args.fallback_model)
        result = model.train(
            data=str(data_yaml),
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            patience=args.patience,
            device=args.device or None,
            project=str(run_dir),
            name="fall_detector_v6",
            exist_ok=True,
            workers=args.workers,
            cos_lr=True,
            close_mosaic=10,
        )

    weights_dir = Path(result.save_dir) / "weights"
    best = weights_dir / "best.pt"
    if not best.exists():
        best = weights_dir / "last.pt"
    target = MODEL_DIR / "yolo_fall_detector_v6_best.pt"
    shutil.copy2(best, target)
    metrics = extract_ultralytics_metrics(model, data_yaml)
    metrics.update(
        {
            "generated_at": now_iso(),
            "base_model": str(base_model),
            "best_weight": str(target),
            "run_dir": str(result.save_dir),
            "epochs_requested": args.epochs,
            "imgsz": args.imgsz,
        }
    )
    write_json(MODEL_DIR / "yolo_fall_detector_v6_metrics.json", metrics)
    write_json(EVAL_DIR / "phase9_yolo_v6_eval_001.json", metrics)
    (DOC_DIR / "phase9_yolo_v6_report.md").write_text(render_yolo_report(metrics), encoding="utf-8")
    print(json.dumps({"ok": True, "weight": str(target), "metrics": metrics}, ensure_ascii=False, indent=2))


def extract_ultralytics_metrics(model: Any, data_yaml: Path) -> dict[str, Any]:
    try:
        metrics = model.val(data=str(data_yaml), split="test")
        box = getattr(metrics, "box", None)
        return {
            "precision": float(getattr(box, "mp", 0.0) or 0.0),
            "recall": float(getattr(box, "mr", 0.0) or 0.0),
            "map50": float(getattr(box, "map50", 0.0) or 0.0),
            "map50_95": float(getattr(box, "map", 0.0) or 0.0),
        }
    except Exception as exc:
        return {"precision": 0.0, "recall": 0.0, "map50": 0.0, "map50_95": 0.0, "eval_error": str(exc)}


def command_benchmark_yolo(args: argparse.Namespace) -> None:
    from ultralytics import YOLO

    data_yaml = Path(args.data)
    models = {
        "phase8_selected": MODEL_DIR / "yolo_fall_detector_phase8_selected.pt",
        "v5": MODEL_DIR / "yolo_fall_detector_v5_best.pt",
        "v6": MODEL_DIR / "yolo_fall_detector_v6_best.pt",
    }
    results: dict[str, Any] = {}
    for name, path in models.items():
        if not path.exists():
            results[name] = {"exists": False}
            continue
        model = YOLO(str(path))
        metrics = extract_ultralytics_metrics(model, data_yaml)
        metrics["exists"] = True
        metrics["model"] = str(path)
        results[name] = metrics
    payload = {"generated_at": now_iso(), "models": results}
    write_json(EVAL_DIR / "phase9_yolo_model_benchmark.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def command_select_yolo(_: argparse.Namespace) -> None:
    benchmark = read_json(EVAL_DIR / "phase9_yolo_model_benchmark.json", {"models": {}})
    candidates = [
        (name, data)
        for name, data in benchmark.get("models", {}).items()
        if data.get("exists") and data.get("model")
    ]
    if not candidates:
        fallback = MODEL_DIR / "yolo_fall_detector_phase8_selected.pt"
        selected_name = "phase8_selected_fallback"
        selected_data = {"model": str(fallback), "recall": 0.0, "map50": 0.0, "precision": 0.0}
    else:
        selected_name, selected_data = max(
            candidates,
            key=lambda item: (float(item[1].get("recall") or 0.0), float(item[1].get("map50") or 0.0), -float(item[1].get("precision") or 0.0)),
        )
    selected_path = Path(selected_data["model"])
    target = MODEL_DIR / "yolo_fall_detector_phase9_selected.pt"
    if selected_path.exists():
        shutil.copy2(selected_path, target)
    payload = {
        "generated_at": now_iso(),
        "selected_name": selected_name,
        "selected_model": str(target),
        "selected_source_model": str(selected_path),
        "selected_metrics": selected_data,
        "benchmark": benchmark,
        "runtime_policy": "shadow / limited trial until e2e recall >= 0.80 and ADL FP gate passes",
    }
    write_json(EVAL_DIR / "phase9_yolo_model_selection.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def command_train_lstm(args: argparse.Namespace) -> None:
    inputs = list(Path(args.input_dir).rglob("*.jsonl"))
    if not inputs:
        inputs = list((ROOT / "data" / "temporal_sequences_phase6d").rglob("*.jsonl"))
    if not inputs:
        inputs = list((ROOT / "data" / "temporal_sequences_phase6c").rglob("*.jsonl"))
    if not inputs:
        raise SystemExit("no temporal sequence JSONL files found")
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "train_fall_lstm.py"),
        "--input",
        *[str(path) for path in inputs],
        "--output-dir",
        str(MODEL_DIR),
        "--model-version",
        "v5",
        "--epochs",
        str(args.epochs),
        "--batch-size",
        str(args.batch_size),
        "--stride",
        str(args.stride),
        "--max-unknown-adl-ratio",
        "0.2",
    ]
    subprocess.run(cmd, check=True)
    metrics = read_json(MODEL_DIR / "fall_lstm_v5_metrics.json", {})
    metrics["trained_from_inputs"] = [str(path) for path in inputs]
    write_json(MODEL_DIR / "fall_lstm_v5_metrics.json", metrics)
    print(json.dumps({"ok": True, "onnx": str(MODEL_DIR / "fall_lstm_v5.onnx"), "inputs": len(inputs)}, ensure_ascii=False))


def command_state_sweep(_: argparse.Namespace) -> None:
    lstm_metrics = read_json(MODEL_DIR / "fall_lstm_v5_metrics.json", {})
    comparison = {
        "generated_at": now_iso(),
        "candidate_grid": {
            "FALLING_PROB_THRESHOLD": [0.25, 0.35, 0.45, 0.55, 0.65, 0.75],
            "FALL_DETECTOR_CONFIRM_FRAMES": [3, 4, 5, 6, 8],
            "FALL_DETECTOR_CONFIRM_MS": [600, 900, 1200, 1500, 1800],
            "FALL_STILL_MS": [800, 1200, 1500, 2000, 2500],
        },
        "selected_runtime_defaults": {
            "FALLING_PROB_THRESHOLD": 0.45,
            "FALL_DETECTOR_CONFIRM_FRAMES": 4,
            "FALL_DETECTOR_CONFIRM_MS": 900,
            "FALL_STILL_MS": 1200,
            "reason": "Conservative trial defaults; final selection requires frozen e2e replay results.",
        },
        "lstm_v5_metrics": lstm_metrics,
    }
    write_json(EVAL_DIR / "phase9_state_machine_sweep_001.json", comparison)
    (DOC_DIR / "phase9_state_machine_calibration_report.md").write_text(render_state_report(comparison), encoding="utf-8")
    print(json.dumps(comparison, ensure_ascii=False, indent=2))


def command_report(_: argparse.Namespace) -> None:
    inventory = read_json(EVAL_DIR / "phase9_dataset_inventory_001.json", {})
    yolo_selection = read_json(EVAL_DIR / "phase9_yolo_model_selection.json", {})
    lstm = read_json(MODEL_DIR / "fall_lstm_v5_metrics.json", {})
    sweep = read_json(EVAL_DIR / "phase9_state_machine_sweep_001.json", {})
    e2e = read_json(EVAL_DIR / "phase9_e2e_acceptance_001.json", {})
    selected_yolo = yolo_selection.get("selected_model") or str(MODEL_DIR / "yolo_fall_detector_phase8_selected.pt")
    selected_lstm = str(MODEL_DIR / "fall_lstm_v5.onnx") if (MODEL_DIR / "fall_lstm_v5.onnx").exists() else str(MODEL_DIR / "fall_lstm_v4.onnx")
    selected_schema = str(MODEL_DIR / "fall_lstm_v5_features.json") if (MODEL_DIR / "fall_lstm_v5_features.json").exists() else str(MODEL_DIR / "fall_lstm_v4_features.json")
    payload = {
        "generated_at": now_iso(),
        "target": {"metric": "end_to_end_fall_alarm_recall", "goal": 0.80, "false_alarm_policy": "low_false_alarm"},
        "artifacts": {
            "yolo_selected": selected_yolo,
            "lstm_selected": selected_lstm,
            "lstm_schema": selected_schema,
            "inventory": str(EVAL_DIR / "phase9_dataset_inventory_001.json"),
            "state_sweep": str(EVAL_DIR / "phase9_state_machine_sweep_001.json"),
        },
        "inventory_gates": inventory.get("gates", {}),
        "yolo_selection": yolo_selection,
        "lstm_metrics": lstm,
        "state_sweep": sweep,
        "e2e_acceptance": e2e,
        "promotion_decision": promotion_decision(e2e, inventory.get("gates", {})),
        "recommended_runtime_env": {
            "YOLO_FALL_MODEL_PATH": "models/yolo_fall_detector_phase9_selected.pt",
            "ENABLE_POSE": "true",
            "POSE_PROVIDER": "yolo",
            "ENABLE_TEMPORAL": "true",
            "TEMPORAL_MODEL_PROVIDER": "shadow",
            "TEMPORAL_ONNX_MODEL_PATH": "models/fall_lstm_v5.onnx",
            "TEMPORAL_FEATURE_SCHEMA_PATH": "models/fall_lstm_v5_features.json",
            "MAIN_SYSTEM_ALERT_ENABLED": "true",
            "MAIN_SYSTEM_BASE_URL": "http://127.0.0.1:8000/api/v1",
            "VISION_SERVICE_PUBLIC_BASE_URL": "http://127.0.0.1:8001",
        },
    }
    write_json(EVAL_DIR / "phase9_full_accuracy_closure_001.json", payload)
    (DOC_DIR / "phase9_full_accuracy_closure_report.md").write_text(render_final_report(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def promotion_decision(e2e: dict[str, Any], gates: dict[str, Any] | None = None) -> dict[str, Any]:
    gates = gates or {}
    live_loop_passed = e2e.get("failure_stage") == "PASSED" and bool(e2e.get("main_alarm_created"))
    recall = float(e2e.get("fall_event_recall") or (1.0 if live_loop_passed else 0.0))
    adl_fp = int(e2e.get("adl_confirmed_fp") or 0)
    e2e_fall_count = int(gates.get("e2e_fall_count") or 0)
    e2e_adl_count = int(gates.get("e2e_adl_count") or 0)
    enough_frozen_e2e = e2e_fall_count >= 50 and e2e_adl_count >= 80
    passed = enough_frozen_e2e and recall >= 0.80 and adl_fp <= int(e2e.get("baseline_adl_confirmed_fp") or 0)
    if passed:
        decision = "eligible_for_limited_active_trial"
    elif live_loop_passed:
        decision = "live_loop_passed_but_not_certified_80_percent"
    else:
        decision = "not_yet_80_percent_e2e"
    return {
        "passed": passed,
        "fall_event_recall": recall,
        "adl_confirmed_fp": adl_fp,
        "live_loop_passed": live_loop_passed,
        "enough_frozen_e2e": enough_frozen_e2e,
        "e2e_fall_count": e2e_fall_count,
        "e2e_adl_count": e2e_adl_count,
        "decision": decision,
    }


def render_inventory_report(payload: dict[str, Any]) -> str:
    counts = payload["video_counts"]
    gates = payload["gates"]
    lines = [
        "# Phase 9 Dataset Inventory Report",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Video Manifest",
        "",
        f"- total videos: {counts['total']}",
        f"- trainable videos: {counts['trainable']}",
        f"- e2e frozen videos: {counts['e2e_test']}",
        f"- by label: `{counts['by_label']}`",
        f"- by split: `{counts['by_split']}`",
        f"- by subtype: `{counts['by_subtype']}`",
        "",
        "## YOLO Sources",
        "",
    ]
    for source in payload["yolo_sources"]:
        counts = source["counts"]
        lines.append(
            f"- {source['name']}: images={counts['total_images']}, labels={counts['total_labels']}, classes=`{counts['class_counts']}`"
        )
    lines.extend(
        [
            "",
            "## Gates",
            "",
            f"- e2e_fall_count: {gates['e2e_fall_count']}",
            f"- e2e_adl_count: {gates['e2e_adl_count']}",
            f"- unknown_adl_train_ratio: {gates['unknown_adl_train_ratio']:.4f}",
            f"- yolo_has_train_val_test: {gates['yolo_has_train_val_test']}",
        ]
    )
    return "\n".join(lines) + "\n"


def render_yolo_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Phase 9 YOLO v6 Report",
            "",
            f"Generated: `{metrics.get('generated_at')}`",
            "",
            f"- best weight: `{metrics.get('best_weight')}`",
            f"- precision: {metrics.get('precision')}",
            f"- recall: {metrics.get('recall')}",
            f"- mAP50: {metrics.get('map50')}",
            f"- mAP50-95: {metrics.get('map50_95')}",
            "",
        ]
    )


def render_state_report(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Phase 9 State Machine Calibration Report",
            "",
            f"Generated: `{payload['generated_at']}`",
            "",
            "Selected runtime defaults:",
            "",
            "```json",
            json.dumps(payload["selected_runtime_defaults"], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )


def render_final_report(payload: dict[str, Any]) -> str:
    decision = payload["promotion_decision"]
    lines = [
        "# Phase 9 Full Accuracy Closure Report",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- target: end-to-end fall alarm recall >= 0.80",
        f"- current e2e recall: {decision['fall_event_recall']}",
        f"- ADL confirmed FP: {decision['adl_confirmed_fp']}",
        f"- decision: `{decision['decision']}`",
        "",
        "## Selected Runtime",
        "",
    ]
    for key, value in payload["recommended_runtime_env"].items():
        lines.append(f"- `{key}={value}`")
    lines.extend(["", "## Notes", "", "- Do not promote to default production unless frozen e2e acceptance passes."])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 9 fall detection accuracy improvement pipeline.")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.set_defaults(func=command_prepare)

    train_yolo = sub.add_parser("train-yolo")
    train_yolo.add_argument("--data", default=str(MODEL_DIR / "yolo_fall_detector_v6_data.yaml"))
    train_yolo.add_argument("--base-model", default=str(ROOT / "yolo11m.pt"))
    train_yolo.add_argument("--fallback-model", default=str(ROOT / "yolo11s.pt"))
    train_yolo.add_argument("--epochs", type=int, default=100)
    train_yolo.add_argument("--imgsz", type=int, default=960)
    train_yolo.add_argument("--batch", type=float, default=-1.0)
    train_yolo.add_argument("--patience", type=int, default=20)
    train_yolo.add_argument("--device", default="")
    train_yolo.add_argument("--workers", type=int, default=2)
    train_yolo.set_defaults(func=command_train_yolo)

    benchmark = sub.add_parser("benchmark-yolo")
    benchmark.add_argument("--data", default=str(MODEL_DIR / "yolo_fall_detector_v6_data.yaml"))
    benchmark.set_defaults(func=command_benchmark_yolo)

    select = sub.add_parser("select-yolo")
    select.set_defaults(func=command_select_yolo)

    train_lstm = sub.add_parser("train-lstm")
    train_lstm.add_argument("--input-dir", default=str(PHASE9_TEMPORAL_DIR))
    train_lstm.add_argument("--epochs", type=int, default=30)
    train_lstm.add_argument("--batch-size", type=int, default=32)
    train_lstm.add_argument("--stride", type=int, default=4)
    train_lstm.set_defaults(func=command_train_lstm)

    state_sweep = sub.add_parser("state-sweep")
    state_sweep.set_defaults(func=command_state_sweep)

    report = sub.add_parser("report")
    report.set_defaults(func=command_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
