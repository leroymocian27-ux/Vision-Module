from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "datasets" / "boundary_pair_repair_pack_20260705"

REVIEWED_FINAL_ROOT = ROOT / "datasets" / "falling_transition_positive_batch_20260705_reviewed_final"
REVIEWED_FINAL_MANIFEST = REVIEWED_FINAL_ROOT / "manifest.csv"
REVIEWED_FINAL_TRANSITIONS = REVIEWED_FINAL_ROOT / "meta" / "class_transition.csv"

REVIEWED_ALL_ROOT = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"
REVIEWED_ALL_MANIFEST = REVIEWED_ALL_ROOT / "meta" / "manifest.csv"

CLEAN_REVIEWED_MANIFEST = ROOT / "datasets" / "fall_hint_v2_clean_reviewed_only_noaug_20260703" / "meta" / "manifest.csv"
V3_MANIFEST = ROOT / "datasets" / "fall_hint_v3_balanced_hardcase_202607" / "manifest.csv"

ACCEPTANCE_MANIFEST = ROOT / "datasets" / "fall_hint_acceptance_fixed_202607_v1" / "manifest.csv"
ACCEPTANCE_ONLY_CSV = ROOT / "datasets" / "fall_false_positive_bank_202607" / "subsets" / "acceptance_only.csv"

FOCUS_CASE_IDS = {"acc_000023", "acc_000024"}
OUTPUT_CATEGORY_ORDER = [
    "kneeling_vs_falling_boundary",
    "bending_vs_fallen_boundary",
    "falling_to_fallen_transition",
    "fallen_low_posture_boundary",
]
TARGET_COUNTS = {
    "kneeling_vs_falling_boundary": 15,
    "bending_vs_fallen_boundary": 18,
    "falling_to_fallen_transition": 12,
    "fallen_low_posture_boundary": 12,
}
OLD_ORDER_NAMES = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
TARGET_CLASS_NAMES = ["standing", "fallen", "sitting", "lying", "falling", "kneeling", "bending"]
OLD_TO_NEW = {0: 4, 1: 1, 2: 3, 3: 2, 4: 6, 5: 5, 6: 0}
SEMANTIC_TO_TARGET = {name: idx for idx, name in enumerate(TARGET_CLASS_NAMES)}


@dataclass
class CandidateItem:
    source_kind: str
    boundary_category: str
    class_name: str
    original_class: str
    reviewed_class: str
    source_dataset: str
    source_image_path: Path
    source_label_path: Path
    source_original_image: str
    source_video: str
    near_miss_pattern: str
    related_failure_case: str
    reason: str
    expected_help: str
    notes: str
    width: int
    height: int


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_row_path(csv_path: Path, value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path if path.exists() else None
    for candidate in [csv_path.parent.parent / value, csv_path.parent / value]:
        if candidate.exists():
            return candidate
    return None


def image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return image.size


def remap_old_order_label_text(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            continue
        old_cls = int(parts[0])
        new_cls = OLD_TO_NEW[old_cls]
        lines.append(f"{new_cls} {' '.join(parts[1:])}")
    return ("\n".join(lines) + "\n") if lines else ""


def parse_single_class_name(text: str) -> str:
    matches = re.findall(r'"?([a-z_]+)"?\s*:\s*\d+', text)
    return matches[0] if matches else ""


def build_test_and_acceptance_exclusions() -> dict[str, Any]:
    acceptance_rows = read_csv(ACCEPTANCE_MANIFEST)

    test_manifest_files_scanned: list[str] = []
    acceptance_manifest_files_scanned = [str(ACCEPTANCE_MANIFEST), str(ACCEPTANCE_ONLY_CSV)]

    test_source_images: set[str] = set()
    test_original_images: set[str] = set()
    test_hashes: set[str] = set()

    for base in [ROOT / "datasets", ROOT / "runs"]:
        for csv_path in base.rglob("*.csv"):
            try:
                rows = read_csv(csv_path)
            except Exception:
                continue
            if not rows:
                continue
            fields = set(rows[0].keys())
            if "split" not in fields and "use_in_acceptance" not in fields and "is_acceptance" not in fields and "acceptance_id" not in fields:
                continue

            file_used = False
            for row in rows:
                split = str(row.get("split", "")).lower()
                use_in_acceptance = str(row.get("use_in_acceptance", "")).lower() == "true"
                is_acceptance = str(row.get("is_acceptance", "")).lower() == "true"
                if split != "test" and not use_in_acceptance and not is_acceptance:
                    continue

                file_used = True
                for key in ["source_original_image", "original_image"]:
                    value = row.get(key, "")
                    if value:
                        test_original_images.add(Path(value).name)

                for key in ["source_image_path", "image", "target_image_path", "v3_image_path", "source_archive_image", "new_image"]:
                    resolved = resolve_row_path(csv_path, row.get(key, ""))
                    if resolved and resolved.exists():
                        test_source_images.add(str(resolved.resolve()))
                        test_hashes.add(sha256_file(resolved))

            if file_used:
                test_manifest_files_scanned.append(str(csv_path))

    acceptance_source_images: set[str] = set()
    acceptance_hashes: set[str] = set()
    focus_case_hashes: set[str] = set()
    focus_case_original_images: set[str] = set()
    focus_case_source_images: set[str] = set()

    for row in acceptance_rows:
        source_image_path = Path(row["source_image_path"])
        target_image_path = Path(row["target_image_path"])
        if source_image_path.exists():
            acceptance_source_images.add(str(source_image_path.resolve()))
            acceptance_hashes.add(sha256_file(source_image_path))
        if target_image_path.exists():
            acceptance_hashes.add(sha256_file(target_image_path))
        if row["acceptance_id"] in FOCUS_CASE_IDS:
            focus_case_hashes.add(row["image_sha256"])
            if source_image_path.exists():
                focus_case_hashes.add(sha256_file(source_image_path))
                focus_case_source_images.add(str(source_image_path.resolve()))
            focus_case_original_images.update(
                match.group(1)
                for match in re.finditer(r"source_original_image=([^;]+)", row.get("notes", ""))
            )

    acceptance_only_paths: set[str] = set()
    for row in read_csv(ACCEPTANCE_ONLY_CSV):
        bank_image_path = Path(row["bank_image_path"])
        if bank_image_path.exists():
            acceptance_only_paths.add(str(bank_image_path.resolve()))

    return {
        "test_source_images": test_source_images,
        "test_original_images": test_original_images,
        "test_hashes": test_hashes,
        "acceptance_source_images": acceptance_source_images,
        "acceptance_hashes": acceptance_hashes,
        "acceptance_only_paths": acceptance_only_paths,
        "focus_case_hashes": focus_case_hashes,
        "focus_case_original_images": focus_case_original_images,
        "focus_case_source_images": focus_case_source_images,
        "test_manifest_files_scanned": test_manifest_files_scanned,
        "acceptance_manifest_files_scanned": acceptance_manifest_files_scanned,
    }


def build_reviewed_final_candidates(exclusions: dict[str, Any]) -> dict[str, list[CandidateItem]]:
    rows = read_csv(REVIEWED_FINAL_MANIFEST)
    hash_cache: dict[str, str] = {}
    buckets: dict[str, list[CandidateItem]] = defaultdict(list)
    for row in rows:
        source_original = row["source_original_image"]
        source_image_path = Path(row["final_image_path"])
        source_label_path = Path(row["final_label_path"])
        if not source_image_path.exists() or not source_label_path.exists():
            continue
        if source_original in exclusions["focus_case_original_images"]:
            continue
        if source_original in exclusions["test_original_images"]:
            continue
        if str(source_image_path.resolve()) in exclusions["focus_case_source_images"]:
            continue
        if str(source_image_path.resolve()) in exclusions["test_source_images"]:
            continue
        image_hash = hash_cache.setdefault(str(source_image_path), sha256_file(source_image_path))
        if image_hash in exclusions["test_hashes"]:
            continue

        original_class = row["original_candidate_class"]
        reviewed_class = row["reviewed_class"]
        near_miss_pattern = row["near_miss_pattern"]
        notes = row.get("notes", "")

        if (
            near_miss_pattern in {"boundary_shift_to_kneeling", "slow_fall_boundary_to_kneeling"}
            or (original_class == "kneeling" and reviewed_class in {"falling", "fallen"})
        ) and reviewed_class in {"falling", "kneeling", "fallen"}:
            buckets["kneeling_vs_falling_boundary"].append(
                CandidateItem(
                    source_kind="reviewed_final",
                    boundary_category="kneeling_vs_falling_boundary",
                    class_name=reviewed_class,
                    original_class=original_class,
                    reviewed_class=reviewed_class,
                    source_dataset="falling_transition_positive_batch_20260705_reviewed_final",
                    source_image_path=source_image_path,
                    source_label_path=source_label_path,
                    source_original_image=source_original,
                    source_video=row["source_video"],
                    near_miss_pattern=near_miss_pattern,
                    related_failure_case="acc_000023_like",
                    reason="reviewed_final near-miss that visually leans toward kneeling during real fall",
                    expected_help="help_reduce_kneeling_shift",
                    notes=notes,
                    width=int(row["width"]),
                    height=int(row["height"]),
                )
            )

        if (
            near_miss_pattern == "boundary_shift_to_bending"
            or (original_class == "bending" and reviewed_class in {"falling", "fallen"})
            or (original_class in {"sitting", "lying"} and reviewed_class == "fallen")
        ) and reviewed_class in {"fallen", "bending", "falling"}:
            buckets["bending_vs_fallen_boundary"].append(
                CandidateItem(
                    source_kind="reviewed_final",
                    boundary_category="bending_vs_fallen_boundary",
                    class_name=reviewed_class,
                    original_class=original_class,
                    reviewed_class=reviewed_class,
                    source_dataset="falling_transition_positive_batch_20260705_reviewed_final",
                    source_image_path=source_image_path,
                    source_label_path=source_label_path,
                    source_original_image=source_original,
                    source_video=row["source_video"],
                    near_miss_pattern=near_miss_pattern,
                    related_failure_case="acc_000024_like",
                    reason="reviewed_final near-miss that visually leans toward bending during real fall",
                    expected_help="help_reduce_bending_shift",
                    notes=notes,
                    width=int(row["width"]),
                    height=int(row["height"]),
                )
            )

        if (
            f"{original_class}->{reviewed_class}"
            in {"falling->fallen", "sitting->fallen", "lying->fallen", "bending->falling", "kneeling->falling", "kneeling->fallen"}
            or near_miss_pattern in {"falling_transition_recall_support", "slow_fall_like_recall_support"}
        ) and reviewed_class in {"falling", "fallen"}:
            buckets["falling_to_fallen_transition"].append(
                CandidateItem(
                    source_kind="reviewed_final",
                    boundary_category="falling_to_fallen_transition",
                    class_name=reviewed_class,
                    original_class=original_class,
                    reviewed_class=reviewed_class,
                    source_dataset="falling_transition_positive_batch_20260705_reviewed_final",
                    source_image_path=source_image_path,
                    source_label_path=source_label_path,
                    source_original_image=source_original,
                    source_video=row["source_video"],
                    near_miss_pattern=near_miss_pattern,
                    related_failure_case="both",
                    reason="reviewed_final transition support sample around falling to fallen changeover",
                    expected_help="help_stabilize_falling_to_fallen_boundary",
                    notes=notes,
                    width=int(row["width"]),
                    height=int(row["height"]),
                )
            )

        if (
            near_miss_pattern in {"low_posture_boundary", "real_fall_low_posture_hold"}
            or (reviewed_class == "fallen" and original_class in {"sitting", "lying", "bending", "kneeling"})
        ) and reviewed_class in {"fallen", "lying", "sitting", "bending", "kneeling"}:
            buckets["fallen_low_posture_boundary"].append(
                CandidateItem(
                    source_kind="reviewed_final",
                    boundary_category="fallen_low_posture_boundary",
                    class_name=reviewed_class,
                    original_class=original_class,
                    reviewed_class=reviewed_class,
                    source_dataset="falling_transition_positive_batch_20260705_reviewed_final",
                    source_image_path=source_image_path,
                    source_label_path=source_label_path,
                    source_original_image=source_original,
                    source_video=row["source_video"],
                    near_miss_pattern=near_miss_pattern,
                    related_failure_case="both",
                    reason="reviewed_final low-posture fall sample useful for fallen vs low-pose stabilization",
                    expected_help="help_stabilize_fallen_low_posture_boundary",
                    notes=notes,
                    width=int(row["width"]),
                    height=int(row["height"]),
                )
            )
    return buckets


def build_reviewed_all_candidates(exclusions: dict[str, Any]) -> dict[str, list[CandidateItem]]:
    rows = read_csv(REVIEWED_ALL_MANIFEST)
    hash_cache: dict[str, str] = {}
    fall_rows: list[dict[str, str]] = []
    by_video_classes: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("group") != "fall":
            continue
        original_image = row["original_image"]
        if original_image in exclusions["focus_case_original_images"] or original_image in exclusions["test_original_images"]:
            continue
        derived_class = parse_single_class_name(row["class_counts"])
        if not derived_class:
            continue
        row["derived_class"] = derived_class
        video_key = row.get("video_id") or row.get("source_video")
        fall_rows.append(row)
        by_video_classes[video_key].add(derived_class)

    kneeling_pair_videos = {video for video, classes in by_video_classes.items() if "falling" in classes and "kneeling" in classes}
    bending_pair_videos = {video for video, classes in by_video_classes.items() if "fallen" in classes and "bending" in classes}
    transition_videos = {video for video, classes in by_video_classes.items() if "falling" in classes and "fallen" in classes}
    low_posture_videos = {
        video
        for video, classes in by_video_classes.items()
        if "fallen" in classes and classes.intersection({"lying", "sitting", "bending", "kneeling"})
    }

    buckets: dict[str, list[CandidateItem]] = defaultdict(list)
    for row in fall_rows:
        source_image_path = REVIEWED_ALL_ROOT / row["new_image"]
        source_label_path = REVIEWED_ALL_ROOT / row["new_label"]
        if not source_image_path.exists() or not source_label_path.exists():
            continue
        if str(source_image_path.resolve()) in exclusions["test_source_images"]:
            continue
        image_hash = hash_cache.setdefault(str(source_image_path), sha256_file(source_image_path))
        if image_hash in exclusions["test_hashes"]:
            continue
        video_key = row.get("video_id") or row.get("source_video")
        class_name = row["derived_class"]
        base_notes = f"reviewed_all fallback candidate; batch={row['batch_id']}; scene={row['scene']}; video_id={video_key}"
        common = dict(
            source_kind="reviewed_all",
            class_name=class_name,
            original_class=class_name,
            reviewed_class=class_name,
            source_dataset="fall_hint_v2_reviewed_all_b001_b029",
            source_image_path=source_image_path,
            source_label_path=source_label_path,
            source_original_image=row["original_image"],
            source_video=row["source_video"],
            near_miss_pattern="video_pair_boundary_heuristic",
            notes=base_notes,
            width=0,
            height=0,
        )

        if video_key in kneeling_pair_videos and class_name in {"falling", "kneeling"}:
            buckets["kneeling_vs_falling_boundary"].append(
                CandidateItem(
                    boundary_category="kneeling_vs_falling_boundary",
                    related_failure_case="acc_000023_like",
                    reason="same fall video contains both falling and kneeling reviewed frames, likely near kneeling/falling boundary",
                    expected_help="help_reduce_kneeling_shift",
                    **common,
                )
            )
        elif class_name in {"falling", "kneeling"} and (
            "transition" in row["original_image"].lower() or class_name == "kneeling"
        ):
            buckets["kneeling_vs_falling_boundary"].append(
                CandidateItem(
                    boundary_category="kneeling_vs_falling_boundary",
                    related_failure_case="acc_000023_like",
                    reason="fall-group transition or kneeling frame kept as fallback for kneeling/falling boundary review",
                    expected_help="help_reduce_kneeling_shift",
                    **common,
                )
            )

        if video_key in bending_pair_videos and class_name in {"fallen", "bending"}:
            buckets["bending_vs_fallen_boundary"].append(
                CandidateItem(
                    boundary_category="bending_vs_fallen_boundary",
                    related_failure_case="acc_000024_like",
                    reason="same fall video contains both fallen and bending reviewed frames, likely near bending/fallen boundary",
                    expected_help="help_reduce_bending_shift",
                    **common,
                )
            )

        if video_key in transition_videos and class_name in {"falling", "fallen"}:
            buckets["falling_to_fallen_transition"].append(
                CandidateItem(
                    boundary_category="falling_to_fallen_transition",
                    related_failure_case="both",
                    reason="same fall video contains both falling and fallen reviewed frames, useful for transition stabilization",
                    expected_help="help_stabilize_falling_to_fallen_boundary",
                    **common,
                )
            )

        if video_key in low_posture_videos and class_name in {"fallen", "lying", "sitting", "bending", "kneeling"}:
            buckets["fallen_low_posture_boundary"].append(
                CandidateItem(
                    boundary_category="fallen_low_posture_boundary",
                    related_failure_case="both",
                    reason="same fall video contains fallen and another low-posture class, useful for low-posture fall boundary review",
                    expected_help="help_stabilize_fallen_low_posture_boundary",
                    **common,
                )
            )
    return buckets


def choose_pack_items(
    reviewed_final_buckets: dict[str, list[CandidateItem]],
    reviewed_all_buckets: dict[str, list[CandidateItem]],
) -> dict[str, list[CandidateItem]]:
    selected: dict[str, list[CandidateItem]] = {category: [] for category in OUTPUT_CATEGORY_ORDER}
    used_source_images: set[str] = set()
    used_original_images: set[str] = set()
    used_source_hashes: set[str] = set()
    hash_cache: dict[str, str] = {}

    def try_add(category: str, item: CandidateItem) -> bool:
        source_key = str(item.source_image_path.resolve())
        source_hash = hash_cache.setdefault(source_key, sha256_file(item.source_image_path))
        if source_key in used_source_images:
            return False
        if item.source_original_image in used_original_images:
            return False
        if source_hash in used_source_hashes:
            return False
        selected[category].append(item)
        used_source_images.add(source_key)
        used_original_images.add(item.source_original_image)
        used_source_hashes.add(source_hash)
        return True

    for category in OUTPUT_CATEGORY_ORDER:
        for item in reviewed_final_buckets.get(category, []):
            if len(selected[category]) >= TARGET_COUNTS[category]:
                break
            try_add(category, item)

        for item in reviewed_all_buckets.get(category, []):
            if len(selected[category]) >= TARGET_COUNTS[category]:
                break
            try_add(category, item)

    return selected


def copy_pack_items(selected: dict[str, list[CandidateItem]]) -> tuple[list[dict[str, object]], list[dict[str, object]], Counter[str], Counter[str]]:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    for category in OUTPUT_CATEGORY_ORDER:
        (OUTPUT_ROOT / "images" / category).mkdir(parents=True, exist_ok=True)
        (OUTPUT_ROOT / "labels" / category).mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, object]] = []
    similarity_rows: list[dict[str, object]] = []
    class_counter: Counter[str] = Counter()
    related_counter: Counter[str] = Counter()
    item_index = 1

    for category in OUTPUT_CATEGORY_ORDER:
        for item in selected[category]:
            item_id = f"bpr_{item_index:04d}"
            image_target = OUTPUT_ROOT / "images" / category / f"{item_id}{item.source_image_path.suffix.lower()}"
            label_target = OUTPUT_ROOT / "labels" / category / f"{item_id}.txt"
            shutil.copy2(item.source_image_path, image_target)
            label_text = remap_old_order_label_text(item.source_label_path.read_text(encoding="utf-8"))
            label_target.write_text(label_text, encoding="utf-8")

            image_sha = sha256_file(image_target)
            label_sha = sha256_file(label_target)
            width, height = item.width, item.height
            if width <= 0 or height <= 0:
                width, height = image_size(image_target)
            manifest_rows.append(
                {
                    "item_id": item_id,
                    "boundary_category": category,
                    "class_name": item.class_name,
                    "original_class": item.original_class,
                    "reviewed_class": item.reviewed_class,
                    "source_dataset": item.source_dataset,
                    "source_image_path": str(item.source_image_path),
                    "source_label_path": str(item.source_label_path),
                    "source_original_image": item.source_original_image,
                    "source_video": item.source_video,
                    "target_image_path": str(image_target),
                    "target_label_path": str(label_target),
                    "related_failure_case": item.related_failure_case,
                    "near_miss_pattern": item.near_miss_pattern,
                    "is_positive_repair": True,
                    "use_in_training_future": False,
                    "use_in_validation_future": False,
                    "use_in_acceptance": False,
                    "manual_review_required": True,
                    "reason": item.reason,
                    "image_sha256": image_sha,
                    "label_sha256": label_sha,
                    "width": width,
                    "height": height,
                    "notes": item.notes,
                }
            )
            similarity_rows.append(
                {
                    "item_id": item_id,
                    "related_failure_case": item.related_failure_case,
                    "boundary_category": category,
                    "similarity_reason": item.reason,
                    "expected_help": item.expected_help,
                    "source_image_path": str(item.source_image_path),
                    "target_image_path": str(image_target),
                }
            )
            class_counter[item.class_name] += 1
            related_counter[item.related_failure_case] += 1
            item_index += 1

    return manifest_rows, similarity_rows, class_counter, related_counter


def build_no_leak_check(manifest_rows: list[dict[str, object]], exclusions: dict[str, Any]) -> dict[str, object]:
    acceptance_leak_count = 0
    acceptance_only_leak_count = 0
    test_leak_count = 0
    focus_case_leak_count = 0
    missing_image_count = 0
    missing_label_count = 0

    seen_hashes: Counter[str] = Counter()
    for row in manifest_rows:
        source_image_path = Path(str(row["source_image_path"]))
        target_image_path = Path(str(row["target_image_path"]))
        source_original = str(row.get("source_original_image", ""))
        image_hash = str(row["image_sha256"])

        if not target_image_path.exists():
            missing_image_count += 1
        if not Path(str(row["target_label_path"])).exists():
            missing_label_count += 1

        if (
            str(source_image_path.resolve()) in exclusions["acceptance_source_images"]
            or image_hash in exclusions["acceptance_hashes"]
        ):
            acceptance_leak_count += 1
        if str(source_image_path.resolve()) in exclusions["acceptance_only_paths"]:
            acceptance_only_leak_count += 1
        if (
            str(source_image_path.resolve()) in exclusions["test_source_images"]
            or image_hash in exclusions["test_hashes"]
            or source_original in exclusions["test_original_images"]
        ):
            test_leak_count += 1
        if (
            source_original in exclusions["focus_case_original_images"]
            or str(source_image_path.resolve()) in exclusions["focus_case_source_images"]
            or image_hash in exclusions["focus_case_hashes"]
        ):
            focus_case_leak_count += 1

        seen_hashes[image_hash] += 1

    duplicate_sha256_count = sum(count - 1 for count in seen_hashes.values() if count > 1)
    payload = {
        "acceptance_leak_count": acceptance_leak_count,
        "acceptance_only_leak_count": acceptance_only_leak_count,
        "test_leak_count": test_leak_count,
        "focus_case_leak_count": focus_case_leak_count,
        "duplicate_sha256_count": duplicate_sha256_count,
        "missing_image_count": missing_image_count,
        "missing_label_count": missing_label_count,
        "pass": all(
            [
                acceptance_leak_count == 0,
                acceptance_only_leak_count == 0,
                test_leak_count == 0,
                focus_case_leak_count == 0,
                duplicate_sha256_count == 0,
                missing_image_count == 0,
                missing_label_count == 0,
            ]
        ),
        "test_manifest_files_scanned": exclusions["test_manifest_files_scanned"],
        "acceptance_manifest_files_scanned": exclusions["acceptance_manifest_files_scanned"],
        "focus_case_original_images": sorted(exclusions["focus_case_original_images"]),
    }
    return payload


def build_review_queue(manifest_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    queue_rows: list[dict[str, object]] = []
    for row in manifest_rows:
        queue_rows.append(
            {
                "item_id": row["item_id"],
                "boundary_category": row["boundary_category"],
                "target_image_path": row["target_image_path"],
                "target_label_path": row["target_label_path"],
                "related_failure_case": row["related_failure_case"],
                "review_decision": "pending",
                "correct_class": "",
                "usable_for_training": "pending",
                "usable_for_validation": "pending",
                "reject_reason": "",
                "review_notes": "",
            }
        )
    return queue_rows


def build_category_distribution(manifest_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    counts: Counter[tuple[str, str]] = Counter()
    for row in manifest_rows:
        counts[(str(row["boundary_category"]), str(row["class_name"]))] += 1
    rows: list[dict[str, object]] = []
    for (category, class_name), count in sorted(counts.items()):
        rows.append({"boundary_category": category, "class_name": class_name, "count": count})
    return rows


def build_summary(
    manifest_rows: list[dict[str, object]],
    related_counter: Counter[str],
    no_leak_payload: dict[str, object],
) -> dict[str, object]:
    category_distribution = Counter(str(row["boundary_category"]) for row in manifest_rows)
    total_items = len(manifest_rows)
    known_gaps: list[str] = []
    for category in OUTPUT_CATEGORY_ORDER:
        if category_distribution[category] < TARGET_COUNTS[category]:
            known_gaps.append(f"{category} below target: {category_distribution[category]} < {TARGET_COUNTS[category]}")

    if not no_leak_payload["pass"]:
        stage_result = "FAIL"
    elif total_items >= 50 and len(known_gaps) == 0:
        stage_result = "PASS"
    else:
        stage_result = "PARTIAL"

    return {
        "dataset_name": "boundary_pair_repair_pack_20260705",
        "stage": "boundary_pair_repair_pack_build",
        "purpose": "repair_acc_000023_kneeling_shift_and_acc_000024_bending_shift_without_acceptance_leak",
        "total_items": total_items,
        "category_distribution": dict(category_distribution),
        "related_failure_case_distribution": dict(related_counter),
        "manual_review_required": True,
        "no_leak_pass": bool(no_leak_payload["pass"]),
        "known_gaps": known_gaps,
        "safety": {
            "trained_model": False,
            "replaced_weights": False,
            "modified_env": False,
            "modified_alert_chain": False,
        },
        "stage_result": stage_result,
    }


def build_readme(summary: dict[str, object]) -> str:
    return "\n".join(
        [
            "# boundary_pair_repair_pack_20260705",
            "",
            "这是一个围绕固定失败模式构建的小型边界修复样本包。",
            "",
            "## 这个数据包是什么",
            "",
            "- 它是为后续人工审核和 precision-safe boundary polish 准备的边界样本集合。",
            "- 样本重点围绕 kneeling 与 falling 的混淆、bending 与 fallen 的混淆、falling 到 fallen 的过渡，以及 fallen 低姿态边界。",
            "",
            "## 为什么围绕 acc_000023 和 acc_000024 构建",
            "",
            "- acc_000023 的真实问题是: 真跌倒边界样本容易被打成 kneeling。",
            "- acc_000024 的真实问题是: 真跌倒边界样本容易被偏到 bending。",
            "- 这包数据就是围绕这两类失败模式寻找相似但不泄漏的人工可审样本。",
            "",
            "## acc_000023 / acc_000024 本身没有进入数据包",
            "",
            "- 这两个 acceptance 样本自身没有被复制进来。",
            "- 与它们同源的 test/acceptance 样本也被排除。",
            "",
            "## 当前使用方式",
            "",
            "- 这包数据只用于后续人工审核和边界修复设计。",
            "- 它现在不能直接拿去训练。",
            "- 即使 no-leak 通过，也仍然需要人工审核 review_queue.csv。",
            "",
            "## 标签说明",
            "",
            "- 输出标签已经统一重映射到当前 v3 类别顺序:",
            "- 0 standing",
            "- 1 fallen",
            "- 2 sitting",
            "- 3 lying",
            "- 4 falling",
            "- 5 kneeling",
            "- 6 bending",
            "",
            "## 后续如何用于 precision-safe polish",
            "",
            "- 先逐项审核 review_queue.csv。",
            "- 只把审核通过、确认无泄漏、边界价值明确的样本并入后续 precision_safe_boundary_polish 数据集。",
            "- 并入时仍不能混入 acceptance/test 样本。",
            "",
            f"## 当前结果",
            "",
            f"- total_items: {summary['total_items']}",
            f"- no_leak_pass: {summary['no_leak_pass']}",
            f"- stage_result: {summary['stage_result']}",
        ]
    ) + "\n"


def build_log_text(
    summary: dict[str, object],
    no_leak_payload: dict[str, object],
    manifest_rows: list[dict[str, object]],
    related_counter: Counter[str],
    category_distribution_rows: list[dict[str, object]],
) -> str:
    return "\n".join(
        [
            "# Build Log",
            "",
            f"1. build_time: {datetime.now().isoformat(timespec='seconds')}",
            f"2. input_sources: {json.dumps([str(REVIEWED_FINAL_MANIFEST), str(REVIEWED_FINAL_TRANSITIONS), str(REVIEWED_ALL_MANIFEST)], ensure_ascii=False)}",
            f"3. excluded_sources: {json.dumps([str(ACCEPTANCE_MANIFEST), str(ACCEPTANCE_ONLY_CSV), str(CLEAN_REVIEWED_MANIFEST), str(V3_MANIFEST)], ensure_ascii=False)}",
            f"4. failure_reference_cases: {json.dumps(sorted(FOCUS_CASE_IDS), ensure_ascii=False)}",
            "5. selection_rules: reviewed_final first, reviewed_all supplement only when category target is not met, exclude focus/test/acceptance sources, keep one source image once",
            f"6. per_category_counts: {json.dumps(dict(Counter(str(row['boundary_category']) for row in manifest_rows)), ensure_ascii=False)}",
            f"7. related_failure_case_distribution: {json.dumps(dict(related_counter), ensure_ascii=False)}",
            f"8. no_leak_result: {json.dumps(no_leak_payload, ensure_ascii=False)}",
            "9. generated_review_queue: YES",
            "10. trained_model: NO",
            "11. replaced_weights: NO",
            "12. modified_env: NO",
            f"13. final_stage_result: {summary['stage_result']}",
            "",
            "14. category_distribution_rows:",
            *[f"   - {row['boundary_category']} / {row['class_name']}: {row['count']}" for row in category_distribution_rows],
        ]
    ) + "\n"


def main() -> int:
    exclusions = build_test_and_acceptance_exclusions()
    reviewed_final_buckets = build_reviewed_final_candidates(exclusions)
    reviewed_all_buckets = build_reviewed_all_candidates(exclusions)
    selected = choose_pack_items(reviewed_final_buckets, reviewed_all_buckets)
    manifest_rows, similarity_rows, _class_counter, related_counter = copy_pack_items(selected)

    no_leak_payload = build_no_leak_check(manifest_rows, exclusions)
    review_queue_rows = build_review_queue(manifest_rows)
    category_distribution_rows = build_category_distribution(manifest_rows)
    summary = build_summary(manifest_rows, related_counter, no_leak_payload)

    write_csv(OUTPUT_ROOT / "manifest.csv", manifest_rows)
    write_csv(OUTPUT_ROOT / "review_queue.csv", review_queue_rows)
    write_csv(OUTPUT_ROOT / "similarity_to_acceptance_focus.csv", similarity_rows)
    write_csv(OUTPUT_ROOT / "category_distribution.csv", category_distribution_rows)
    write_json(OUTPUT_ROOT / "no_leak_check.json", no_leak_payload)
    write_json(OUTPUT_ROOT / "summary.json", summary)
    write_text(OUTPUT_ROOT / "README.md", build_readme(summary))
    write_text(OUTPUT_ROOT / "build_log.md", build_log_text(summary, no_leak_payload, manifest_rows, related_counter, category_distribution_rows))

    return 0 if summary["stage_result"] in {"PASS", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
