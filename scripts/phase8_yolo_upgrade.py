from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_HUB = Path("D:/Program") / "\u6570\u636e\u96c6"
MANIFEST_DIR = DATA_HUB / "manifests"
DOWNLOAD_DIR = DATA_HUB / "downloads"
MODEL_DOWNLOAD_DIR = DATA_HUB / "downloaded_models"
YOLO_MERGED_DIR = DATA_HUB / "yolo_merged"
DOC_DIR = ROOT / "docs"
EVAL_DIR = ROOT / "evaluations"
MODEL_DIR = ROOT / "models"
V3_LAB = Path(r"D:\Program\model_test\fall_detection_model_bundle\v3_upgrade_lab")
V3_DATASETS = V3_LAB / "datasets"


YOLO_SOURCES = [
    {
        "name": "fall_detect_existing",
        "root": V3_DATASETS / "fall_detect_existing",
        "domain": "public_existing",
        "license": "inherited/needs final dataset-source confirmation",
        "usable_for_training": True,
    },
    {
        "name": "fall_detect_v2_recall_existing",
        "root": V3_DATASETS / "fall_detect_v2_recall_existing",
        "domain": "public_existing_recall",
        "license": "inherited/needs final dataset-source confirmation",
        "usable_for_training": True,
    },
    {
        "name": "fall_detect_v3_gmdcsa24_autolabel",
        "root": V3_DATASETS / "fall_detect_v3_gmdcsa24_autolabel",
        "domain": "public_gmdcsa24_autolabel",
        "license": "research/demo use; verify source terms before commercial use",
        "usable_for_training": True,
    },
]


DATASET_CANDIDATES = [
    {
        "name": "UR Fall official",
        "source_url": "https://fenix.ur.edu.pl/~mkepski/ds/uf.html",
        "target": DATA_HUB / "01_公开跌倒视频数据集" / "UR_Fall",
        "license": "CC BY-NC-SA 4.0",
        "download_method": "already linked/local mirror",
        "status": "available_via_existing_link",
        "usable_for_training": True,
        "commercial_allowed": False,
        "notes": "Good smoke/research data; not commercial-production training data without permission.",
    },
    {
        "name": "Le2i / ImViA Fall Dataset",
        "source_url": "https://www.kaggle.com/datasets/tuyenldvn/falldataset-imvia",
        "target": DOWNLOAD_DIR / "le2i_imvia",
        "license": "Kaggle dataset license must be accepted by user",
        "download_method": "kaggle api",
        "status": "blocked_no_kaggle_credentials",
        "usable_for_training": False,
        "commercial_allowed": None,
        "notes": "Requires C:\\Users\\YANG\\.kaggle\\kaggle.json and dataset terms acceptance.",
    },
    {
        "name": "Roboflow UR Fall YOLO export",
        "source_url": "https://universe.roboflow.com/search?q=class%3Afall",
        "target": DOWNLOAD_DIR / "roboflow_ur_fall",
        "license": "per-project Roboflow Universe license",
        "download_method": "roboflow api",
        "status": "blocked_no_roboflow_api_key",
        "usable_for_training": False,
        "commercial_allowed": None,
        "notes": "Requires ROBOFLOW_API_KEY and per-dataset license check.",
    },
    {
        "name": "FPDS",
        "source_url": "https://gram.web.uah.es/data/datasets/fpds/index.html",
        "target": DOWNLOAD_DIR / "fpds",
        "license": "official terms must be checked before training",
        "download_method": "manual official download / possible SharePoint login",
        "status": "blocked_manual_authorization",
        "usable_for_training": False,
        "commercial_allowed": None,
        "notes": "High-value fallen-person still-image data, but direct no-login download was not confirmed.",
    },
    {
        "name": "YifeiYang210 Fall Detection dataset metadata",
        "source_url": "https://github.com/YifeiYang210/Fall_Detection_dataset",
        "target": DOWNLOAD_DIR / "github_fall_detection_dataset_metadata",
        "license": "GitHub repository terms; linked data license must be checked",
        "download_method": "git clone metadata",
        "status": "pending",
        "usable_for_training": False,
        "commercial_allowed": None,
        "notes": "Repository mainly documents Google Drive datasets; use only after license/source confirmation.",
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_dirs() -> None:
    for path in [
        MANIFEST_DIR,
        DOWNLOAD_DIR,
        MODEL_DOWNLOAD_DIR,
        YOLO_MERGED_DIR / "images" / "train",
        YOLO_MERGED_DIR / "images" / "val",
        YOLO_MERGED_DIR / "images" / "test",
        YOLO_MERGED_DIR / "labels" / "train",
        YOLO_MERGED_DIR / "labels" / "val",
        YOLO_MERGED_DIR / "labels" / "test",
        DOC_DIR,
        EVAL_DIR,
        MODEL_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def check_credentials() -> dict[str, Any]:
    return {
        "kaggle_json": str(Path.home() / ".kaggle" / "kaggle.json"),
        "kaggle_json_exists": (Path.home() / ".kaggle" / "kaggle.json").exists(),
        "roboflow_api_key_present": bool(os.environ.get("ROBOFLOW_API_KEY")),
    }


def count_yolo_source(root: Path) -> dict[str, Any]:
    split_counts: dict[str, dict[str, int]] = {}
    for split in ["train", "val", "test"]:
        images = []
        labels = []
        image_dir = root / "images" / split
        label_dir = root / "labels" / split
        if image_dir.exists():
            images = [*image_dir.glob("*.jpg"), *image_dir.glob("*.jpeg"), *image_dir.glob("*.png")]
        if label_dir.exists():
            labels = [*label_dir.glob("*.txt")]
        split_counts[split] = {"images": len(images), "labels": len(labels)}
    return {
        "exists": root.exists(),
        "split_counts": split_counts,
        "total_images": sum(v["images"] for v in split_counts.values()),
        "total_labels": sum(v["labels"] for v in split_counts.values()),
    }


def build_yolo_yaml() -> Path:
    train_dirs: list[str] = []
    val_dirs: list[str] = []
    test_dirs: list[str] = []
    for source in YOLO_SOURCES:
        root = source["root"]
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
        "# Phase 8 YOLO merged training data.",
        "# Absolute paths avoid stale junction aliases and make training reproducible.",
        "path: .",
        "train:",
        *[f"  - {p}" for p in train_dirs],
        "val:",
        *[f"  - {p}" for p in val_dirs],
        "test:",
        *[f"  - {p}" for p in test_dirs],
        "names:",
        *[f"  {idx}: {name}" for idx, name in names.items()],
    ]
    yaml_path = YOLO_MERGED_DIR / "data.yaml"
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yaml_path


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 8 YOLO Data And Training Preparation",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "## Credentials",
        "",
        f"- Kaggle credentials present: {payload['credentials']['kaggle_json_exists']}",
        f"- Roboflow API key present: {payload['credentials']['roboflow_api_key_present']}",
        "",
        "## Dataset Candidates",
        "",
    ]
    for item in payload["dataset_candidates"]:
        lines.append(
            f"- {item['name']}: status={item['status']}, usable={item['usable_for_training']}, license={item['license']}, target={item['target']}"
        )
    lines.extend(["", "## YOLO Sources", ""])
    for item in payload["yolo_sources"]:
        count = item["counts"]
        lines.append(
            f"- {item['name']}: images={count['total_images']}, labels={count['total_labels']}, root={item['root']}"
        )
    lines.extend(
        [
            "",
            "## Training Recommendation",
            "",
            "- Train from a stronger Ultralytics base such as `yolo11s.pt` or continue from the current v4 last checkpoint.",
            "- Keep v3/v4 untouched; export Phase 8 candidate as `models/yolo_fall_detector_v5_best.pt`.",
            "- Do not replace the runtime model until benchmark and real-camera alert tests pass.",
        ]
    )
    return "\n".join(lines) + "\n"


def command_prepare(_: argparse.Namespace) -> None:
    ensure_dirs()
    credentials = check_credentials()
    candidates = []
    for item in DATASET_CANDIDATES:
        copied = dict(item)
        copied["target"] = str(copied["target"])
        candidates.append(copied)
    yolo_sources = []
    for source in YOLO_SOURCES:
        yolo_sources.append(
            {
                "name": source["name"],
                "root": str(source["root"]),
                "domain": source["domain"],
                "license": source["license"],
                "usable_for_training": source["usable_for_training"],
                "counts": count_yolo_source(source["root"]),
            }
        )
    yaml_path = build_yolo_yaml()
    payload = {
        "generated_at": now_iso(),
        "data_hub": str(DATA_HUB),
        "credentials": credentials,
        "dataset_candidates": candidates,
        "yolo_sources": yolo_sources,
        "yolo_data_yaml": str(yaml_path),
    }
    write_json(MANIFEST_DIR / "phase8_dataset_license_manifest.json", payload)
    write_json(EVAL_DIR / "phase8_dataset_inventory_001.json", payload)
    (DOC_DIR / "phase8_yolo_training_report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"ok": True, "yolo_data_yaml": str(yaml_path)}, ensure_ascii=False))


def command_record_model(args: argparse.Namespace) -> None:
    payload = {
        "generated_at": now_iso(),
        "model_path": args.model_path,
        "source": args.source,
        "status": args.status,
        "notes": args.notes,
    }
    write_json(MODEL_DOWNLOAD_DIR / "downloaded_model_manifest.json", payload)
    print(json.dumps(payload, ensure_ascii=False))


def command_select_best(_: argparse.Namespace) -> None:
    benchmark_path = EVAL_DIR / "phase8_yolo_model_benchmark.json"
    if benchmark_path.exists():
        benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    else:
        benchmark = {"models": [], "decision": "no_benchmark_available"}
    write_json(EVAL_DIR / "phase8_yolo_model_selection.json", benchmark)
    print(json.dumps({"ok": True, "selection": str(EVAL_DIR / "phase8_yolo_model_selection.json")}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 8 YOLO fall detector upgrade helpers.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.set_defaults(func=command_prepare)
    record = sub.add_parser("record-model")
    record.add_argument("--model-path", required=True)
    record.add_argument("--source", required=True)
    record.add_argument("--status", required=True)
    record.add_argument("--notes", default="")
    record.set_defaults(func=command_record_model)
    select = sub.add_parser("select-best")
    select.set_defaults(func=command_select_best)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
