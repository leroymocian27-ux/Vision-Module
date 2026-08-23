from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASET_HUB = Path("D:/Program") / "\u6570\u636e\u96c6"
VISION_DATASETS = ROOT / "datasets"
V3_LAB = Path(r"D:\Program\model_test\fall_detection_model_bundle\v3_upgrade_lab")
V3_DATASETS = V3_LAB / "datasets"
PHASE6_LABELS = ROOT / "data" / "phase6_labels" / "phase6_labels.jsonl"
PHASE7_LABEL_DIR = ROOT / "data" / "phase7_labels"
EVAL_DIR = ROOT / "evaluations"
DOC_DIR = ROOT / "docs"
MODEL_DIR = ROOT / "models"

ALLOWED_SUBTYPES = {
    "standing",
    "walking",
    "sitting",
    "bending",
    "squatting",
    "picking_object",
    "lying_down_normal",
    "unknown_adl",
}

YOLO_DATASETS = [
    {
        "name": "fall_detect_existing",
        "root": V3_DATASETS / "fall_detect_existing",
        "domain": "public_existing",
        "classes": {0: "person", 1: "fall", 2: "fallen", 3: "sitting", 4: "lying", 5: "bending"},
    },
    {
        "name": "fall_detect_v2_recall_existing",
        "root": V3_DATASETS / "fall_detect_v2_recall_existing",
        "domain": "public_existing_recall",
        "classes": {0: "person", 1: "fall", 2: "fallen", 3: "sitting", 4: "lying", 5: "bending"},
    },
    {
        "name": "fall_detect_v3_gmdcsa24_autolabel",
        "root": V3_DATASETS / "fall_detect_v3_gmdcsa24_autolabel",
        "domain": "public_gmdcsa24_autolabel",
        "classes": {
            0: "person",
            1: "fall",
            2: "fallen",
            3: "lying",
            4: "sitting",
            5: "bending",
            6: "kneeling",
            7: "standing",
        },
    },
]

VIDEO_DIRS = [
    {"name": "vision_datasets", "root": VISION_DATASETS, "domain": "phase6_public_private"},
    {"name": "private_raw_videos", "root": V3_DATASETS / "private_raw_videos", "domain": "private_field"},
    {"name": "private_dryrun_videos", "root": V3_DATASETS / "private_dryrun_videos", "domain": "screen_replay"},
    {"name": "external_authorized", "root": V3_DATASETS / "external_authorized", "domain": "authorized_external"},
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def stable_split(group: str) -> str:
    digest = int(hashlib.sha1(group.encode("utf-8")).hexdigest()[:8], 16) % 100
    if digest < 70:
        return "train"
    if digest < 85:
        return "val"
    return "test"


def infer_video_label(path: Path) -> tuple[str, str, bool, str]:
    name = path.stem.lower()
    if "fall" in name and "non" not in name and "nofall" not in name:
        return "fall", "fall", True, "filename heuristic"
    subtype = "unknown_adl"
    for token, mapped in [
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
            subtype = mapped
            break
    usable = subtype != "unknown_adl"
    return "non_fall", subtype, usable, "filename heuristic"


def label_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [r for r in rows if r.get("usable_for_training", True)]
    non_fall = [r for r in usable if r.get("binary_label") == "non_fall"]
    unknown = [r for r in non_fall if r.get("non_fall_subtype") == "unknown_adl"]
    return {
        "rows": len(rows),
        "usable_training_rows": len(usable),
        "binary_label_counts": dict(Counter(r.get("binary_label", "unknown") for r in usable)),
        "subtype_counts": dict(
            Counter((r.get("non_fall_subtype") if r.get("binary_label") == "non_fall" else "fall") for r in usable)
        ),
        "source_dataset_counts": dict(Counter(r.get("source_dataset", "unknown") for r in usable)),
        "split_counts": dict(Counter(r.get("split", "unassigned") for r in usable)),
        "unknown_adl_ratio": (len(unknown) / len(non_fall)) if non_fall else 0.0,
    }


def scan_video_inventory() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_source: dict[str, Any] = {}
    for item in VIDEO_DIRS:
        root = item["root"]
        videos = []
        if root.exists():
            videos = sorted([*root.rglob("*.mp4"), *root.rglob("*.avi"), *root.rglob("*.mov"), *root.rglob("*.mkv")])
        by_source[item["name"]] = {
            "root": str(root),
            "exists": root.exists(),
            "domain": item["domain"],
            "video_count": len(videos),
        }
        for video in videos:
            rel = video.relative_to(root).as_posix()
            binary, subtype, usable, note = infer_video_label(video)
            split_group = f"{item['name']}:{rel}"
            rows.append(
                {
                    "video_id": rel,
                    "absolute_path": str(video),
                    "source_dataset": item["name"],
                    "license": "unknown_private_or_inherited" if "private" in item["domain"] else "inherited_dataset_license",
                    "domain": item["domain"],
                    "split_group": split_group,
                    "subject": rel.split("/")[0] if "/" in rel else video.stem,
                    "binary_label": binary,
                    "non_fall_subtype": subtype if binary == "non_fall" else None,
                    "event_start_frame": 0,
                    "event_end_frame": None,
                    "usable_for_training": usable,
                    "split": "test" if item["domain"] in {"private_field", "screen_replay"} else stable_split(split_group),
                    "notes": note,
                }
            )
    return rows, by_source


def scan_yolo_dataset(dataset: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = dataset["root"]
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "name": dataset["name"],
        "root": str(root),
        "exists": root.exists(),
        "domain": dataset["domain"],
        "image_count": 0,
        "label_count": 0,
        "missing_label_count": 0,
        "split_counts": {},
        "class_counts": {},
        "usable_for_training": False,
    }
    if not root.exists():
        return rows, summary
    split_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    for split in ["train", "val", "test"]:
        image_dir = root / "images" / split
        label_dir = root / "labels" / split
        images = sorted([*image_dir.glob("*.jpg"), *image_dir.glob("*.jpeg"), *image_dir.glob("*.png")]) if image_dir.exists() else []
        for image in images:
            label = label_dir / f"{image.stem}.txt"
            has_label = label.exists()
            classes: list[int] = []
            if has_label:
                for line in label.read_text(encoding="utf-8", errors="ignore").splitlines():
                    parts = line.strip().split()
                    if parts and parts[0].isdigit():
                        classes.append(int(parts[0]))
                        class_counts[str(parts[0])] += 1
            rows.append(
                {
                    "dataset": dataset["name"],
                    "domain": dataset["domain"],
                    "split": split,
                    "image_path": str(image),
                    "label_path": str(label),
                    "has_label": has_label,
                    "classes": classes,
                    "class_names": [dataset["classes"].get(c, f"class_{c}") for c in classes],
                    "usable_for_training": has_label,
                }
            )
            split_counts[split] += 1
    summary.update(
        {
            "image_count": len(rows),
            "label_count": sum(1 for r in rows if r["has_label"]),
            "missing_label_count": sum(1 for r in rows if not r["has_label"]),
            "split_counts": dict(split_counts),
            "class_counts": dict(class_counts),
            "usable_for_training": any(r["has_label"] for r in rows),
        }
    )
    return rows, summary


def build_yolo_yaml(yolo_summaries: list[dict[str, Any]]) -> Path:
    train_dirs: list[str] = []
    val_dirs: list[str] = []
    test_dirs: list[str] = []
    for dataset in YOLO_DATASETS:
        root = dataset["root"]
        if not root.exists():
            continue
        for split, bucket in [("train", train_dirs), ("val", val_dirs), ("test", test_dirs)]:
            image_dir = root / "images" / split
            label_dir = root / "labels" / split
            if image_dir.exists() and label_dir.exists():
                bucket.append(str(image_dir).replace("\\", "/"))
    names = {
        0: "person",
        1: "fall",
        2: "fallen",
        3: "lying",
        4: "sitting",
        5: "bending",
        6: "kneeling",
        7: "standing",
    }
    lines = [
        "# Phase 7 v4 merged YOLO dataset. Paths are absolute to avoid stale v3 lab aliases.",
        "path: .",
        "train:",
    ]
    lines.extend(f"  - {p}" for p in train_dirs)
    lines.append("val:")
    lines.extend(f"  - {p}" for p in val_dirs)
    lines.append("test:")
    lines.extend(f"  - {p}" for p in test_dirs)
    lines.append("names:")
    lines.extend(f"  {idx}: {name}" for idx, name in names.items())
    path = MODEL_DIR / "yolo_fall_detector_v4_data.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def render_inventory_report(payload: dict[str, Any]) -> str:
    label = payload["phase7_video_labels_summary"]
    yolo = payload["yolo_summary"]
    lines = [
        "# Phase 7 Dataset Inventory",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Video Sources",
        "",
    ]
    for name, info in payload["video_sources"].items():
        lines.append(
            f"- `{name}`: exists={info['exists']}, videos={info['video_count']}, domain={info['domain']}, root=`{info['root']}`"
        )
    lines.extend(
        [
            "",
            "## Phase 7 Video Labels",
            "",
            f"- rows: {label['rows']}",
            f"- usable_training_rows: {label['usable_training_rows']}",
            f"- binary_label_counts: `{label['binary_label_counts']}`",
            f"- subtype_counts: `{label['subtype_counts']}`",
            f"- split_counts: `{label['split_counts']}`",
            f"- unknown_adl_ratio: {label['unknown_adl_ratio']:.4f}",
            "",
            "## YOLO Sources",
            "",
        ]
    )
    for item in yolo:
        lines.append(
            f"- `{item['name']}`: exists={item['exists']}, images={item['image_count']}, labels={item['label_count']}, missing_labels={item['missing_label_count']}, splits=`{item['split_counts']}`, classes=`{item['class_counts']}`"
        )
    lines.extend(
        [
            "",
            "## Gate Notes",
            "",
            "- `D:\\Program\\数据集` currently acts as an index folder. Phase 7 uses the real dataset roots directly.",
            "- `private_field` and `screen_replay` videos are kept in the manifest; items with uncertain subtype stay `usable_for_training=false` until reviewed.",
            "- YOLO v4 data yaml uses absolute image directories and does not overwrite v3 datasets.",
        ]
    )
    return "\n".join(lines) + "\n"


def command_prepare(_: argparse.Namespace) -> None:
    EVAL_DIR.mkdir(exist_ok=True)
    DOC_DIR.mkdir(exist_ok=True)
    PHASE7_LABEL_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(exist_ok=True)

    phase6_rows = read_jsonl(PHASE6_LABELS)
    phase7_rows: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for row in phase6_rows:
        copied = dict(row)
        group = str(copied.get("split_group") or copied.get("video_id") or len(phase7_rows))
        copied["split_group"] = group
        copied["split"] = stable_split(group)
        copied.setdefault("domain", "phase6_curated")
        copied.setdefault("subject", group.split("_")[0])
        phase7_rows.append(copied)
        seen_groups.add(group)

    scanned_rows, video_sources = scan_video_inventory()
    for row in scanned_rows:
        if row["split_group"] in seen_groups:
            continue
        phase7_rows.append(row)

    yolo_rows: list[dict[str, Any]] = []
    yolo_summary: list[dict[str, Any]] = []
    for dataset in YOLO_DATASETS:
        rows, summary = scan_yolo_dataset(dataset)
        yolo_rows.extend(rows)
        yolo_summary.append(summary)

    label_path = PHASE7_LABEL_DIR / "phase7_video_labels.jsonl"
    yolo_manifest_path = PHASE7_LABEL_DIR / "phase7_yolo_labels_manifest.jsonl"
    write_jsonl(label_path, phase7_rows)
    write_jsonl(yolo_manifest_path, yolo_rows)
    yolo_yaml = build_yolo_yaml(yolo_summary)

    payload = {
        "generated_at": now_iso(),
        "dataset_hub": {"path": str(DATASET_HUB), "exists": DATASET_HUB.exists()},
        "video_sources": video_sources,
        "phase7_video_labels": str(label_path),
        "phase7_video_labels_summary": label_summary(phase7_rows),
        "phase7_yolo_labels_manifest": str(yolo_manifest_path),
        "yolo_summary": yolo_summary,
        "yolo_data_yaml": str(yolo_yaml),
        "gates": {
            "unknown_adl_below_10_percent": label_summary(phase7_rows)["unknown_adl_ratio"] < 0.10,
            "yolo_images_have_labels": all(item["missing_label_count"] == 0 for item in yolo_summary if item["exists"]),
            "has_private_or_screen_replay_test": any(
                r.get("domain") in {"private_field", "screen_replay"} and r.get("split") == "test" for r in phase7_rows
            ),
        },
    }
    write_json(EVAL_DIR / "phase7_dataset_inventory_001.json", payload)
    (DOC_DIR / "phase7_dataset_inventory_report.md").write_text(render_inventory_report(payload), encoding="utf-8")
    print(json.dumps({"ok": True, "inventory": str(EVAL_DIR / "phase7_dataset_inventory_001.json"), "yolo_yaml": str(yolo_yaml)}, ensure_ascii=False))


def command_comparison(_: argparse.Namespace) -> None:
    def load(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"exists": False}
        return json.loads(path.read_text(encoding="utf-8"))

    yolo_v4_metrics = load(MODEL_DIR / "yolo_fall_detector_v4_metrics.json")
    lstm_v3_metrics = load(MODEL_DIR / "fall_lstm_v3_metrics.json")
    lstm_v4_metrics = load(MODEL_DIR / "fall_lstm_v4_metrics.json")
    inventory = load(EVAL_DIR / "phase7_dataset_inventory_001.json")
    payload = {
        "generated_at": now_iso(),
        "comparison": {
            "current_mock_rules": {"role": "production_default", "status": "kept"},
            "yolo_v3_lstm_v3": {"lstm_metrics": lstm_v3_metrics},
            "yolo_v4_lstm_v3": {"yolo_metrics": yolo_v4_metrics, "lstm_metrics": lstm_v3_metrics},
            "yolo_v4_lstm_v4_shadow": {"yolo_metrics": yolo_v4_metrics, "lstm_metrics": lstm_v4_metrics, "provider": "shadow"},
            "yolo_v4_lstm_v4_active_trial": {
                "eligible": bool(lstm_v4_metrics.get("onnx_validation", {}).get("passed")) and (MODEL_DIR / "yolo_fall_detector_v4_best.pt").exists(),
                "provider": "onnx_lstm",
                "scope": "limited fixed-camera trial only",
            },
        },
        "inventory_gates": inventory.get("gates", {}),
        "promotion_decision": "limited_trial_only",
        "production_provider": "mock/rules",
        "recommended_runtime_provider": "shadow",
        "notes": [
            "Phase 7 artifacts are versioned and do not overwrite v3.",
            "Do not promote onnx_lstm to default until field ADL false positives and confirmed recall pass gate.",
        ],
    }
    write_json(EVAL_DIR / "phase7_v4_full_comparison_001.json", payload)
    report = [
        "# Phase 7 v4 Full Comparison Report",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Decision",
        "",
        "- Production provider remains `mock/rules`.",
        "- Recommended runtime provider remains `shadow`.",
        "- v4 `onnx_lstm` is limited trial only.",
        "",
        "## Artifacts",
        "",
        f"- YOLO v4 metrics: `{MODEL_DIR / 'yolo_fall_detector_v4_metrics.json'}`",
        f"- LSTM v4 metrics: `{MODEL_DIR / 'fall_lstm_v4_metrics.json'}`",
        f"- Dataset inventory: `{EVAL_DIR / 'phase7_dataset_inventory_001.json'}`",
        "",
        "## Gates",
        "",
    ]
    for key, value in payload["inventory_gates"].items():
        report.append(f"- {key}: `{value}`")
    (DOC_DIR / "phase7_v4_full_comparison_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "comparison": str(EVAL_DIR / "phase7_v4_full_comparison_001.json")}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Phase 7 v4 data manifests and reports.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="Inventory datasets and generate Phase 7 manifests.")
    prepare.set_defaults(func=command_prepare)
    comparison = sub.add_parser("comparison", help="Generate final v4 comparison report from available metrics.")
    comparison.set_defaults(func=command_comparison)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
