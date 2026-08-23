from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = ROOT / "datasets"
DEFAULT_OUTPUT = DATASETS_DIR / "fall_false_positive_bank_202607"
DEFAULT_BATCH = DATASETS_DIR / "fall_hint_v2_raw" / "batch_031_hardcase_audit"

CATEGORIES = [
    "empty_scene",
    "sitting_as_fall",
    "bending_as_fall",
    "kneeling_as_fall",
    "lying_adl_as_fall",
    "sit_to_floor",
    "slow_fall_like",
    "low_posture",
    "occlusion",
    "low_light",
    "uncertain",
]

CLASS_NAMES = {
    0: "falling",
    1: "fallen",
    2: "lying",
    3: "sitting",
    4: "bending",
    5: "kneeling",
    6: "standing",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Fall Hint false-positive sample bank from reviewed batch 031.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-dir", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_label_classes(path: Path) -> list[str]:
    if not path.exists():
        return []
    classes: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        try:
            cls_id = int(float(parts[0]))
        except ValueError:
            continue
        classes.append(CLASS_NAMES.get(cls_id, f"class_{cls_id}"))
    return classes


def image_size(path: Path) -> tuple[int | str, int | str]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        pass
    try:
        import cv2

        image = cv2.imread(str(path))
        if image is None:
            return "", ""
        height, width = image.shape[:2]
        return width, height
    except Exception:
        return "", ""


def classify_item(scene: str, group: str, reviewed_classes: list[str], image_name: str) -> tuple[str, str]:
    text = " ".join([scene, group, image_name, " ".join(reviewed_classes)]).lower()
    if not reviewed_classes or "empty_false_positive" in text:
        return "empty_scene", "reviewed empty hard case / no valid person-fall target"
    if "occlusion" in text or "partial" in text:
        return "occlusion", "occlusion or partial-body hard negative"
    if "low_light" in text or "dark" in text or "blur" in text:
        return "low_light", "low-light or poor-quality hard negative"
    if "sit_to_floor" in text:
        return "sit_to_floor", "sit-to-floor motion similar to fall"
    if "slow_fall" in text:
        return "slow_fall_like", "slow fall-like boundary sample"
    if "sitting" in text or "sitting" in reviewed_classes:
        return "sitting_as_fall", "normal sitting but similar to fallen"
    if "bending" in text or "bending" in reviewed_classes:
        return "bending_as_fall", "normal bending / low head posture but not fall"
    if "kneeling" in text or "kneeling" in reviewed_classes:
        return "kneeling_as_fall", "kneeling or squat-like posture but not fall"
    if "lying" in text or "lying" in reviewed_classes:
        return "lying_adl_as_fall", "normal lying ADL but similar to fallen"
    if "adl_unknown" in text or "low_posture" in text:
        return "low_posture", "low posture ADL hard negative"
    if reviewed_classes and set(reviewed_classes).issubset({"standing"}):
        return "low_posture", "reviewed standing/ADL boundary hard negative"
    if any(cls in {"falling", "fallen"} for cls in reviewed_classes):
        return "slow_fall_like", "reviewed fall-like boundary sample kept for acceptance"
    return "uncertain", "insufficient metadata to assign a narrower false-positive category"


def scan_source_files() -> list[dict[str, Any]]:
    keywords = ["batch_031", "hardcase", "audit", "review", "reviewed", "decision", "decisions", "manifest", "labels", "false_positive", "adl"]
    suffixes = {".csv", ".json", ".jsonl", ".txt", ".md"}
    rows: list[dict[str, Any]] = []
    for path in DATASETS_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        lowered = str(path).lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        rows.append(
            {
                "path": str(path),
                "name": path.name,
                "suffix": path.suffix,
                "size": path.stat().st_size,
                "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
        )
    rows.sort(key=lambda row: (row["path"]))
    return rows


def stable_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.name.encode("utf-8", errors="ignore"))
    digest.update(str(path.stat().st_size).encode("ascii"))
    return digest.hexdigest()


def prepare_output(output: Path, overwrite: bool) -> None:
    if output.exists():
        if not overwrite:
            raise SystemExit(f"output already exists, pass --overwrite to rebuild: {output}")
        shutil.rmtree(output)
    for category in CATEGORIES:
        (output / "images" / category).mkdir(parents=True, exist_ok=True)
        (output / "labels" / category).mkdir(parents=True, exist_ok=True)
    for folder in ["meta", "subsets"]:
        (output / folder).mkdir(parents=True, exist_ok=True)


def split_subsets(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    category_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        category_groups.setdefault(str(row["category"]), []).append(row)

    train: list[dict[str, Any]] = []
    val: list[dict[str, Any]] = []
    acceptance: list[dict[str, Any]] = []
    for category, items in sorted(category_groups.items()):
        items = sorted(items, key=lambda row: row["bank_id"])
        val_count = 0
        if items:
            val_count = max(1, round(len(items) * 0.18))
        acceptance_count = 0
        if category in {"empty_scene", "sitting_as_fall", "bending_as_fall", "kneeling_as_fall", "lying_adl_as_fall", "slow_fall_like", "occlusion", "low_light"}:
            acceptance_count = max(1, min(5, len(items) // 5 if len(items) >= 5 else 1))

        acceptance_ids = {row["bank_id"] for row in items[:acceptance_count]}
        val_candidates = [row for row in items if row["bank_id"] not in acceptance_ids]
        val_ids = {row["bank_id"] for row in val_candidates[:val_count]}
        for row in items:
            if row["bank_id"] in acceptance_ids:
                row["is_acceptance_candidate"] = "true"
                acceptance.append(row)
            elif row["bank_id"] in val_ids:
                val.append(row)
            else:
                train.append(row)
    return train, val, acceptance


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    batch_dir = args.batch_dir.resolve()
    prepare_output(output, args.overwrite)

    frames_dir = batch_dir / "frames"
    review_labels_dir = batch_dir / "human_review" / "labels"
    prelabels_dir = batch_dir / "prelabels" / "hf_human_fall_yolo11_mapped" / "labels"
    meta_dir = batch_dir / "meta"
    frame_manifest_path = meta_dir / "frame_manifest.csv"
    review_summary_path = meta_dir / "review_validation_summary.json"
    review_rows_path = meta_dir / "review_validation_reviewed_rows.csv"

    source_files = scan_source_files()
    (output / "meta" / "source_files.json").write_text(json.dumps(source_files, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "meta" / "class_mapping.json").write_text(json.dumps(CLASS_NAMES, ensure_ascii=False, indent=2), encoding="utf-8")

    frame_manifest = {row.get("image", ""): row for row in read_csv(frame_manifest_path) if row.get("image")}
    review_summary = read_json(review_summary_path)
    reviewed_rows = read_csv(review_rows_path)
    reviewed_images = {row.get("image", "") for row in reviewed_rows if row.get("image")}
    if not reviewed_images:
        reviewed_images = {path.name for path in frames_dir.glob("*") if path.is_file()}

    manifest_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    duplicate_rows: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_names: set[str] = set()
    seen_hashes: dict[str, str] = {}

    for index, image_name in enumerate(sorted(reviewed_images), start=1):
        source_image = frames_dir / image_name
        source_label = review_labels_dir / f"{Path(image_name).stem}.txt"
        source_prelabel = prelabels_dir / f"{Path(image_name).stem}.txt"
        image_exists = source_image.exists()
        label_exists = source_label.exists()
        if not image_exists or not label_exists:
            unresolved_rows.append(
                {
                    "image": image_name,
                    "source_image_path": str(source_image),
                    "source_label_path": str(source_label),
                    "reason": "missing_image_or_label",
                    "image_exists": image_exists,
                    "label_exists": label_exists,
                }
            )
            continue

        path_key = str(source_image.resolve()).lower()
        name_key = source_image.name.lower()
        hash_key = stable_hash(source_image)
        if path_key in seen_paths or name_key in seen_names or hash_key in seen_hashes:
            duplicate_rows.append(
                {
                    "image": image_name,
                    "duplicate_of": seen_hashes.get(hash_key, ""),
                    "reason": "same_path_or_name_or_name_size_hash",
                    "source_image_path": str(source_image),
                }
            )
            continue
        seen_paths.add(path_key)
        seen_names.add(name_key)
        seen_hashes[hash_key] = image_name

        meta = frame_manifest.get(image_name, {})
        reviewed_classes = read_label_classes(source_label)
        original_classes = read_label_classes(source_prelabel)
        category, reason = classify_item(
            scene=meta.get("scene", ""),
            group=meta.get("group", ""),
            reviewed_classes=reviewed_classes,
            image_name=image_name,
        )
        bank_id = f"fpb_{len(manifest_rows) + 1:06d}"
        image_dst = output / "images" / category / f"{bank_id}{source_image.suffix.lower()}"
        label_dst = output / "labels" / category / f"{bank_id}.txt"
        shutil.copy2(source_image, image_dst)
        shutil.copy2(source_label, label_dst)
        width, height = image_size(image_dst)

        is_hard_negative = "false" if any(cls in {"falling", "fallen"} for cls in reviewed_classes) else "true"
        manifest_rows.append(
            {
                "bank_id": bank_id,
                "category": category,
                "source_image_path": str(source_image),
                "source_label_path": str(source_label),
                "bank_image_path": str(image_dst),
                "bank_label_path": str(label_dst),
                "original_class": " ".join(original_classes) if original_classes else "__empty__",
                "reviewed_class": " ".join(reviewed_classes) if reviewed_classes else "__empty__",
                "review_decision": "reviewed",
                "is_hard_negative": is_hard_negative,
                "is_acceptance_candidate": "false",
                "reason": reason,
                "source_batch": "batch_031_hardcase_audit",
                "source_file": meta.get("source_video", ""),
                "image_exists": "true",
                "label_exists": "true",
                "width": width,
                "height": height,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        )

    train_rows, val_rows, acceptance_rows = split_subsets(manifest_rows)
    manifest_fieldnames = [
        "bank_id",
        "category",
        "source_image_path",
        "source_label_path",
        "bank_image_path",
        "bank_label_path",
        "original_class",
        "reviewed_class",
        "review_decision",
        "is_hard_negative",
        "is_acceptance_candidate",
        "reason",
        "source_batch",
        "source_file",
        "image_exists",
        "label_exists",
        "width",
        "height",
        "created_at",
    ]
    write_csv(output / "manifest.csv", manifest_rows, manifest_fieldnames)
    write_csv(output / "meta" / "unresolved_items.csv", unresolved_rows, ["image", "source_image_path", "source_label_path", "reason", "image_exists", "label_exists"])
    write_csv(output / "meta" / "duplicate_items.csv", duplicate_rows, ["image", "duplicate_of", "reason", "source_image_path"])
    write_csv(output / "subsets" / "train_hard_negative.csv", train_rows, manifest_fieldnames)
    write_csv(output / "subsets" / "val_hard_negative.csv", val_rows, manifest_fieldnames)
    write_csv(output / "subsets" / "acceptance_only.csv", acceptance_rows, manifest_fieldnames)

    category_counts = {category: 0 for category in CATEGORIES}
    for row in manifest_rows:
        category_counts[str(row["category"])] += 1
    summary = {
        "bank_name": "fall_false_positive_bank_202607",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_root": str(batch_dir),
        "primary_review_file": str(review_rows_path),
        "review_summary_file": str(review_summary_path),
        "total_items": len(manifest_rows),
        "category_counts": category_counts,
        "hard_negative_count": sum(1 for row in manifest_rows if row["is_hard_negative"] == "true"),
        "acceptance_candidate_count": len(acceptance_rows),
        "unresolved_count": len(unresolved_rows),
        "duplicate_count": len(duplicate_rows),
        "review_summary": review_summary,
        "notes": [
            "Built only from reviewed batch_031_hardcase_audit results.",
            "No model training was run.",
            "No runtime model, .env, or alert-chain configuration was modified.",
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    readme = [
        "# Fall False Positive Bank 202607",
        "",
        "This bank stores reviewed Fall Hint hard-case samples from batch_031_hardcase_audit.",
        "",
        "## Purpose",
        "",
        "The samples are organized for later hard-negative training, validation, and acceptance checks. This build did not train models or replace weights.",
        "",
        "## Source",
        "",
        f"- Source root: `{batch_dir}`",
        f"- Main review file: `{review_rows_path}`",
        f"- Frame manifest: `{frame_manifest_path}`",
        "",
        "## Category Counts",
        "",
        *[f"- {category}: {count}" for category, count in category_counts.items()],
        "",
        "## Subsets",
        "",
        "- `subsets/train_hard_negative.csv`: candidates for later hard-negative training.",
        "- `subsets/val_hard_negative.csv`: holdout validation hard negatives.",
        "- `subsets/acceptance_only.csv`: typical risky samples reserved for acceptance checks.",
        "",
        "## Unresolved",
        "",
        f"- unresolved_count: {len(unresolved_rows)}",
        f"- duplicate_count: {len(duplicate_rows)}",
        "",
        "## Safety",
        "",
        "- Model training: NO",
        "- Weight replacement: NO",
        "- .env modified: NO",
        "- Runtime alert chain modified: NO",
    ]
    (output / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")

    build_log = [
        "# Build Log",
        "",
        f"- Created at: {summary['created_at']}",
        f"- Scanned root: `{DATASETS_DIR}`",
        f"- Source files discovered: {len(source_files)}",
        f"- Primary review file: `{review_rows_path}`",
        f"- Images source: `{frames_dir}`",
        f"- Labels source: `{review_labels_dir}`",
        f"- Imported samples: {len(manifest_rows)}",
        f"- Missing/unresolved samples: {len(unresolved_rows)}",
        f"- Duplicate samples: {len(duplicate_rows)}",
        "",
        "## Category Counts",
        "",
        *[f"- {category}: {count}" for category, count in category_counts.items()],
        "",
        "## Generated Files",
        "",
        "- README.md",
        "- manifest.csv",
        "- summary.json",
        "- build_log.md",
        "- meta/source_files.json",
        "- meta/unresolved_items.csv",
        "- meta/duplicate_items.csv",
        "- meta/class_mapping.json",
        "- subsets/train_hard_negative.csv",
        "- subsets/val_hard_negative.csv",
        "- subsets/acceptance_only.csv",
        "",
        "## Safety",
        "",
        "No model training, weight replacement, .env edit, or runtime-chain edit was performed.",
    ]
    (output / "build_log.md").write_text("\n".join(build_log) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
