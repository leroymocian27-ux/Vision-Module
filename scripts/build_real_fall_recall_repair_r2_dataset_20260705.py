from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "datasets" / "falling_transition_positive_batch_20260705_reviewed_final"
OUTPUT_ROOT = ROOT / "datasets" / "real_fall_recall_repair_r2_dataset_20260705"
V3_ROOT = ROOT / "datasets" / "fall_hint_v3_balanced_hardcase_202607"
V3_MANIFEST = V3_ROOT / "manifest.csv"
FIXED_ACCEPTANCE_MANIFEST = ROOT / "datasets" / "fall_hint_acceptance_fixed_202607_v1" / "manifest.csv"
ACCEPTANCE_ONLY_CSV = ROOT / "datasets" / "fall_false_positive_bank_202607" / "subsets" / "acceptance_only.csv"
CLEAN_REVIEWED_MANIFEST = ROOT / "datasets" / "fall_hint_v2_clean_reviewed_only_noaug_20260703" / "meta" / "manifest.csv"

TARGET_CLASS_NAMES = ["standing", "fallen", "sitting", "lying", "falling", "kneeling", "bending"]
OLD_ORDER_NAMES = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
OLD_TO_NEW = {0: 4, 1: 1, 2: 3, 3: 2, 4: 6, 5: 5, 6: 0}

REQUIRED_VAL_CLASSES = {"falling", "fallen", "sitting", "lying", "bending", "kneeling"}
REQUIRED_VAL_TRANSITIONS = {
    ("falling", "fallen"),
    ("sitting", "fallen"),
    ("lying", "fallen"),
    ("bending", "falling"),
}
REQUIRED_VAL_PATTERNS = {"boundary_shift_to_kneeling", "boundary_shift_to_bending"}


@dataclass
class Item:
    item_id: str
    category: str
    original_class: str
    reviewed_class: str
    source_dataset: str
    source_image_path: Path
    source_label_path: Path
    final_image_path: Path
    final_label_path: Path
    source_video_id: str
    frame_index: int
    near_miss_pattern: str
    is_positive_repair: bool
    is_adl_anchor: bool
    source_batch_id: str
    source_original_image: str
    source_video: str
    width: int
    height: int
    notes: str
    transition_key: tuple[str, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the real_fall_recall_repair_r2 training dataset from the reviewed falling-transition repair packet."
    )
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
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


def parse_notes(notes: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in notes.split(";"):
        token = part.strip()
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def remap_old_order_label_text(text: str) -> str:
    output_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            continue
        old_cls = int(parts[0])
        if old_cls not in OLD_TO_NEW:
            continue
        new_cls = OLD_TO_NEW[old_cls]
        output_lines.append(f"{new_cls} {' '.join(parts[1:])}")
    return ("\n".join(output_lines) + "\n") if output_lines else ""


def validate_yolo_label(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing_label"
    for line_index, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            return False, f"line_{line_index}_bad_column_count"
        try:
            cls = int(float(parts[0]))
            x_center, y_center, width, height = [float(value) for value in parts[1:]]
        except ValueError:
            return False, f"line_{line_index}_non_numeric"
        if cls < 0 or cls >= len(TARGET_CLASS_NAMES):
            return False, f"line_{line_index}_bad_class_{cls}"
        if not (0 <= x_center <= 1 and 0 <= y_center <= 1 and 0 < width <= 1 and 0 < height <= 1):
            return False, f"line_{line_index}_bad_bbox"
    return True, ""


def read_items(source_root: Path) -> list[Item]:
    manifest_path = source_root / "manifest.csv"
    rows = read_csv(manifest_path)
    items: list[Item] = []
    for row in rows:
        notes = parse_notes(row.get("notes", ""))
        items.append(
            Item(
                item_id=row["item_id"],
                category=row["category"],
                original_class=row["original_candidate_class"],
                reviewed_class=row["reviewed_class"],
                source_dataset=row["source_dataset"],
                source_image_path=Path(row["source_image_path"]),
                source_label_path=Path(row["source_label_path"]),
                final_image_path=Path(row["final_image_path"]),
                final_label_path=Path(row["final_label_path"]),
                source_video_id=row["source_video_id"],
                frame_index=int(row["frame_index"]) if str(row["frame_index"]).strip() else -1,
                near_miss_pattern=row["near_miss_pattern"],
                is_positive_repair=str(row["is_positive_repair"]).lower() == "true",
                is_adl_anchor=str(row.get("is_adl_anchor", "false")).lower() == "true",
                source_batch_id=row.get("source_batch_id", notes.get("batch_id", "")),
                source_original_image=row.get("source_original_image", notes.get("original_image", "")),
                source_video=row.get("source_video", notes.get("source_video", "")),
                width=int(float(row["width"])),
                height=int(float(row["height"])),
                notes=row.get("notes", ""),
                transition_key=(row["original_candidate_class"], row["reviewed_class"]),
            )
        )
    return items


def ensure_output_root(output_root: Path, overwrite: bool) -> None:
    if output_root.exists():
        if not overwrite:
            raise SystemExit(f"output exists, pass --overwrite to rebuild: {output_root}")
        resolved = output_root.resolve()
        workspace = ROOT.resolve()
        if workspace not in resolved.parents:
            raise RuntimeError(f"unsafe output path outside workspace: {resolved}")
        shutil.rmtree(resolved)
    for path in [
        output_root / "train" / "images",
        output_root / "train" / "labels",
        output_root / "val" / "images",
        output_root / "val" / "labels",
        output_root / "meta",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def group_items(items: list[Item]) -> dict[str, list[Item]]:
    grouped: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        grouped[item.source_video_id].append(item)
    for rows in grouped.values():
        rows.sort(key=lambda item: (item.frame_index if item.frame_index >= 0 else 999999, item.item_id))
    return grouped


def pick_best_group(
    candidate_groups: list[str],
    grouped: dict[str, list[Item]],
    selected_groups: set[str],
    val_class_counts: Counter[str],
    total_class_counts: Counter[str],
) -> str | None:
    viable: list[tuple[int, int, int, int, str]] = []
    for group_id in candidate_groups:
        if group_id in selected_groups:
            continue
        group_items = grouped[group_id]
        group_class_counts = Counter(item.reviewed_class for item in group_items)
        # Never move all samples of a class into val; keep at least one for train.
        if any(total_class_counts[class_name] - (val_class_counts[class_name] + count) <= 0 for class_name, count in group_class_counts.items()):
            continue
        changed_count = sum(1 for item in group_items if item.original_class != item.reviewed_class)
        rare_bonus = sum(1 for class_name in group_class_counts if total_class_counts[class_name] <= 4)
        uncovered_bonus = sum(1 for class_name in group_class_counts if class_name in REQUIRED_VAL_CLASSES and val_class_counts[class_name] == 0)
        viable.append((len(group_items), -uncovered_bonus, -rare_bonus, -changed_count, group_id))
    if not viable:
        return None
    viable.sort()
    return viable[0][4]


def build_val_groups(items: list[Item]) -> tuple[set[str], dict[str, object]]:
    grouped = group_items(items)
    total_items = len(items)
    target_val_items = max(1, round(total_items * 0.2))
    max_val_items = target_val_items + 2
    total_class_counts = Counter(item.reviewed_class for item in items)

    selected_groups: set[str] = set()
    selected_item_ids: set[str] = set()
    val_class_counts: Counter[str] = Counter()
    covered_transitions: set[tuple[str, str]] = set()
    covered_patterns: set[str] = set()

    def can_add_group(group_id: str) -> bool:
        group_rows = grouped[group_id]
        tentative_count = len(selected_item_ids) + len(group_rows)
        if tentative_count > max_val_items and len(selected_item_ids) >= int(target_val_items * 0.9):
            return False
        group_class_counts = Counter(item.reviewed_class for item in group_rows)
        return not any(total_class_counts[class_name] - (val_class_counts[class_name] + count) <= 0 for class_name, count in group_class_counts.items())

    def add_group(group_id: str) -> None:
        selected_groups.add(group_id)
        for item in grouped[group_id]:
            selected_item_ids.add(item.item_id)
            val_class_counts[item.reviewed_class] += 1
            covered_transitions.add(item.transition_key)
            if item.near_miss_pattern:
                covered_patterns.add(item.near_miss_pattern)

    # 1. Cover required transition corrections.
    for required_transition in sorted(REQUIRED_VAL_TRANSITIONS):
        candidate_groups = [
            group_id for group_id, group_rows in grouped.items() if any(item.transition_key == required_transition for item in group_rows)
        ]
        best = pick_best_group(candidate_groups, grouped, selected_groups, val_class_counts, total_class_counts)
        if best and can_add_group(best):
            add_group(best)

    # 2. Cover required boundary patterns.
    for required_pattern in sorted(REQUIRED_VAL_PATTERNS):
        if required_pattern in covered_patterns:
            continue
        candidate_groups = [
            group_id for group_id, group_rows in grouped.items() if any(item.near_miss_pattern == required_pattern for item in group_rows)
        ]
        best = pick_best_group(candidate_groups, grouped, selected_groups, val_class_counts, total_class_counts)
        if best and can_add_group(best):
            add_group(best)

    # 3. Ensure required reviewed classes exist in val.
    for required_class in sorted(REQUIRED_VAL_CLASSES):
        if val_class_counts[required_class] > 0:
            continue
        candidate_groups = [
            group_id for group_id, group_rows in grouped.items() if any(item.reviewed_class == required_class for item in group_rows)
        ]
        best = pick_best_group(candidate_groups, grouped, selected_groups, val_class_counts, total_class_counts)
        if best and can_add_group(best):
            add_group(best)

    # 4. Fill to about 20% with diverse, small groups.
    while len(selected_item_ids) < target_val_items:
        candidate_groups = [group_id for group_id in grouped if group_id not in selected_groups]
        best = pick_best_group(candidate_groups, grouped, selected_groups, val_class_counts, total_class_counts)
        if best is None or not can_add_group(best):
            break
        add_group(best)

    split_summary = {
        "target_val_items": target_val_items,
        "actual_val_items": len(selected_item_ids),
        "actual_train_items": total_items - len(selected_item_ids),
        "val_group_count": len(selected_groups),
        "required_val_classes": sorted(REQUIRED_VAL_CLASSES),
        "covered_val_classes": sorted(class_name for class_name, count in val_class_counts.items() if count > 0),
        "required_val_transitions": [f"{left}->{right}" for left, right in sorted(REQUIRED_VAL_TRANSITIONS)],
        "covered_val_transitions": [f"{left}->{right}" for left, right in sorted(covered_transitions)],
        "required_val_patterns": sorted(REQUIRED_VAL_PATTERNS),
        "covered_val_patterns": sorted(REQUIRED_VAL_PATTERNS.intersection(covered_patterns)),
    }
    return selected_item_ids, split_summary


def copy_item(
    item: Item,
    split: str,
    index: int,
    output_root: Path,
) -> dict[str, object]:
    out_stem = f"{split}_{index:04d}"
    image_dst = output_root / split / "images" / f"{out_stem}{item.final_image_path.suffix.lower()}"
    label_dst = output_root / split / "labels" / f"{out_stem}.txt"
    shutil.copy2(item.final_image_path, image_dst)
    remapped_text = remap_old_order_label_text(item.final_label_path.read_text(encoding="utf-8"))
    label_dst.write_text(remapped_text, encoding="utf-8")
    valid, reason = validate_yolo_label(label_dst)
    if not valid:
        raise RuntimeError(f"invalid remapped label for {item.item_id}: {reason}")
    image_sha = sha256_file(image_dst)
    label_sha = sha256_file(label_dst)
    return {
        "item_id": item.item_id,
        "split": split,
        "class_name": item.reviewed_class,
        "original_class": item.original_class,
        "reviewed_class": item.reviewed_class,
        "source_dataset": item.source_dataset,
        "source_image_path": str(item.source_image_path),
        "source_label_path": str(item.source_label_path),
        "target_image_path": str(image_dst),
        "target_label_path": str(label_dst),
        "repair_role": "positive_recall_repair",
        "near_miss_pattern": item.near_miss_pattern,
        "is_positive_repair": True,
        "is_adl_anchor": False,
        "use_in_training": split == "train",
        "use_in_validation": split == "val",
        "use_in_acceptance": False,
        "image_sha256": image_sha,
        "label_sha256": label_sha,
        "width": item.width,
        "height": item.height,
        "notes": item.notes,
        "source_batch_id": item.source_batch_id,
        "source_original_image": item.source_original_image,
        "source_video": item.source_video,
        "source_video_id": item.source_video_id,
        "frame_index": item.frame_index,
        "category": item.category,
        "transition_key": f"{item.original_class}->{item.reviewed_class}",
    }


def build_dataset(source_root: Path, output_root: Path) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    items = read_items(source_root)
    if not items:
        raise RuntimeError(f"no items found in source dataset: {source_root}")

    val_item_ids, split_summary = build_val_groups(items)
    manifest_rows: list[dict[str, object]] = []
    train_index = 0
    val_index = 0
    for item in sorted(items, key=lambda row: (row.source_video_id, row.frame_index if row.frame_index >= 0 else 999999, row.item_id)):
        split = "val" if item.item_id in val_item_ids else "train"
        if split == "train":
            train_index += 1
            manifest_rows.append(copy_item(item, split, train_index, output_root))
        else:
            val_index += 1
            manifest_rows.append(copy_item(item, split, val_index, output_root))

    category_distribution_rows: list[dict[str, object]] = []
    for split in ["train", "val"]:
        split_rows = [row for row in manifest_rows if row["split"] == split]
        class_counts = Counter(str(row["class_name"]) for row in split_rows)
        for class_name, count in sorted(class_counts.items()):
            category_distribution_rows.append({"split": split, "class_name": class_name, "count": count})
    total_class_counts = Counter(str(row["class_name"]) for row in manifest_rows)
    for class_name, count in sorted(total_class_counts.items()):
        category_distribution_rows.append({"split": "total", "class_name": class_name, "count": count})

    transition_rows: list[dict[str, object]] = []
    for split in ["train", "val"]:
        split_rows = [row for row in manifest_rows if row["split"] == split]
        transition_counts = Counter((str(row["original_class"]), str(row["reviewed_class"])) for row in split_rows)
        for (original_class, reviewed_class), count in sorted(transition_counts.items()):
            transition_rows.append(
                {
                    "split": split,
                    "original_class": original_class,
                    "reviewed_class": reviewed_class,
                    "count": count,
                }
            )
    overall_transition_counts = Counter((str(row["original_class"]), str(row["reviewed_class"])) for row in manifest_rows)
    for (original_class, reviewed_class), count in sorted(overall_transition_counts.items()):
        transition_rows.append(
            {
                "split": "total",
                "original_class": original_class,
                "reviewed_class": reviewed_class,
                "count": count,
            }
        )

    source_trace_rows = [
        {
            "item_id": row["item_id"],
            "split": row["split"],
            "source_batch_id": row["source_batch_id"],
            "source_original_image": row["source_original_image"],
            "source_video": row["source_video"],
            "source_video_id": row["source_video_id"],
            "source_dataset": row["source_dataset"],
            "category": row["category"],
            "original_class": row["original_class"],
            "reviewed_class": row["reviewed_class"],
            "near_miss_pattern": row["near_miss_pattern"],
            "frame_index": row["frame_index"],
        }
        for row in manifest_rows
    ]

    write_csv(output_root / "meta" / "manifest.csv", manifest_rows)
    write_csv(output_root / "meta" / "train_manifest.csv", [row for row in manifest_rows if row["split"] == "train"])
    write_csv(output_root / "meta" / "val_manifest.csv", [row for row in manifest_rows if row["split"] == "val"])
    write_csv(output_root / "meta" / "category_distribution.csv", category_distribution_rows)
    write_csv(output_root / "meta" / "class_transition_used.csv", transition_rows)
    write_csv(output_root / "meta" / "source_trace.csv", source_trace_rows)

    dataset_yaml = "\n".join(
        [
            f"path: {output_root.as_posix()}",
            "train: train/images",
            "val: val/images",
            "",
            "names:",
            *[f"  {index}: {name}" for index, name in enumerate(TARGET_CLASS_NAMES)],
            "",
        ]
    )
    write_text(output_root / "data.yaml", dataset_yaml)

    class_transition_used = {f"{left}->{right}": count for (left, right), count in sorted(overall_transition_counts.items())}
    build_summary = {
        "total_items": len(manifest_rows),
        "train_items": sum(1 for row in manifest_rows if row["split"] == "train"),
        "val_items": sum(1 for row in manifest_rows if row["split"] == "val"),
        "positive_repair_count": sum(1 for row in manifest_rows if row["is_positive_repair"]),
        "adl_anchor_count": sum(1 for row in manifest_rows if row["is_adl_anchor"]),
        "category_distribution": dict(sorted(total_class_counts.items())),
        "class_transition_used": class_transition_used,
    }
    return manifest_rows, category_distribution_rows, {**split_summary, **build_summary}


def run_no_leak_check(source_rows: list[dict[str, object]]) -> dict[str, object]:
    fixed_rows = read_csv(FIXED_ACCEPTANCE_MANIFEST)
    acceptance_only_rows = read_csv(ACCEPTANCE_ONLY_CSV)
    v3_rows = read_csv(V3_MANIFEST)
    clean_rows = read_csv(CLEAN_REVIEWED_MANIFEST)

    acceptance_hashes = {row["image_sha256"] for row in fixed_rows if row.get("image_sha256")}
    acceptance_only_hashes = {
        sha256_file(Path(row["bank_image_path"]))
        for row in acceptance_only_rows
        if row.get("bank_image_path") and Path(row["bank_image_path"]).exists()
    }
    test_hashes = {row["image_hash"] for row in v3_rows if row.get("split") == "test" and row.get("image_hash")}
    test_source_paths = {row["source_image_path"] for row in v3_rows if row.get("split") == "test" and row.get("source_image_path")}
    clean_test_pairs = {
        (row["source_video"], row["source_original_image"])
        for row in clean_rows
        if row.get("split") == "test"
    }

    acceptance_leak_count = 0
    acceptance_only_leak_count = 0
    test_leak_count = 0
    image_hashes: list[str] = []
    missing_image_count = 0
    missing_label_count = 0

    for row in source_rows:
        image_path = Path(str(row["target_image_path"]))
        label_path = Path(str(row["target_label_path"]))
        if not image_path.exists():
            missing_image_count += 1
        if not label_path.exists():
            missing_label_count += 1

        image_sha = str(row["image_sha256"])
        image_hashes.append(image_sha)
        if image_sha in acceptance_hashes:
            acceptance_leak_count += 1
        if image_sha in acceptance_only_hashes:
            acceptance_only_leak_count += 1
        if image_sha in test_hashes:
            test_leak_count += 1
        if str(row["source_image_path"]) in test_source_paths:
            test_leak_count += 1
        if (str(row["source_video"]), str(row["source_original_image"])) in clean_test_pairs:
            test_leak_count += 1

    duplicate_sha256_count = sum(count - 1 for count in Counter(image_hashes).values() if count > 1)
    payload = {
        "acceptance_leak_count": acceptance_leak_count,
        "acceptance_only_leak_count": acceptance_only_leak_count,
        "test_leak_count": test_leak_count,
        "duplicate_sha256_count": duplicate_sha256_count,
        "missing_image_count": missing_image_count,
        "missing_label_count": missing_label_count,
        "pass": all(
            [
                acceptance_leak_count == 0,
                acceptance_only_leak_count == 0,
                test_leak_count == 0,
                duplicate_sha256_count == 0,
                missing_image_count == 0,
                missing_label_count == 0,
            ]
        ),
    }
    return payload


def render_readme(summary: dict[str, object], split_summary: dict[str, object]) -> str:
    return "\n".join(
        [
            "# real_fall_recall_repair_r2_dataset_20260705",
            "",
            "这是一个为后续 `candidate_v3_c_real_fall_recall_repair_r2` 训练准备的正式数据集。",
            "",
            "## 这个数据集是什么",
            "",
            "- 它来自 `falling_transition_positive_batch_20260705_reviewed_final`。",
            "- 它只包含已经人工审核完成并通过格式校验的样本。",
            "- 本阶段只构建数据集，不训练模型。",
            "",
            "## 它为什么用于 real_fall_recall_repair_r2",
            "",
            "- 上一阶段已经确认，这批样本对修复 `real_fall_miss` 和姿态边界混淆有直接价值。",
            "- 特别是 `falling -> fallen`、`sitting -> fallen`、`lying -> fallen`、`bending -> falling` 这些修正过的边界样本，被优先纳入本轮 train/val。",
            "",
            "## 它来自哪个 reviewed_final 包",
            "",
            f"- 来源目录：`{SOURCE_ROOT}`",
            "",
            "## 它不包含 fixed acceptance / test 泄漏",
            "",
            "- 已对 `fixed acceptance manifest`、`acceptance_only.csv`、`所有 test split` 做 no-leak 检查。",
            f"- 当前 no_leak_pass: `{summary['no_leak_pass']}`",
            "",
            "## train / val 如何拆分",
            "",
            "- 拆分不是随机粗暴切分。",
            "- 优先按 `source_video_id` 做保守拆分，尽量减少近重复帧跨 split。",
            "- val 强制覆盖：`falling`、`fallen`、`sitting`、`lying`、`bending`、`kneeling`，并覆盖关键修正边界。",
            f"- 当前 train/val: `{summary['train_items']}` / `{summary['val_items']}`",
            "",
            "## 后续如何训练 candidate_v3_c_real_fall_recall_repair_r2",
            "",
            "- 直接使用本目录下的 `data.yaml` 作为 YOLO 数据集入口。",
            "- 保持当前 v3 类序：`standing, fallen, sitting, lying, falling, kneeling, bending`。",
            "- 训练阶段应继续保持 no-leak 原则，不得把 fixed acceptance 或 test 样本并入训练。",
            "",
            "## 当前风险和已知限制",
            "",
            "- 本轮数据集以正样本召回修复为主，没有额外大规模加入 ADL anchor 负样本。",
            "- 这有利于先修复 recall，但后续如果 precision 回退，仍可能需要单独的 precision polish 数据集。",
            f"- val 已覆盖关键边界，但样本总量仍只有 `{summary['total_items']}`，不代表最终泛化问题已被彻底解决。",
            "",
            "## val 覆盖摘要",
            "",
            f"- covered_val_classes: {', '.join(split_summary['covered_val_classes'])}",
            f"- covered_val_transitions: {', '.join(split_summary['covered_val_transitions'])}",
            f"- covered_val_patterns: {', '.join(split_summary['covered_val_patterns'])}",
            "",
        ]
    ) + "\n"


def render_build_log(
    *,
    start_ts: str,
    end_ts: str,
    source_root: Path,
    output_root: Path,
    split_summary: dict[str, object],
    category_distribution: dict[str, int],
    transition_counts: dict[str, int],
    no_leak: dict[str, object],
    ready_for_training: bool,
    stage_result: str,
) -> str:
    return "\n".join(
        [
            "# Build Log",
            "",
            f"1. 构建时间：{start_ts} -> {end_ts}",
            f"2. 输入来源：{source_root}",
            f"3. 输出目录：{output_root}",
            "4. 类序校正情况：输入标签为旧类序（falling, fallen, lying, sitting, bending, kneeling, standing），已统一重映射到当前 v3 类序（standing, fallen, sitting, lying, falling, kneeling, bending）。",
            "5. train / val 拆分规则：优先按 source_video_id 保守拆分；先满足关键 transition / class / near_miss 覆盖，再补足到约 20% val。",
            f"6. 每类数量：{json.dumps(category_distribution, ensure_ascii=False)}",
            f"7. class_transition 使用情况：{json.dumps(transition_counts, ensure_ascii=False)}",
            f"8. no-leak 检查结果：{json.dumps(no_leak, ensure_ascii=False)}",
            f"9. 是否 ready_for_training：{ready_for_training}",
            "10. 安全确认：trained_model=NO, replaced_weights=NO, modified_env=NO, modified_alert_chain=NO",
            f"11. 最终结果：{stage_result}",
        ]
    ) + "\n"


def main() -> int:
    args = parse_args()
    source_root = args.source.resolve()
    output_root = args.output.resolve()

    start_ts = datetime.now().isoformat(timespec="seconds")
    ensure_output_root(output_root, args.overwrite)
    manifest_rows, _distribution_rows, split_summary = build_dataset(source_root, output_root)
    no_leak = run_no_leak_check(manifest_rows)
    write_json(output_root / "meta" / "no_leak_check.json", no_leak)

    category_distribution = dict(sorted(Counter(str(row["class_name"]) for row in manifest_rows).items()))
    transition_counts = dict(
        sorted(Counter(f"{row['original_class']}->{row['reviewed_class']}" for row in manifest_rows).items())
    )

    ready_for_training = all(
        [
            no_leak["pass"],
            (output_root / "data.yaml").exists(),
            any((output_root / "train" / "images").iterdir()),
            any((output_root / "val" / "images").iterdir()),
            split_summary["actual_train_items"] > 0,
            split_summary["actual_val_items"] > 0,
        ]
    )
    stage_result = "PASS" if ready_for_training else "FAIL"

    summary = {
        "dataset_name": "real_fall_recall_repair_r2_dataset_20260705",
        "purpose": "real_fall_recall_repair_r2_training_dataset",
        "total_items": split_summary["total_items"],
        "train_items": split_summary["train_items"],
        "val_items": split_summary["val_items"],
        "positive_repair_count": split_summary["positive_repair_count"],
        "adl_anchor_count": split_summary["adl_anchor_count"],
        "category_distribution": category_distribution,
        "class_transition_used": transition_counts,
        "no_leak_pass": no_leak["pass"],
        "ready_for_training": ready_for_training,
        "safety": {
            "trained_model": False,
            "replaced_weights": False,
            "modified_env": False,
            "modified_alert_chain": False,
        },
        "stage_result": stage_result,
    }

    write_json(output_root / "meta" / "split_summary.json", split_summary)
    write_json(output_root / "summary.json", summary)
    write_text(output_root / "README.md", render_readme(summary, split_summary))
    write_text(
        output_root / "build_log.md",
        render_build_log(
            start_ts=start_ts,
            end_ts=datetime.now().isoformat(timespec="seconds"),
            source_root=source_root,
            output_root=output_root,
            split_summary=split_summary,
            category_distribution=category_distribution,
            transition_counts=transition_counts,
            no_leak=no_leak,
            ready_for_training=ready_for_training,
            stage_result=stage_result,
        ),
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if stage_result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
