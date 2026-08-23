from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DATASETS_ROOT = ROOT / "datasets"
OUTPUT_DIR = DATASETS_ROOT / "fall_hint_v3_balanced_hardcase_202607"

SCAN_DIRS = [
    DATASETS_ROOT / "fall_hint_v2_clean_reviewed_only_noaug_20260703",
    DATASETS_ROOT / "fall_false_positive_bank_202607",
    DATASETS_ROOT / "fall_hint_acceptance_eval_202607",
    DATASETS_ROOT / "fall_acceptance_eval_202607",
    DATASETS_ROOT / "acceptance_eval_202607",
    DATASETS_ROOT / "fall_hint_v3_acceptance_202607",
    DATASETS_ROOT / "fall_hint_acceptance_fixed_202607_v1",
    DATASETS_ROOT / "fall_hint_v2_reviewed_all_b001_b031",
    DATASETS_ROOT / "fall_hint_v2_reviewed_all_b001_b029",
    DATASETS_ROOT,
]

POSITIVE_DATASET_DIR = DATASETS_ROOT / "fall_hint_v2_clean_reviewed_only_noaug_20260703"
FALSE_POSITIVE_BANK_DIR = DATASETS_ROOT / "fall_false_positive_bank_202607"

SOURCE_CLASS_NAMES = [
    "falling",
    "fallen",
    "lying",
    "sitting",
    "bending",
    "kneeling",
    "standing",
]
TARGET_CLASS_NAMES = [
    "standing",
    "fallen",
    "sitting",
    "lying",
    "falling",
    "kneeling",
    "bending",
]
TARGET_CLASS_TO_ID = {name: idx for idx, name in enumerate(TARGET_CLASS_NAMES)}
SOURCE_TO_TARGET_ID = {
    source_idx: TARGET_CLASS_TO_ID[name]
    for source_idx, name in enumerate(SOURCE_CLASS_NAMES)
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
CRITICAL_CLASS_NAMES = ["falling", "fallen", "sitting", "lying", "kneeling", "bending"]
HARD_NEGATIVE_CATEGORY_FALLBACK = {
    "sitting_as_fall": "sitting",
    "bending_as_fall": "bending",
    "kneeling_as_fall": "kneeling",
    "lying_adl_as_fall": "lying",
    "low_posture": "standing",
}
EMPTY_CATEGORIES = {"empty_scene"}
ISO_NOW = datetime.now().isoformat(timespec="seconds")


@dataclass
class CandidateItem:
    source_kind: str
    source_dataset: str
    source_image_path: Path
    source_label_path: Path
    output_source_label_path: Path
    output_source_image_path: Path
    source_batch: str
    source_file: str
    source_category: str
    group_id: str
    reason: str
    class_names: tuple[str, ...]
    label_lines: list[str]
    is_hard_negative: bool
    is_acceptance: bool
    is_empty_scene: bool
    metadata: dict[str, str] = field(default_factory=dict)
    image_hash: str = ""
    width: int = 0
    height: int = 0
    image_ext: str = ""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        ordered: list[str] = []
        for row in rows:
            for key in row:
                if key not in ordered:
                    ordered.append(key)
        fieldnames = ordered
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_image_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(26)
    if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        return width, height
    if header[:2] == b"\xff\xd8":
        return read_jpeg_size(path)
    return 0, 0


def read_jpeg_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        handle.read(2)
        while True:
            marker_prefix = handle.read(1)
            if not marker_prefix:
                return 0, 0
            if marker_prefix != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if marker in {b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"}:
                length = int.from_bytes(handle.read(2), "big")
                _precision = handle.read(1)
                height = int.from_bytes(handle.read(2), "big")
                width = int.from_bytes(handle.read(2), "big")
                return width, height
            if marker in {b"\xd8", b"\xd9"}:
                continue
            length_bytes = handle.read(2)
            if len(length_bytes) != 2:
                return 0, 0
            length = int.from_bytes(length_bytes, "big")
            if length < 2:
                return 0, 0
            handle.seek(length - 2, 1)


def normalize_text(value: str) -> str:
    return value.strip().lower()


def stem_without_frame_suffix(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[_-](?:frame)?\d{1,6}$", "", stem)
    stem = re.sub(r"_\d{6}$", "", stem)
    return stem


def make_group_id(*parts: str) -> str:
    for part in parts:
        text = (part or "").strip()
        if not text:
            continue
        normalized = text.replace("\\", "/").lower()
        if "/" in normalized:
            return normalized
        return stem_without_frame_suffix(normalized)
    return "unknown_group"


def parse_source_yolo_label(path: Path) -> tuple[list[tuple[int, float, float, float, float]], str]:
    if not path.exists():
        return [], "missing_label"
    boxes: list[tuple[int, float, float, float, float]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            return [], f"line_{line_no}_bad_column_count"
        try:
            class_id = int(float(parts[0]))
            x_center, y_center, width, height = [float(item) for item in parts[1:]]
        except ValueError:
            return [], f"line_{line_no}_non_numeric"
        if class_id < 0 or class_id >= len(SOURCE_CLASS_NAMES):
            return [], f"line_{line_no}_bad_class_{class_id}"
        if not (0.0 <= x_center <= 1.0 and 0.0 <= y_center <= 1.0 and 0.0 < width <= 1.0 and 0.0 < height <= 1.0):
            return [], f"line_{line_no}_bad_bbox"
        boxes.append((class_id, x_center, y_center, width, height))
    return boxes, ""


def validate_target_label_lines(lines: Iterable[str]) -> tuple[tuple[str, ...], str]:
    class_names: list[str] = []
    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            return tuple(), f"line_{line_no}_bad_column_count"
        try:
            class_id = int(parts[0])
            x_center, y_center, width, height = [float(item) for item in parts[1:]]
        except ValueError:
            return tuple(), f"line_{line_no}_non_numeric"
        if class_id < 0 or class_id >= len(TARGET_CLASS_NAMES):
            return tuple(), f"line_{line_no}_bad_class_{class_id}"
        if not (0.0 <= x_center <= 1.0 and 0.0 <= y_center <= 1.0 and 0.0 < width <= 1.0 and 0.0 < height <= 1.0):
            return tuple(), f"line_{line_no}_bad_bbox"
        class_names.append(TARGET_CLASS_NAMES[class_id])
    return tuple(class_names), ""


def remap_positive_label(source_label_path: Path) -> tuple[list[str], tuple[str, ...], str]:
    boxes, error = parse_source_yolo_label(source_label_path)
    if error:
        return [], tuple(), error
    lines: list[str] = []
    class_names: list[str] = []
    for class_id, x_center, y_center, width, height in boxes:
        target_id = SOURCE_TO_TARGET_ID[class_id]
        lines.append(f"{target_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}")
        class_names.append(TARGET_CLASS_NAMES[target_id])
    return lines, tuple(class_names), ""


def remap_hard_negative_label(
    row: dict[str, str],
    allow_slow_fall_acceptance: bool = False,
) -> tuple[list[str], tuple[str, ...], bool, str]:
    category = row.get("category", "").strip()
    reviewed_class = row.get("reviewed_class", "").strip()
    reviewed_key = normalize_text(reviewed_class)
    source_label_path = Path(row.get("source_label_path", ""))
    if category in EMPTY_CATEGORIES:
        return [], tuple(), True, ""
    resolved_class_name = ""
    if category == "slow_fall_like":
        if allow_slow_fall_acceptance and reviewed_key in TARGET_CLASS_TO_ID:
            resolved_class_name = reviewed_key
        else:
            return [], tuple(), False, "slow_fall_like_not_allowed_in_train_val"
    if category != "slow_fall_like":
        if reviewed_key == "__empty__":
            return [], tuple(), True, ""
        if reviewed_key in TARGET_CLASS_TO_ID:
            resolved_class_name = reviewed_key
        elif category in HARD_NEGATIVE_CATEGORY_FALLBACK:
            resolved_class_name = HARD_NEGATIVE_CATEGORY_FALLBACK[category]
        else:
            return [], tuple(), False, "unknown_reviewed_class_and_category"

    boxes, error = parse_source_yolo_label(source_label_path)
    if error:
        return [], tuple(), False, error
    if not boxes:
        return [], tuple(), False, "empty_label_but_not_empty_scene"

    target_id = TARGET_CLASS_TO_ID[resolved_class_name]
    lines = [
        f"{target_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"
        for _, x_center, y_center, width, height in boxes
    ]
    return lines, tuple([resolved_class_name] * len(lines)), False, ""


def discover_acceptance_dataset() -> Path | None:
    candidates: list[tuple[bool, bool, float, Path]] = []
    for path in SCAN_DIRS:
        if not path.exists() or not path.is_dir():
            continue
        manifest = path / "manifest.csv"
        summary = path / "summary.json"
        if manifest.exists():
            candidates.append(
                (
                    summary.exists(),
                    manifest.exists(),
                    path.stat().st_mtime,
                    path,
                )
            )
    filtered = [
        item
        for item in candidates
        if item[3].name in {
            "fall_hint_acceptance_fixed_202607_v1",
            "fall_hint_acceptance_eval_202607",
            "fall_acceptance_eval_202607",
            "acceptance_eval_202607",
            "fall_hint_v3_acceptance_202607",
        }
    ]
    if not filtered:
        return None
    filtered.sort(key=lambda item: (item[0], item[1], item[2], item[3].name), reverse=True)
    return filtered[0][3]


def build_positive_lookup(manifest_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for row in manifest_rows:
        image_rel = row.get("image", "")
        image_path = (POSITIVE_DATASET_DIR / image_rel).resolve()
        lookup[str(image_path)] = row
    return lookup


def build_bank_lookup(manifest_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for row in manifest_rows:
        bank_id = row.get("bank_id", "")
        if bank_id:
            lookup[bank_id] = row
    return lookup


def parse_bank_id_from_notes(notes: str) -> str:
    match = re.search(r"bank_id=([A-Za-z0-9_]+)", notes or "")
    return match.group(1) if match else ""


def build_acceptance_candidates(
    acceptance_dir: Path | None,
    positive_lookup: dict[str, dict[str, str]],
    bank_lookup: dict[str, dict[str, str]],
    unresolved_rows: list[dict[str, object]],
) -> list[CandidateItem]:
    if acceptance_dir is None:
        return []

    items: list[CandidateItem] = []
    for row in read_csv(acceptance_dir / "manifest.csv"):
        target_image_path = Path(row.get("target_image_path", ""))
        target_label_path = Path(row.get("target_label_path", ""))
        source_dataset = row.get("source_dataset", "")
        source_image_path = Path(row.get("source_image_path", ""))
        source_label_path = Path(row.get("source_label_path", ""))
        category = row.get("category", "")
        notes = row.get("notes", "")
        should_trigger = normalize_text(row.get("should_trigger_fall_alarm", "false")) == "true"

        group_id = ""
        source_batch = ""
        source_file = ""
        label_lines: list[str] = []
        class_names: tuple[str, ...] = tuple()
        is_empty_scene = category == "empty_scene"
        reason = row.get("reason", "")

        if source_dataset.startswith("fall_false_positive_bank_202607"):
            bank_id = parse_bank_id_from_notes(notes)
            bank_row = bank_lookup.get(bank_id)
            if not bank_row:
                unresolved_rows.append(
                    {
                        "source_image_path": str(source_image_path),
                        "source_label_path": str(source_label_path),
                        "source_dataset": source_dataset,
                        "source_category": category,
                        "issue_type": "missing_bank_lookup",
                        "issue_detail": f"bank_id={bank_id or 'unknown'} not found in false-positive manifest",
                        "suggested_action": "repair acceptance source linkage",
                    }
                )
                continue
            source_file = bank_row.get("source_file", "")
            source_batch = bank_row.get("source_batch", "")
            group_id = make_group_id(
                source_file,
                source_image_path.name,
            )
            label_lines, class_names, derived_empty, error = remap_hard_negative_label(
                bank_row,
                allow_slow_fall_acceptance=True,
            )
            if error:
                unresolved_rows.append(
                    {
                        "source_image_path": str(source_image_path),
                        "source_label_path": str(source_label_path),
                        "source_dataset": source_dataset,
                        "source_category": category,
                        "issue_type": "acceptance_label_remap_failed",
                        "issue_detail": error,
                        "suggested_action": "repair bank row or source label before reuse",
                    }
                )
                continue
            is_empty_scene = derived_empty
        else:
            positive_row = positive_lookup.get(str(source_image_path.resolve()))
            if not positive_row:
                unresolved_rows.append(
                    {
                        "source_image_path": str(source_image_path),
                        "source_label_path": str(source_label_path),
                        "source_dataset": source_dataset,
                        "source_category": category,
                        "issue_type": "missing_positive_lookup",
                        "issue_detail": "source_image_path not found in clean reviewed manifest",
                        "suggested_action": "repair acceptance positive source linkage",
                    }
                )
                continue
            source_batch = positive_row.get("source_batch_id", "")
            source_file = positive_row.get("source_video", "")
            group_id = make_group_id(
                positive_row.get("source_video", ""),
                positive_row.get("video_id", ""),
                f"{source_batch}:{positive_row.get('source_original_image', '')}",
            )
            label_lines, class_names, error = remap_positive_label(source_label_path)
            if error:
                unresolved_rows.append(
                    {
                        "source_image_path": str(source_image_path),
                        "source_label_path": str(source_label_path),
                        "source_dataset": source_dataset,
                        "source_category": category,
                        "issue_type": "acceptance_positive_label_remap_failed",
                        "issue_detail": error,
                        "suggested_action": "repair positive label before acceptance reuse",
                    }
                )
                continue
            is_empty_scene = len(label_lines) == 0

        if not target_image_path.exists():
            unresolved_rows.append(
                {
                    "source_image_path": str(source_image_path),
                    "source_label_path": str(source_label_path),
                    "source_dataset": source_dataset,
                    "source_category": category,
                    "issue_type": "missing_acceptance_image",
                    "issue_detail": str(target_image_path),
                    "suggested_action": "rebuild acceptance dataset",
                }
            )
            continue

        image_hash = sha256_file(target_image_path)
        width, height = read_image_size(target_image_path)
        items.append(
            CandidateItem(
                source_kind="acceptance",
                source_dataset=source_dataset,
                source_image_path=source_image_path,
                source_label_path=source_label_path,
                output_source_label_path=target_label_path,
                output_source_image_path=target_image_path,
                source_batch=source_batch,
                source_file=source_file,
                source_category=category,
                group_id=group_id or make_group_id(target_image_path.name),
                reason=reason,
                class_names=class_names,
                label_lines=label_lines,
                is_hard_negative=normalize_text(row.get("is_hard_negative", "false")) == "true",
                is_acceptance=True,
                is_empty_scene=is_empty_scene,
                metadata={
                    "acceptance_id": row.get("acceptance_id", ""),
                    "expected_behavior": row.get("expected_behavior", ""),
                    "should_trigger_fall_alarm": str(should_trigger).lower(),
                    "notes": notes,
                },
                image_hash=image_hash,
                width=width,
                height=height,
                image_ext=target_image_path.suffix.lower(),
            )
        )
    return items


def build_positive_candidates(
    acceptance_group_ids: set[str],
    acceptance_hashes: set[str],
    duplicate_rows: list[dict[str, object]],
    unresolved_rows: list[dict[str, object]],
) -> tuple[list[CandidateItem], list[dict[str, str]]]:
    manifest_rows = read_csv(POSITIVE_DATASET_DIR / "meta" / "manifest.csv")
    items: list[CandidateItem] = []
    skipped: list[dict[str, str]] = []
    seen_hashes: set[str] = set(acceptance_hashes)

    for row in manifest_rows:
        image_path = (POSITIVE_DATASET_DIR / row.get("image", "")).resolve()
        label_path = (POSITIVE_DATASET_DIR / row.get("label", "")).resolve()
        if not image_path.exists():
            unresolved_rows.append(
                {
                    "source_image_path": str(image_path),
                    "source_label_path": str(label_path),
                    "source_dataset": POSITIVE_DATASET_DIR.name,
                    "source_category": row.get("class_names", ""),
                    "issue_type": "missing_image",
                    "issue_detail": "clean reviewed image missing",
                    "suggested_action": "rebuild clean reviewed dataset",
                }
            )
            continue

        label_lines, class_names, error = remap_positive_label(label_path)
        if error:
            unresolved_rows.append(
                {
                    "source_image_path": str(image_path),
                    "source_label_path": str(label_path),
                    "source_dataset": POSITIVE_DATASET_DIR.name,
                    "source_category": row.get("class_names", ""),
                    "issue_type": "positive_label_remap_failed",
                    "issue_detail": error,
                    "suggested_action": "repair source label",
                }
            )
            continue

        group_id = make_group_id(
            row.get("source_video", ""),
            row.get("video_id", ""),
            f"{row.get('source_batch_id', '')}:{row.get('source_original_image', '')}",
        )
        image_hash = sha256_file(image_path)
        if group_id in acceptance_group_ids:
            skipped.append(
                {
                    "source_image_path": str(image_path),
                    "source_label_path": str(label_path),
                    "source_dataset": POSITIVE_DATASET_DIR.name,
                    "reason": "excluded_due_to_acceptance_group_overlap",
                }
            )
            continue
        if image_hash in seen_hashes:
            duplicate_rows.append(
                {
                    "kept_source": "acceptance_or_previous",
                    "dropped_source": str(image_path),
                    "image_hash": image_hash,
                    "reason": "duplicate_image_hash",
                }
            )
            continue
        seen_hashes.add(image_hash)
        width, height = read_image_size(image_path)
        items.append(
            CandidateItem(
                source_kind="positive",
                source_dataset=POSITIVE_DATASET_DIR.name,
                source_image_path=image_path,
                source_label_path=label_path,
                output_source_label_path=label_path,
                output_source_image_path=image_path,
                source_batch=row.get("source_batch_id", ""),
                source_file=row.get("source_video", ""),
                source_category=row.get("class_names", ""),
                group_id=group_id,
                reason="clean_reviewed_positive",
                class_names=class_names,
                label_lines=label_lines,
                is_hard_negative=False,
                is_acceptance=False,
                is_empty_scene=False,
                metadata={
                    "original_split": row.get("split", ""),
                    "source_original_image": row.get("source_original_image", ""),
                    "video_id": row.get("video_id", ""),
                },
                image_hash=image_hash,
                width=width,
                height=height,
                image_ext=image_path.suffix.lower(),
            )
        )
    return items, skipped


def build_hard_negative_candidates(
    split_name: str,
    subset_path: Path,
    bank_lookup: dict[str, dict[str, str]],
    assigned_group_to_split: dict[str, str],
    acceptance_group_ids: set[str],
    acceptance_hashes: set[str],
    duplicate_rows: list[dict[str, object]],
    unresolved_rows: list[dict[str, object]],
) -> tuple[list[CandidateItem], list[dict[str, str]]]:
    items: list[CandidateItem] = []
    skipped: list[dict[str, str]] = []
    seen_hashes: set[str] = set(acceptance_hashes)

    for row in read_csv(subset_path):
        bank_id = row.get("bank_id", "")
        bank_row = bank_lookup.get(bank_id)
        if not bank_row:
            unresolved_rows.append(
                {
                    "source_image_path": row.get("source_image_path", ""),
                    "source_label_path": row.get("source_label_path", ""),
                    "source_dataset": FALSE_POSITIVE_BANK_DIR.name,
                    "source_category": row.get("category", ""),
                    "issue_type": "missing_bank_lookup",
                    "issue_detail": f"subset bank_id missing from bank manifest: {bank_id}",
                    "suggested_action": "repair subset export",
                }
            )
            continue

        image_path = Path(bank_row.get("bank_image_path", ""))
        label_path = Path(bank_row.get("bank_label_path", ""))
        source_image_path = Path(bank_row.get("source_image_path", ""))
        source_label_path = Path(bank_row.get("source_label_path", ""))
        group_id = make_group_id(
            bank_row.get("source_file", ""),
            source_image_path.name,
        )

        if group_id in acceptance_group_ids:
            skipped.append(
                {
                    "source_image_path": str(source_image_path),
                    "source_label_path": str(source_label_path),
                    "source_dataset": FALSE_POSITIVE_BANK_DIR.name,
                    "reason": "excluded_due_to_acceptance_group_overlap",
                }
            )
            continue
        existing_split = assigned_group_to_split.get(group_id)
        if existing_split and existing_split != split_name:
            skipped.append(
                {
                    "source_image_path": str(source_image_path),
                    "source_label_path": str(source_label_path),
                    "source_dataset": FALSE_POSITIVE_BANK_DIR.name,
                    "reason": f"excluded_due_to_group_leakage_with_{existing_split}",
                }
            )
            continue

        if not image_path.exists():
            unresolved_rows.append(
                {
                    "source_image_path": str(source_image_path),
                    "source_label_path": str(source_label_path),
                    "source_dataset": FALSE_POSITIVE_BANK_DIR.name,
                    "source_category": bank_row.get("category", ""),
                    "issue_type": "missing_image",
                    "issue_detail": str(image_path),
                    "suggested_action": "rebuild false-positive bank",
                }
            )
            continue

        label_lines, class_names, is_empty_scene, error = remap_hard_negative_label(bank_row)
        if error:
            unresolved_rows.append(
                {
                    "source_image_path": str(source_image_path),
                    "source_label_path": str(source_label_path),
                    "source_dataset": FALSE_POSITIVE_BANK_DIR.name,
                    "source_category": bank_row.get("category", ""),
                    "issue_type": "hard_negative_label_remap_failed",
                    "issue_detail": error,
                    "suggested_action": "repair bank label or keep in acceptance only",
                }
            )
            continue

        image_hash = sha256_file(image_path)
        if image_hash in seen_hashes:
            duplicate_rows.append(
                {
                    "kept_source": "acceptance_or_previous",
                    "dropped_source": str(image_path),
                    "image_hash": image_hash,
                    "reason": "duplicate_image_hash",
                }
            )
            continue
        seen_hashes.add(image_hash)
        width, height = read_image_size(image_path)
        items.append(
            CandidateItem(
                source_kind="hard_negative",
                source_dataset=FALSE_POSITIVE_BANK_DIR.name,
                source_image_path=source_image_path,
                source_label_path=source_label_path,
                output_source_label_path=label_path,
                output_source_image_path=image_path,
                source_batch=bank_row.get("source_batch", ""),
                source_file=bank_row.get("source_file", ""),
                source_category=bank_row.get("category", ""),
                group_id=group_id,
                reason=bank_row.get("reason", ""),
                class_names=class_names,
                label_lines=label_lines,
                is_hard_negative=True,
                is_acceptance=False,
                is_empty_scene=is_empty_scene,
                metadata={
                    "bank_id": bank_id,
                    "subset": split_name,
                    "reviewed_class": bank_row.get("reviewed_class", ""),
                    "original_class": bank_row.get("original_class", ""),
                },
                image_hash=image_hash,
                width=width,
                height=height,
                image_ext=image_path.suffix.lower(),
            )
        )
        assigned_group_to_split[group_id] = split_name
    return items, skipped


def group_items(items: list[CandidateItem]) -> dict[str, list[CandidateItem]]:
    groups: dict[str, list[CandidateItem]] = defaultdict(list)
    for item in items:
        groups[item.group_id].append(item)
    return groups


def class_counter_from_items(items: Iterable[CandidateItem]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in items:
        counts.update(item.class_names)
    return counts


def assign_groups_for_seed(groups: dict[str, list[CandidateItem]], seed: int) -> dict[str, list[CandidateItem]]:
    group_entries = list(groups.items())
    group_entries.sort(
        key=lambda entry: hashlib.sha256(f"{seed}|{entry[0]}".encode("utf-8")).hexdigest()
    )
    total_items = sum(len(group_items_list) for _, group_items_list in group_entries)
    targets = {
        "train": int(total_items * 0.70),
        "val": int(total_items * 0.15),
        "test": total_items - int(total_items * 0.70) - int(total_items * 0.15),
    }
    splits: dict[str, list[CandidateItem]] = {"train": [], "val": [], "test": []}
    for _, group_items_list in group_entries:
        deficits = {name: targets[name] - len(splits[name]) for name in splits}
        chosen = max(deficits, key=lambda name: (deficits[name], -len(splits[name]), name))
        if deficits[chosen] <= 0:
            chosen = min(
                splits,
                key=lambda name: (
                    len(splits[name]) / max(1, targets[name]),
                    len(splits[name]),
                    name,
                ),
            )
        splits[chosen].extend(group_items_list)
    return splits


def evaluate_positive_split(splits: dict[str, list[CandidateItem]]) -> tuple[int, int, int, int, list[str]]:
    total_counts = class_counter_from_items(
        item for split_items in splits.values() for item in split_items
    )
    test_counts = class_counter_from_items(splits["test"])
    val_counts = class_counter_from_items(splits["val"])
    shortfall_classes: list[str] = []
    total_shortfall = 0
    val_shortfall = 0
    for class_name in CRITICAL_CLASS_NAMES:
        total = total_counts.get(class_name, 0)
        desired_test = 20 if total >= 20 else min(total, 5)
        if test_counts.get(class_name, 0) < desired_test:
            deficit = desired_test - test_counts.get(class_name, 0)
            total_shortfall += deficit
            shortfall_classes.append(class_name)
        desired_val = 10 if total >= 10 else min(total, 3)
        if val_counts.get(class_name, 0) < desired_val:
            val_shortfall += desired_val - val_counts.get(class_name, 0)
    total_items = sum(len(items) for items in splits.values())
    target_counts = {
        "train": int(total_items * 0.70),
        "val": int(total_items * 0.15),
        "test": total_items - int(total_items * 0.70) - int(total_items * 0.15),
    }
    split_deviation = sum(abs(len(splits[name]) - target_counts[name]) for name in splits)
    return total_shortfall, val_shortfall, split_deviation, len(shortfall_classes), shortfall_classes


def choose_best_positive_split(items: list[CandidateItem]) -> tuple[dict[str, list[CandidateItem]], list[str], int]:
    groups = group_items(items)
    best_score: tuple[int, int, int, int] | None = None
    best_splits: dict[str, list[CandidateItem]] | None = None
    best_shortfalls: list[str] = []
    best_seed = 0
    for seed in range(512):
        candidate_splits = assign_groups_for_seed(groups, seed)
        score = evaluate_positive_split(candidate_splits)
        score_key = score[:4]
        if best_score is None or score_key < best_score:
            best_score = score_key
            best_splits = candidate_splits
            best_shortfalls = score[4]
            best_seed = seed
            if score_key == (0, 0, 0, 0):
                break
    if best_splits is None:
        raise RuntimeError("failed to produce positive split")
    return best_splits, best_shortfalls, best_seed


def ensure_clean_output(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    for split in ["train", "val", "test"]:
        (path / split / "images").mkdir(parents=True, exist_ok=True)
        (path / split / "labels").mkdir(parents=True, exist_ok=True)
    (path / "acceptance" / "images").mkdir(parents=True, exist_ok=True)
    (path / "acceptance" / "labels").mkdir(parents=True, exist_ok=True)


def write_item_to_split(output_dir: Path, split: str, item: CandidateItem, index: int) -> tuple[str, str]:
    image_name = f"{split}_{index:06d}{item.image_ext or item.output_source_image_path.suffix.lower()}"
    label_name = f"{split}_{index:06d}.txt"
    image_target = output_dir / split / "images" / image_name
    label_target = output_dir / split / "labels" / label_name
    shutil.copy2(item.output_source_image_path, image_target)
    label_target.write_text(
        ("\n".join(item.label_lines) + "\n") if item.label_lines else "",
        encoding="utf-8",
    )
    return str(image_target.resolve()), str(label_target.resolve())


def build_leakage_rows(items_by_split: dict[str, list[CandidateItem]]) -> tuple[list[dict[str, object]], int]:
    groups_presence: dict[str, set[str]] = defaultdict(set)
    for split, split_items in items_by_split.items():
        for item in split_items:
            groups_presence[item.group_id].add(split)

    rows: list[dict[str, object]] = []
    leakage_count = 0
    for group_id, splits in sorted(groups_presence.items()):
        train = "train" in splits
        val = "val" in splits
        test = "test" in splits
        acceptance = "acceptance" in splits
        split_count = sum([train, val, test, acceptance])
        status = "ok"
        note = ""
        if split_count > 1:
            status = "leakage"
            leakage_count += 1
            note = ",".join(sorted(splits))
        rows.append(
            {
                "group_id": group_id,
                "appears_in_train": str(train).lower(),
                "appears_in_val": str(val).lower(),
                "appears_in_test": str(test).lower(),
                "appears_in_acceptance": str(acceptance).lower(),
                "status": status,
                "note": note,
            }
        )
    return rows, leakage_count


def count_split_images(items: list[CandidateItem]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in items:
        for class_name in set(item.class_names):
            counts[class_name] += 1
    return counts


def write_dataset_yaml(output_dir: Path) -> None:
    lines = [
        f"path: {output_dir.as_posix()}",
        "train: train/images",
        "val: val/images",
        "test: test/images",
        "",
        "names:",
    ]
    lines.extend(f"  {idx}: {name}" for idx, name in enumerate(TARGET_CLASS_NAMES))
    lines.append("")
    (output_dir / "dataset.yaml").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ensure_clean_output(OUTPUT_DIR)

    unresolved_rows: list[dict[str, object]] = []
    duplicate_rows: list[dict[str, object]] = []
    build_notes: list[str] = []

    positive_manifest_rows = read_csv(POSITIVE_DATASET_DIR / "meta" / "manifest.csv")
    bank_manifest_rows = read_csv(FALSE_POSITIVE_BANK_DIR / "manifest.csv")
    positive_lookup = build_positive_lookup(positive_manifest_rows)
    bank_lookup = build_bank_lookup(bank_manifest_rows)

    acceptance_dir = discover_acceptance_dataset()
    acceptance_items = build_acceptance_candidates(
        acceptance_dir,
        positive_lookup,
        bank_lookup,
        unresolved_rows,
    )
    acceptance_group_ids = {item.group_id for item in acceptance_items}
    acceptance_hashes = {item.image_hash for item in acceptance_items}

    positive_items, positive_skipped = build_positive_candidates(
        acceptance_group_ids,
        acceptance_hashes,
        duplicate_rows,
        unresolved_rows,
    )
    positive_splits, shortfall_classes, positive_split_seed = choose_best_positive_split(positive_items)
    assigned_group_to_split = {
        item.group_id: split
        for split, split_items in positive_splits.items()
        for item in split_items
    }

    train_hard_negative_items, train_hn_skipped = build_hard_negative_candidates(
        "train",
        FALSE_POSITIVE_BANK_DIR / "subsets" / "train_hard_negative.csv",
        bank_lookup,
        assigned_group_to_split,
        acceptance_group_ids,
        acceptance_hashes,
        duplicate_rows,
        unresolved_rows,
    )
    val_hard_negative_items, val_hn_skipped = build_hard_negative_candidates(
        "val",
        FALSE_POSITIVE_BANK_DIR / "subsets" / "val_hard_negative.csv",
        bank_lookup,
        assigned_group_to_split,
        acceptance_group_ids,
        acceptance_hashes,
        duplicate_rows,
        unresolved_rows,
    )

    items_by_split: dict[str, list[CandidateItem]] = {
        "train": positive_splits["train"] + train_hard_negative_items,
        "val": positive_splits["val"] + val_hard_negative_items,
        "test": positive_splits["test"],
        "acceptance": acceptance_items,
    }

    manifest_rows: list[dict[str, object]] = []
    acceptance_manifest_rows: list[dict[str, object]] = []
    v3_index = 1
    for split in ["train", "val", "test", "acceptance"]:
        for item in items_by_split[split]:
            image_path, label_path = write_item_to_split(OUTPUT_DIR, split, item, v3_index)
            row = {
                "v3_id": f"v3_{v3_index:06d}",
                "split": split,
                "class_id": ",".join(str(TARGET_CLASS_TO_ID[name]) for name in item.class_names),
                "class_name": ",".join(item.class_names),
                "source_image_path": str(item.source_image_path),
                "source_label_path": str(item.source_label_path),
                "v3_image_path": image_path,
                "v3_label_path": label_path,
                "source_dataset": item.source_dataset,
                "source_batch": item.source_batch,
                "source_file": item.source_file,
                "source_category": item.source_category,
                "is_hard_negative": str(item.is_hard_negative).lower(),
                "is_acceptance": str(item.is_acceptance).lower(),
                "is_empty_scene": str(item.is_empty_scene).lower(),
                "is_resolved": "true",
                "group_id": item.group_id,
                "image_hash": item.image_hash,
                "width": item.width,
                "height": item.height,
                "label_exists": "true",
                "image_exists": "true",
                "reason": item.reason,
                "created_at": ISO_NOW,
            }
            manifest_rows.append(row)
            if split == "acceptance":
                acceptance_manifest_rows.append(row)
            v3_index += 1

    leakage_rows, leakage_count = build_leakage_rows(items_by_split)

    split_summary_rows: list[dict[str, object]] = []
    class_counts_total = Counter()
    class_counts_by_split: dict[str, dict[str, int]] = {}
    for split, split_items in items_by_split.items():
        split_class_counter = class_counter_from_items(split_items)
        class_counts_total.update(split_class_counter)
        class_counts_by_split[split] = {
            class_name: split_class_counter.get(class_name, 0)
            for class_name in TARGET_CLASS_NAMES
        }
        split_image_counts = count_split_images(split_items)
        split_hard_negative_count = sum(1 for item in split_items if item.is_hard_negative)
        split_empty_count = sum(1 for item in split_items if item.is_empty_scene)
        split_acceptance_count = sum(1 for item in split_items if item.is_acceptance)
        for class_name in TARGET_CLASS_NAMES:
            split_summary_rows.append(
                {
                    "split": split,
                    "class_name": class_name,
                    "count": split_class_counter.get(class_name, 0),
                    "image_count": split_image_counts.get(class_name, 0),
                    "hard_negative_count": split_hard_negative_count,
                    "empty_scene_count": split_empty_count,
                    "acceptance_count": split_acceptance_count,
                }
            )

    scanned_dirs = [str(path) for path in SCAN_DIRS if path.exists()]
    source_files_json = {
        "scanned_directories": scanned_dirs,
        "positive_dataset": str(POSITIVE_DATASET_DIR),
        "positive_manifest": str(POSITIVE_DATASET_DIR / "meta" / "manifest.csv"),
        "false_positive_bank": str(FALSE_POSITIVE_BANK_DIR),
        "false_positive_manifest": str(FALSE_POSITIVE_BANK_DIR / "manifest.csv"),
        "train_hard_negative_subset": str(FALSE_POSITIVE_BANK_DIR / "subsets" / "train_hard_negative.csv"),
        "val_hard_negative_subset": str(FALSE_POSITIVE_BANK_DIR / "subsets" / "val_hard_negative.csv"),
        "acceptance_dataset": str(acceptance_dir) if acceptance_dir else "",
        "acceptance_manifest": str(acceptance_dir / "manifest.csv") if acceptance_dir else "",
    }

    summary = {
        "dataset_name": OUTPUT_DIR.name,
        "created_at": ISO_NOW,
        "total_items": len(manifest_rows),
        "train_count": len(items_by_split["train"]),
        "val_count": len(items_by_split["val"]),
        "test_count": len(items_by_split["test"]),
        "acceptance_count": len(items_by_split["acceptance"]),
        "class_counts_total": {
            class_name: class_counts_total.get(class_name, 0) for class_name in TARGET_CLASS_NAMES
        },
        "class_counts_by_split": class_counts_by_split,
        "hard_negative_count": sum(1 for row in manifest_rows if row["is_hard_negative"] == "true"),
        "empty_scene_count": sum(1 for row in manifest_rows if row["is_empty_scene"] == "true"),
        "acceptance_only_count": sum(
            1
            for item in acceptance_items
            if item.metadata.get("expected_behavior") == "no_fall_alarm"
        ),
        "unresolved_count": len(unresolved_rows),
        "duplicate_count": len(duplicate_rows),
        "leakage_count": leakage_count,
        "shortfall_classes": shortfall_classes,
        "source_datasets": sorted(
            {
                POSITIVE_DATASET_DIR.name,
                FALSE_POSITIVE_BANK_DIR.name,
                acceptance_dir.name if acceptance_dir else "acceptance_missing",
            }
        ),
        "split_seed": positive_split_seed,
        "safety": {
            "trained_model": False,
            "replaced_weights": False,
            "modified_env": False,
            "modified_production_chain": False,
        },
    }

    write_dataset_yaml(OUTPUT_DIR)
    (OUTPUT_DIR / "class_mapping.json").write_text(
        json.dumps({str(idx): name for idx, name in enumerate(TARGET_CLASS_NAMES)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "source_files.json").write_text(
        json.dumps(source_files_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(
        OUTPUT_DIR / "manifest.csv",
        manifest_rows,
        fieldnames=[
            "v3_id",
            "split",
            "class_id",
            "class_name",
            "source_image_path",
            "source_label_path",
            "v3_image_path",
            "v3_label_path",
            "source_dataset",
            "source_batch",
            "source_file",
            "source_category",
            "is_hard_negative",
            "is_acceptance",
            "is_empty_scene",
            "is_resolved",
            "group_id",
            "image_hash",
            "width",
            "height",
            "label_exists",
            "image_exists",
            "reason",
            "created_at",
        ],
    )
    write_csv(OUTPUT_DIR / "split_summary.csv", split_summary_rows)
    write_csv(
        OUTPUT_DIR / "leakage_report.csv",
        leakage_rows,
        fieldnames=[
            "group_id",
            "appears_in_train",
            "appears_in_val",
            "appears_in_test",
            "appears_in_acceptance",
            "status",
            "note",
        ],
    )
    write_csv(
        OUTPUT_DIR / "unresolved_items.csv",
        unresolved_rows,
        fieldnames=[
            "source_image_path",
            "source_label_path",
            "source_dataset",
            "source_category",
            "issue_type",
            "issue_detail",
            "suggested_action",
        ],
    )
    write_csv(
        OUTPUT_DIR / "duplicate_items.csv",
        duplicate_rows,
        fieldnames=["kept_source", "dropped_source", "image_hash", "reason"],
    )
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    build_log_lines = [
        f"# Fall Hint v3 Build Log",
        "",
        f"- 构建时间: {ISO_NOW}",
        f"- 扫描目录数量: {len(scanned_dirs)}",
        f"- 选择基础 reviewed 数据: {POSITIVE_DATASET_DIR}",
        f"- 选择误报样本库: {FALSE_POSITIVE_BANK_DIR}",
        f"- 选择 acceptance 数据集: {acceptance_dir if acceptance_dir else 'NOT_FOUND'}",
        f"- positive split seed: {positive_split_seed}",
        f"- 导入 clean reviewed 正样本: {len(positive_items)}",
        f"- 导入 train hard negative: {len(train_hard_negative_items)}",
        f"- 导入 val hard negative: {len(val_hard_negative_items)}",
        f"- 导入 acceptance: {len(acceptance_items)}",
        f"- 过滤 positive acceptance-group overlap: {len(positive_skipped)}",
        f"- 过滤 hard negative leakage/overlap: {len(train_hn_skipped) + len(val_hn_skipped)}",
        f"- unresolved 数量: {len(unresolved_rows)}",
        f"- duplicate 数量: {len(duplicate_rows)}",
        f"- leakage 数量: {leakage_count}",
        "",
        "输出文件:",
        "- dataset.yaml",
        "- README.md",
        "- manifest.csv",
        "- summary.json",
        "- build_log.md",
        "- quality_report.md",
        "- split_summary.csv",
        "- leakage_report.csv",
        "- unresolved_items.csv",
        "- duplicate_items.csv",
        "- class_mapping.json",
        "- source_files.json",
        "",
        f"是否可进入下一阶段训练: {'YES' if len(items_by_split['train']) and len(items_by_split['val']) and len(items_by_split['test']) and leakage_count == 0 else 'NO'}",
    ]
    (OUTPUT_DIR / "build_log.md").write_text("\n".join(build_log_lines) + "\n", encoding="utf-8")

    quality_lines = [
        "# Fall Hint v3 Quality Report",
        "",
        "## 数据来源概览",
        f"- clean reviewed: {POSITIVE_DATASET_DIR}",
        f"- false-positive bank: {FALSE_POSITIVE_BANK_DIR}",
        f"- acceptance: {acceptance_dir if acceptance_dir else 'NOT_FOUND'}",
        "",
        "## split 样本数量",
        f"- train: {len(items_by_split['train'])}",
        f"- val: {len(items_by_split['val'])}",
        f"- test: {len(items_by_split['test'])}",
        f"- acceptance: {len(items_by_split['acceptance'])}",
        "",
        "## 类别 box 数量",
    ]
    for class_name in TARGET_CLASS_NAMES:
        quality_lines.append(f"- {class_name}: {class_counts_total.get(class_name, 0)}")
    quality_lines.extend(
        [
            "",
            f"- hard negative 数量: {summary['hard_negative_count']}",
            f"- empty_scene 数量: {summary['empty_scene_count']}",
            f"- acceptance 数量: {len(items_by_split['acceptance'])}",
            f"- duplicate 数量: {len(duplicate_rows)}",
            f"- unresolved 数量: {len(unresolved_rows)}",
            f"- leakage 检查结果: {'PASS' if leakage_count == 0 else 'FAIL'}",
            "",
            "## 类别不足说明",
            f"- shortfall_classes: {', '.join(shortfall_classes) if shortfall_classes else 'none'}",
            "",
            "## 最低训练进入条件",
            f"- train / val / test 均非空: {'YES' if len(items_by_split['train']) and len(items_by_split['val']) and len(items_by_split['test']) else 'NO'}",
            f"- dataset.yaml 存在: {'YES' if (OUTPUT_DIR / 'dataset.yaml').exists() else 'NO'}",
            f"- manifest.csv 非空: {'YES' if manifest_rows else 'NO'}",
            f"- acceptance 未混入 train/val/test: {'YES' if leakage_count == 0 else 'NO'}",
            "- 本轮未训练模型、未替换权重、未修改 .env、未修改正式链路: YES",
        ]
    )
    (OUTPUT_DIR / "quality_report.md").write_text("\n".join(quality_lines) + "\n", encoding="utf-8")

    readme_lines = [
        "# Fall Hint v3 Balanced Hardcase 202607",
        "",
        "## 1. v3 数据集用途",
        "这是为下一阶段候选 Fall Hint 模型训练准备的 v3 数据集。它把干净 reviewed 正样本、误报 hard negative、固定 acceptance 验收集放进同一套可追溯目录体系，但 acceptance 只用于最终验收，不参与训练。",
        "",
        "## 2. 本轮构建背景",
        "当前正式链路仍使用既有较优模型。本轮只做数据集重建，不训练模型，不替换权重，不改 .env，不改生产链路。",
        "",
        "## 3. 数据来源",
        f"- clean reviewed: {POSITIVE_DATASET_DIR}",
        f"- false-positive bank: {FALSE_POSITIVE_BANK_DIR}",
        f"- acceptance: {acceptance_dir if acceptance_dir else 'NOT_FOUND'}",
        "",
        "## 4. 类别定义",
    ]
    for idx, name in enumerate(TARGET_CLASS_NAMES):
        readme_lines.append(f"- {idx}: {name}")
    readme_lines.extend(
        [
            "",
            "## 5. train / val / test / acceptance 划分规则",
            "- train / val / test 由 clean reviewed 正样本重新按 group 划分，并叠加 bank 中 train/val hard negative。",
            "- acceptance 独立复制到 acceptance 目录，不参与训练和验证。",
            "- 为避免泄漏，凡是与 acceptance 共组的正样本或 hard negative，都会被过滤掉。",
            "",
            "## 6. hard negative 使用说明",
            "- train_hard_negative.csv 只进入 train。",
            "- val_hard_negative.csv 只进入 val。",
            "- acceptance_only / acceptance_fixed 只进入 acceptance。",
            "",
            "## 7. acceptance 不参与训练说明",
            "acceptance 目录中的样本不能用于训练、微调、增强、调参或采样。它们只用于候选模型之间的最终对比验收。",
            "",
            "## 8. 数据质量问题",
            f"- unresolved_count: {len(unresolved_rows)}",
            f"- duplicate_count: {len(duplicate_rows)}",
            f"- leakage_count: {leakage_count}",
            f"- shortfall_classes: {', '.join(shortfall_classes) if shortfall_classes else 'none'}",
            "",
            "## 9. 下一阶段如何训练 candidate_v3_a / b / c",
            "- candidate_v3_a: 只用本 v3 train/val/test 做标准训练。",
            "- candidate_v3_b: 在相同数据集基础上调整 hard negative 权重或采样策略。",
            "- candidate_v3_c: 在不触碰 acceptance 的前提下，只改训练超参数或损失配置。",
            "",
            "## 10. 安全声明",
            "本轮没有训练模型，没有替换任何 .pt 权重，没有修改 .env，没有修改正式告警链路。",
        ]
    )
    (OUTPUT_DIR / "README.md").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "acceptance" / "README.md").write_text(
        "\n".join(
            [
                "# Acceptance Split",
                "",
                "这里是 v3 数据体系中的固定验收集副本，仅用于最终验收。",
                "它不参与 train / val / test，也不能用于训练、微调、增强或调参。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    write_csv(OUTPUT_DIR / "acceptance" / "manifest.csv", acceptance_manifest_rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
