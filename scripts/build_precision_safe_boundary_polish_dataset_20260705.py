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
INPUT_BATCH = ROOT / "datasets" / "fall_hint_v2_raw" / "batch_035_boundary_pair_review_20260705"
INPUT_REVIEW_QUEUE = INPUT_BATCH / "meta" / "review_queue.csv"
INPUT_REVIEW_SUMMARY = INPUT_BATCH / "meta" / "review_summary.json"
INPUT_REVIEW_VALIDATION_SUMMARY = INPUT_BATCH / "meta" / "review_validation_summary.json"
INPUT_REVIEW_VALIDATED_ROWS = INPUT_BATCH / "meta" / "review_validation_reviewed_rows.csv"
BOUNDARY_MANIFEST = ROOT / "datasets" / "boundary_pair_repair_pack_20260705" / "manifest.csv"

DEFAULT_OUTPUT = ROOT / "datasets" / "precision_safe_boundary_polish_dataset_20260705"

ACCEPTANCE_MANIFEST = ROOT / "datasets" / "fall_hint_acceptance_fixed_202607_v1" / "manifest.csv"
ACCEPTANCE_ONLY_CSV = ROOT / "datasets" / "fall_false_positive_bank_202607" / "subsets" / "acceptance_only.csv"
FOCUS_CASE_IDS = {"acc_000023", "acc_000024"}

INPUT_CLASS_ORDER = ["standing", "fallen", "sitting", "lying", "falling", "kneeling", "bending"]
OUTPUT_CLASS_ORDER = ["standing", "sitting", "lying", "bending", "kneeling", "falling", "fallen"]
INPUT_ID_TO_OUTPUT_ID = {0: 0, 1: 6, 2: 1, 3: 2, 4: 5, 5: 4, 6: 3}
OUTPUT_NAME_TO_ID = {name: idx for idx, name in enumerate(OUTPUT_CLASS_ORDER)}

EXPECTED_TOTAL = 57
EXPECTED_TRAIN = 40
EXPECTED_VAL = 17
EXPECTED_BOUNDARY_COUNTS = {
    "kneeling_vs_falling_boundary": 15,
    "bending_vs_fallen_boundary": 18,
    "falling_to_fallen_transition": 12,
    "fallen_low_posture_boundary": 12,
}
EXPECTED_RELATED_CASE_COUNTS = {
    "acc_000023_like": 15,
    "acc_000024_like": 18,
    "both": 24,
}


@dataclass
class ReviewItem:
    item_id: str
    boundary_category: str
    related_failure_case: str
    target_image_path: Path
    target_label_path: Path
    current_class: str
    correct_class: str
    review_decision: str
    usable_for_training: bool
    usable_for_validation: bool
    reject_reason: str
    review_notes: str
    similarity_reason: str
    expected_help: str


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: Any) -> None:
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


def bool_from_text(value: str) -> bool:
    return str(value).strip().lower() == "true"


def ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def resolve_row_path(csv_path: Path, value: str) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate if candidate.exists() else None
    for attempt in [csv_path.parent.parent / value, csv_path.parent / value]:
        if attempt.exists():
            return attempt
    return None


def image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return image.size


def parse_and_remap_label(
    label_path: Path,
    semantic_class: str,
    item_id: str,
) -> tuple[str, list[str], Counter[str], bool]:
    if semantic_class not in OUTPUT_NAME_TO_ID:
        raise ValueError(f"{item_id}: unsupported semantic class {semantic_class}")

    output_lines: list[str] = []
    remap_notes: list[str] = []
    box_counter: Counter[str] = Counter()
    semantic_present = False

    raw_lines = label_path.read_text(encoding="utf-8").splitlines()
    for line_index, raw in enumerate(raw_lines, start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{item_id}: invalid YOLO row at line {line_index}: {raw!r}")
        try:
            input_id = int(parts[0])
        except ValueError as exc:
            raise ValueError(f"{item_id}: invalid class id at line {line_index}: {parts[0]!r}") from exc
        if input_id not in INPUT_ID_TO_OUTPUT_ID:
            raise ValueError(f"{item_id}: class id out of range at line {line_index}: {input_id}")
        output_id = INPUT_ID_TO_OUTPUT_ID[input_id]
        coords = [float(value) for value in parts[1:]]
        x_center, y_center, width, height = coords
        if not (0.0 <= x_center <= 1.0 and 0.0 <= y_center <= 1.0):
            raise ValueError(f"{item_id}: center out of range at line {line_index}")
        if not (0.0 < width <= 1.0 and 0.0 < height <= 1.0):
            raise ValueError(f"{item_id}: size out of range at line {line_index}")
        class_name = OUTPUT_CLASS_ORDER[output_id]
        box_counter[class_name] += 1
        if class_name == semantic_class:
            semantic_present = True
        remap_notes.append(f"line{line_index}:{input_id}->{output_id}")
        output_lines.append(
            f"{output_id} "
            f"{x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"
        )

    if not output_lines:
        raise ValueError(f"{item_id}: empty label after remap")

    return "\n".join(output_lines) + "\n", remap_notes, box_counter, semantic_present


def validate_output_label(label_path: Path) -> tuple[bool, str]:
    try:
        lines = label_path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"read_error:{exc}"
    if not lines:
        return False, "empty_label"
    for line_index, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            return False, f"line_{line_index}_column_count"
        try:
            class_id = int(parts[0])
            x_center, y_center, width, height = [float(value) for value in parts[1:]]
        except ValueError:
            return False, f"line_{line_index}_parse_error"
        if class_id < 0 or class_id >= len(OUTPUT_CLASS_ORDER):
            return False, f"line_{line_index}_class_range"
        if not (0.0 <= x_center <= 1.0 and 0.0 <= y_center <= 1.0):
            return False, f"line_{line_index}_center_range"
        if not (0.0 < width <= 1.0 and 0.0 < height <= 1.0):
            return False, f"line_{line_index}_size_range"
    return True, ""


def collect_no_leak_reference_sets() -> dict[str, Any]:
    acceptance_rows = read_csv(ACCEPTANCE_MANIFEST)

    acceptance_hashes: set[str] = set()
    acceptance_source_images: set[str] = set()
    focus_case_hashes: set[str] = set()
    focus_case_source_images: set[str] = set()
    focus_case_original_images: set[str] = set()

    for row in acceptance_rows:
        source_image_path = Path(row["source_image_path"])
        target_image_path = Path(row["target_image_path"])
        if source_image_path.exists():
            acceptance_source_images.add(str(source_image_path.resolve()))
            acceptance_hashes.add(sha256_file(source_image_path))
        if target_image_path.exists():
            acceptance_hashes.add(sha256_file(target_image_path))
        if row.get("acceptance_id", "") in FOCUS_CASE_IDS:
            if source_image_path.exists():
                focus_case_source_images.add(str(source_image_path.resolve()))
                focus_case_hashes.add(sha256_file(source_image_path))
            if row.get("image_sha256"):
                focus_case_hashes.add(row["image_sha256"])
            notes = row.get("notes", "")
            for token in notes.split(";"):
                token = token.strip()
                if token.startswith("source_original_image="):
                    focus_case_original_images.add(Path(token.split("=", 1)[1]).name)

    acceptance_only_hashes: set[str] = set()
    acceptance_only_paths: set[str] = set()
    for row in read_csv(ACCEPTANCE_ONLY_CSV):
        bank_image_path = Path(row["bank_image_path"])
        if bank_image_path.exists():
            acceptance_only_paths.add(str(bank_image_path.resolve()))
            acceptance_only_hashes.add(sha256_file(bank_image_path))

    test_hashes: set[str] = set()
    test_source_images: set[str] = set()
    test_original_images: set[str] = set()
    test_manifest_files_scanned: list[str] = []

    for base in [ROOT / "datasets", ROOT / "runs"]:
        if not base.exists():
            continue
        for csv_path in base.rglob("*.csv"):
            try:
                rows = read_csv(csv_path)
            except Exception:
                continue
            if not rows:
                continue
            fields = set(rows[0].keys())
            if "split" not in fields and "use_in_acceptance" not in fields and "is_acceptance" not in fields:
                continue

            file_used = False
            for row in rows:
                split = str(row.get("split", "")).strip().lower()
                use_in_acceptance = str(row.get("use_in_acceptance", "")).strip().lower() == "true"
                is_acceptance = str(row.get("is_acceptance", "")).strip().lower() == "true"
                if split != "test" and not use_in_acceptance and not is_acceptance:
                    continue

                file_used = True
                for key in ("source_original_image", "original_image"):
                    value = row.get(key, "")
                    if value:
                        test_original_images.add(Path(value).name)
                for key in (
                    "source_image_path",
                    "image",
                    "target_image_path",
                    "v3_image_path",
                    "source_archive_image",
                    "new_image",
                    "bank_image_path",
                ):
                    resolved = resolve_row_path(csv_path, row.get(key, ""))
                    if resolved and resolved.exists():
                        test_source_images.add(str(resolved.resolve()))
                        test_hashes.add(sha256_file(resolved))

            if file_used:
                test_manifest_files_scanned.append(str(csv_path))

    return {
        "acceptance_hashes": acceptance_hashes,
        "acceptance_source_images": acceptance_source_images,
        "acceptance_only_hashes": acceptance_only_hashes,
        "acceptance_only_paths": acceptance_only_paths,
        "focus_case_hashes": focus_case_hashes,
        "focus_case_source_images": focus_case_source_images,
        "focus_case_original_images": focus_case_original_images,
        "test_hashes": test_hashes,
        "test_source_images": test_source_images,
        "test_original_images": test_original_images,
        "test_manifest_files_scanned": test_manifest_files_scanned,
        "acceptance_manifest_files_scanned": [str(ACCEPTANCE_MANIFEST), str(ACCEPTANCE_ONLY_CSV)],
    }


def build_readme(summary: dict[str, Any], no_leak: dict[str, Any]) -> str:
    return f"""# precision_safe_boundary_polish_dataset_20260705

## 这是什么

这是基于 `batch_035_boundary_pair_review_20260705` 人工审核结果构建的训练就绪数据集，用于后续 `candidate_v3_c` 主线的小学习率 precision-safe boundary polish 训练。

## 数据来源

- 输入审核批次：`datasets/fall_hint_v2_raw/batch_035_boundary_pair_review_20260705`
- 输入状态：57 / 57 已审核完成
- 拆分结果：`train=40`，`val=17`

## 这个数据集解决什么问题

这批样本主要服务于两类误报边界修补：

1. `acc_000023` 对应的 `kneeling / falling` 边界混淆
2. `acc_000024` 对应的 `bending / fallen` 边界混淆

同时也补入了：

- `falling_to_fallen_transition`
- `fallen_low_posture_boundary`

## 重要安全说明

- `acc_000023` 与 `acc_000024` 本体没有进入训练集
- 本数据集未混入 fixed acceptance 样本
- 本数据集未混入 `acceptance_only.csv` 样本
- 本数据集未混入任何 test split 样本

## 类别顺序

当前 `data.yaml` 固定类序为：

0. standing
1. sitting
2. lying
3. bending
4. kneeling
5. falling
6. fallen

## train / val 如何拆分

- `pass_train` -> `train`
- `pass_val` -> `val`
- `reject / needs_fix / pending` 一律不纳入

## 后续如何用于训练

后续训练时直接使用本目录下的 `data.yaml`，只做 boundary polish 小步训练即可，不要把 acceptance/test 样本再混入训练过程。

## 当前风险与限制

- 该数据集规模较小，目的不是全面重训，而是精准修补边界误报
- 样本重点集中在边界混淆场景，对全量场景泛化能力提升有限
- 训练前仍应复核主模型主干精度，避免 polish 阶段把 recall 拉低

## 构建结果

- total_items: {summary["total_items"]}
- train_items: {summary["train_items"]}
- val_items: {summary["val_items"]}
- no_leak_pass: {str(no_leak["pass"]).lower()}
- ready_for_training: {str(summary["ready_for_training"]).lower()}
"""


def build_data_yaml(output_root: Path) -> str:
    names_block = "\n".join(f"  {idx}: {name}" for idx, name in enumerate(OUTPUT_CLASS_ORDER))
    return (
        f"path: {output_root.as_posix()}\n"
        "train: train/images\n"
        "val: val/images\n"
        f"nc: {len(OUTPUT_CLASS_ORDER)}\n"
        "names:\n"
        f"{names_block}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build precision_safe_boundary_polish_dataset_20260705")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    ensure_exists(INPUT_BATCH, "input batch")
    ensure_exists(INPUT_REVIEW_QUEUE, "review_queue.csv")
    ensure_exists(INPUT_REVIEW_SUMMARY, "review_summary.json")
    ensure_exists(INPUT_REVIEW_VALIDATION_SUMMARY, "review_validation_summary.json")
    ensure_exists(INPUT_REVIEW_VALIDATED_ROWS, "review_validation_reviewed_rows.csv")
    ensure_exists(BOUNDARY_MANIFEST, "boundary manifest")
    ensure_exists(ACCEPTANCE_MANIFEST, "acceptance manifest")
    ensure_exists(ACCEPTANCE_ONLY_CSV, "acceptance_only.csv")

    output_root = args.output.resolve()
    if output_root.exists():
        if not args.overwrite:
            raise SystemExit(f"Output already exists, use --overwrite to rebuild: {output_root}")
        shutil.rmtree(output_root)

    review_summary = json.loads(INPUT_REVIEW_SUMMARY.read_text(encoding="utf-8"))
    validation_summary = json.loads(INPUT_REVIEW_VALIDATION_SUMMARY.read_text(encoding="utf-8"))
    validated_rows = read_csv(INPUT_REVIEW_VALIDATED_ROWS)
    review_rows = read_csv(INPUT_REVIEW_QUEUE)
    boundary_rows = read_csv(BOUNDARY_MANIFEST)

    if not review_summary.get("ready_for_merge", False):
        raise SystemExit("FAIL: review_summary.ready_for_merge is false")
    if not validation_summary.get("ready_for_merge", False):
        raise SystemExit("FAIL: review_validation_summary.ready_for_merge is false")
    if validation_summary.get("reviewed_rows") != EXPECTED_TOTAL:
        raise SystemExit(f"FAIL: reviewed_rows != {EXPECTED_TOTAL}")
    if validation_summary.get("decision_counts", {}).get("pass_train") != EXPECTED_TRAIN:
        raise SystemExit(f"FAIL: pass_train != {EXPECTED_TRAIN}")
    if validation_summary.get("decision_counts", {}).get("pass_val") != EXPECTED_VAL:
        raise SystemExit(f"FAIL: pass_val != {EXPECTED_VAL}")
    if validation_summary.get("needs_fix_count") != 0:
        raise SystemExit("FAIL: needs_fix_count != 0")
    if validation_summary.get("invalid_decision_count") != 0:
        raise SystemExit("FAIL: invalid_decision_count != 0")
    if validation_summary.get("issue_count") != 0:
        raise SystemExit("FAIL: issue_count != 0")
    if len(validated_rows) != EXPECTED_TOTAL:
        raise SystemExit(f"FAIL: validated reviewed rows != {EXPECTED_TOTAL}")

    invalid_validated = [row for row in validated_rows if str(row.get("label_valid", "")).lower() != "true"]
    if invalid_validated:
        raise SystemExit(f"FAIL: found invalid reviewed labels: {len(invalid_validated)}")

    review_by_item: dict[str, ReviewItem] = {}
    for row in review_rows:
        item_id = row["item_id"]
        review_by_item[item_id] = ReviewItem(
            item_id=item_id,
            boundary_category=row["boundary_category"],
            related_failure_case=row["related_failure_case"],
            target_image_path=Path(row["target_image_path"]),
            target_label_path=Path(row["target_label_path"]),
            current_class=row["current_class"],
            correct_class=row["correct_class"] or row["current_class"],
            review_decision=row["review_decision"],
            usable_for_training=bool_from_text(row["usable_for_training"]),
            usable_for_validation=bool_from_text(row["usable_for_validation"]),
            reject_reason=row.get("reject_reason", ""),
            review_notes=row.get("review_notes", ""),
            similarity_reason=row.get("similarity_reason", ""),
            expected_help=row.get("expected_help", ""),
        )

    boundary_by_item = {row["item_id"]: row for row in boundary_rows}

    manifest_rows: list[dict[str, Any]] = []
    train_manifest_rows: list[dict[str, Any]] = []
    val_manifest_rows: list[dict[str, Any]] = []
    source_trace_rows: list[dict[str, Any]] = []

    split_item_counter: Counter[str] = Counter()
    box_distribution: Counter[str] = Counter()
    reviewed_class_distribution: Counter[str] = Counter()
    boundary_distribution: Counter[str] = Counter()
    related_distribution: Counter[str] = Counter()
    semantic_presence_failures: list[str] = []
    remap_log_rows: list[dict[str, str]] = []

    train_images = output_root / "train" / "images"
    train_labels = output_root / "train" / "labels"
    val_images = output_root / "val" / "images"
    val_labels = output_root / "val" / "labels"
    meta_dir = output_root / "meta"
    for path in [train_images, train_labels, val_images, val_labels, meta_dir]:
        path.mkdir(parents=True, exist_ok=True)

    for item_id in sorted(review_by_item):
        review = review_by_item[item_id]
        if review.review_decision not in {"pass_train", "pass_val"}:
            continue
        if item_id not in boundary_by_item:
            raise SystemExit(f"FAIL: missing boundary manifest row for {item_id}")

        boundary = boundary_by_item[item_id]
        split = "train" if review.review_decision == "pass_train" else "val"
        output_image = (train_images if split == "train" else val_images) / f"{item_id}.jpg"
        output_label = (train_labels if split == "train" else val_labels) / f"{item_id}.txt"

        ensure_exists(review.target_image_path, f"{item_id} reviewed image")
        ensure_exists(review.target_label_path, f"{item_id} reviewed label")

        shutil.copy2(review.target_image_path, output_image)
        remapped_text, remap_notes, per_file_box_counter, semantic_present = parse_and_remap_label(
            review.target_label_path,
            review.correct_class,
            item_id,
        )
        output_label.write_text(remapped_text, encoding="utf-8")

        image_sha = sha256_file(output_image)
        label_sha = sha256_file(output_label)
        width, height = image_size(output_image)
        if not semantic_present:
            semantic_presence_failures.append(item_id)

        split_item_counter[split] += 1
        reviewed_class_distribution[review.correct_class] += 1
        boundary_distribution[review.boundary_category] += 1
        related_distribution[review.related_failure_case] += 1
        box_distribution.update(per_file_box_counter)

        manifest_row = {
            "item_id": item_id,
            "split": split,
            "boundary_category": review.boundary_category,
            "related_failure_case": review.related_failure_case,
            "class_name": review.correct_class,
            "original_class": boundary.get("original_class", ""),
            "reviewed_class": boundary.get("reviewed_class", ""),
            "correct_class": review.correct_class,
            "source_dataset": boundary.get("source_dataset", ""),
            "source_image_path": boundary.get("source_image_path", ""),
            "source_label_path": boundary.get("source_label_path", ""),
            "source_original_image": boundary.get("source_original_image", ""),
            "source_video": boundary.get("source_video", ""),
            "target_image_path": str(output_image),
            "target_label_path": str(output_label),
            "review_decision": review.review_decision,
            "usable_for_training": str(review.usable_for_training).lower(),
            "usable_for_validation": str(review.usable_for_validation).lower(),
            "repair_role": boundary.get("reason", ""),
            "near_miss_pattern": boundary.get("near_miss_pattern", ""),
            "is_positive_repair": boundary.get("is_positive_repair", ""),
            "is_boundary_polish": "true",
            "use_in_training": str(split == "train").lower(),
            "use_in_validation": str(split == "val").lower(),
            "use_in_acceptance": "false",
            "image_sha256": image_sha,
            "label_sha256": label_sha,
            "width": width,
            "height": height,
            "notes": "; ".join(
                filter(
                    None,
                    [
                        f"source_batch=batch_035_boundary_pair_review_20260705",
                        f"reviewed_input_image={review.target_image_path}",
                        f"reviewed_input_label={review.target_label_path}",
                        f"similarity_reason={review.similarity_reason}",
                        f"expected_help={review.expected_help}",
                        f"review_notes={review.review_notes}",
                        f"boundary_manifest_notes={boundary.get('notes', '')}",
                    ],
                )
            ),
        }
        manifest_rows.append(manifest_row)
        source_trace_rows.append(
            {
                "item_id": item_id,
                "split": split,
                "source_batch": "batch_035_boundary_pair_review_20260705",
                "reviewed_image_path": str(review.target_image_path),
                "reviewed_label_path": str(review.target_label_path),
                "original_source_dataset": boundary.get("source_dataset", ""),
                "original_source_image_path": boundary.get("source_image_path", ""),
                "original_source_label_path": boundary.get("source_label_path", ""),
                "source_original_image": boundary.get("source_original_image", ""),
                "source_video": boundary.get("source_video", ""),
                "boundary_category": review.boundary_category,
                "related_failure_case": review.related_failure_case,
                "reviewed_class": review.correct_class,
            }
        )
        remap_log_rows.append(
            {
                "item_id": item_id,
                "correct_class": review.correct_class,
                "remap_notes": "|".join(remap_notes),
            }
        )

    manifest_rows.sort(key=lambda row: row["item_id"])
    train_manifest_rows = [row for row in manifest_rows if row["split"] == "train"]
    val_manifest_rows = [row for row in manifest_rows if row["split"] == "val"]

    category_distribution_rows = [
        {"class_name": class_name, "box_count": box_distribution.get(class_name, 0), "reviewed_item_count": reviewed_class_distribution.get(class_name, 0)}
        for class_name in OUTPUT_CLASS_ORDER
    ]
    boundary_distribution_rows = [
        {"boundary_category": key, "item_count": boundary_distribution.get(key, 0)}
        for key in EXPECTED_BOUNDARY_COUNTS
    ]
    related_distribution_rows = [
        {"related_failure_case": key, "item_count": related_distribution.get(key, 0)}
        for key in EXPECTED_RELATED_CASE_COUNTS
    ]

    write_csv(meta_dir / "manifest.csv", manifest_rows)
    write_csv(meta_dir / "train_manifest.csv", train_manifest_rows)
    write_csv(meta_dir / "val_manifest.csv", val_manifest_rows)
    write_csv(meta_dir / "category_distribution.csv", category_distribution_rows)
    write_csv(meta_dir / "boundary_category_distribution.csv", boundary_distribution_rows)
    write_csv(meta_dir / "related_failure_case_distribution.csv", related_distribution_rows)
    write_csv(meta_dir / "source_trace.csv", source_trace_rows)

    review_import_summary = {
        "source_batch": "batch_035_boundary_pair_review_20260705",
        "total_reviewed_rows": len(validated_rows),
        "imported_rows": len(manifest_rows),
        "train_rows": len(train_manifest_rows),
        "val_rows": len(val_manifest_rows),
        "decision_counts": dict(Counter(row["review_decision"] for row in review_rows)),
        "reviewed_class_distribution": {name: reviewed_class_distribution.get(name, 0) for name in OUTPUT_CLASS_ORDER},
        "semantic_presence_failure_count": len(semantic_presence_failures),
        "semantic_presence_failures": semantic_presence_failures,
    }
    write_json(meta_dir / "review_import_summary.json", review_import_summary)

    split_summary = {
        "dataset_name": "precision_safe_boundary_polish_dataset_20260705",
        "total_items": len(manifest_rows),
        "train_items": len(train_manifest_rows),
        "val_items": len(val_manifest_rows),
        "expected_total_items": EXPECTED_TOTAL,
        "expected_train_items": EXPECTED_TRAIN,
        "expected_val_items": EXPECTED_VAL,
    }
    write_json(meta_dir / "split_summary.json", split_summary)

    data_yaml_path = output_root / "data.yaml"
    write_text(data_yaml_path, build_data_yaml(output_root))

    reference_sets = collect_no_leak_reference_sets()

    acceptance_leaks: list[str] = []
    acceptance_only_leaks: list[str] = []
    test_leaks: list[str] = []
    focus_case_leaks: list[str] = []
    duplicate_image_items: list[str] = []
    missing_images: list[str] = []
    missing_labels: list[str] = []
    invalid_labels: list[dict[str, str]] = []

    image_hash_to_item: dict[str, str] = {}
    for row in manifest_rows:
        image_path = Path(row["target_image_path"])
        label_path = Path(row["target_label_path"])
        source_image_path = Path(row["source_image_path"]) if row["source_image_path"] else None
        source_original_image = row.get("source_original_image", "")

        if not image_path.exists():
            missing_images.append(row["item_id"])
        if not label_path.exists():
            missing_labels.append(row["item_id"])

        valid, issue = validate_output_label(label_path)
        if not valid:
            invalid_labels.append({"item_id": row["item_id"], "issue": issue})

        image_sha = row["image_sha256"]
        if image_sha in image_hash_to_item:
            duplicate_image_items.append(f"{image_hash_to_item[image_sha]}->{row['item_id']}")
        else:
            image_hash_to_item[image_sha] = row["item_id"]

        if image_sha in reference_sets["acceptance_hashes"]:
            acceptance_leaks.append(row["item_id"])
        if image_sha in reference_sets["acceptance_only_hashes"]:
            acceptance_only_leaks.append(row["item_id"])
        if image_sha in reference_sets["test_hashes"]:
            test_leaks.append(row["item_id"])
        if image_sha in reference_sets["focus_case_hashes"]:
            focus_case_leaks.append(row["item_id"])

        if source_image_path and source_image_path.exists():
            source_resolved = str(source_image_path.resolve())
            if source_resolved in reference_sets["acceptance_source_images"]:
                acceptance_leaks.append(f"{row['item_id']}:source_path")
            if source_resolved in reference_sets["acceptance_only_paths"]:
                acceptance_only_leaks.append(f"{row['item_id']}:source_path")
            if source_resolved in reference_sets["test_source_images"]:
                test_leaks.append(f"{row['item_id']}:source_path")
            if source_resolved in reference_sets["focus_case_source_images"]:
                focus_case_leaks.append(f"{row['item_id']}:source_path")
        if source_original_image and source_original_image in reference_sets["test_original_images"]:
            test_leaks.append(f"{row['item_id']}:source_original_image")
        if source_original_image and source_original_image in reference_sets["focus_case_original_images"]:
            focus_case_leaks.append(f"{row['item_id']}:focus_original_image")

    no_leak = {
        "acceptance_leak_count": len(acceptance_leaks),
        "acceptance_only_leak_count": len(acceptance_only_leaks),
        "test_leak_count": len(test_leaks),
        "focus_case_leak_count": len(focus_case_leaks),
        "duplicate_sha256_count": len(duplicate_image_items),
        "missing_image_count": len(missing_images),
        "missing_label_count": len(missing_labels),
        "invalid_label_count": len(invalid_labels),
        "pass": False,
        "acceptance_leaks": acceptance_leaks,
        "acceptance_only_leaks": acceptance_only_leaks,
        "test_leaks": test_leaks,
        "focus_case_leaks": focus_case_leaks,
        "duplicate_image_items": duplicate_image_items,
        "missing_images": missing_images,
        "missing_labels": missing_labels,
        "invalid_labels": invalid_labels,
        "acceptance_manifest_files_scanned": reference_sets["acceptance_manifest_files_scanned"],
        "test_manifest_files_scanned": reference_sets["test_manifest_files_scanned"],
    }
    no_leak["pass"] = (
        no_leak["acceptance_leak_count"] == 0
        and no_leak["acceptance_only_leak_count"] == 0
        and no_leak["test_leak_count"] == 0
        and no_leak["focus_case_leak_count"] == 0
        and no_leak["duplicate_sha256_count"] == 0
        and no_leak["missing_image_count"] == 0
        and no_leak["missing_label_count"] == 0
        and no_leak["invalid_label_count"] == 0
    )
    write_json(meta_dir / "no_leak_check.json", no_leak)

    counts_ok = (
        len(manifest_rows) == EXPECTED_TOTAL
        and len(train_manifest_rows) == EXPECTED_TRAIN
        and len(val_manifest_rows) == EXPECTED_VAL
    )
    boundary_counts_ok = all(boundary_distribution.get(key, 0) == value for key, value in EXPECTED_BOUNDARY_COUNTS.items())
    related_counts_ok = all(related_distribution.get(key, 0) == value for key, value in EXPECTED_RELATED_CASE_COUNTS.items())
    data_yaml_valid = data_yaml_path.exists() and "0: standing" in data_yaml_path.read_text(encoding="utf-8")
    ready_for_training = (
        counts_ok
        and boundary_counts_ok
        and related_counts_ok
        and no_leak["pass"]
        and data_yaml_valid
        and len(semantic_presence_failures) == 0
    )

    summary = {
        "dataset_name": "precision_safe_boundary_polish_dataset_20260705",
        "purpose": "precision_safe_boundary_polish_training_dataset",
        "source_batch": "batch_035_boundary_pair_review_20260705",
        "total_items": len(manifest_rows),
        "train_items": len(train_manifest_rows),
        "val_items": len(val_manifest_rows),
        "category_distribution": {name: box_distribution.get(name, 0) for name in OUTPUT_CLASS_ORDER},
        "boundary_category_distribution": {key: boundary_distribution.get(key, 0) for key in EXPECTED_BOUNDARY_COUNTS},
        "related_failure_case_distribution": {key: related_distribution.get(key, 0) for key in EXPECTED_RELATED_CASE_COUNTS},
        "no_leak_pass": no_leak["pass"],
        "ready_for_training": ready_for_training,
        "safety": {
            "trained_model": False,
            "replaced_weights": False,
            "modified_env": False,
            "modified_alert_chain": False,
            "used_acceptance_for_training": False,
            "used_test_for_training": False,
        },
        "semantic_presence_failure_count": len(semantic_presence_failures),
        "stage_result": "PASS" if ready_for_training else "FAIL",
    }
    write_json(output_root / "summary.json", summary)
    write_text(output_root / "README.md", build_readme(summary, no_leak))

    build_log_lines = [
        "# build_log",
        "",
        f"- 构建时间: {datetime.now().isoformat(timespec='seconds')}",
        f"- 输入来源: {INPUT_BATCH}",
        f"- 输入 review_summary: ready_for_merge={review_summary.get('ready_for_merge')}, total_items={review_summary.get('total_items')}, reviewed_items={review_summary.get('reviewed_items')}",
        f"- 输入 review_validation_summary: reviewed_rows={validation_summary.get('reviewed_rows')}, pass_train={validation_summary.get('decision_counts', {}).get('pass_train')}, pass_val={validation_summary.get('decision_counts', {}).get('pass_val')}, needs_fix={validation_summary.get('needs_fix_count')}, invalid_decision_count={validation_summary.get('invalid_decision_count')}, issue_count={validation_summary.get('issue_count')}",
        f"- 输出目录: {output_root}",
        "- 类序检查/重映射: batch_035 输入标签按 boundary-pack 类序逐框 remap 到当前 v3 类序。",
        f"  - 输入类序: {INPUT_CLASS_ORDER}",
        f"  - 输出类序: {OUTPUT_CLASS_ORDER}",
        f"  - 映射: {INPUT_ID_TO_OUTPUT_ID}",
        f"- train / val 数量: train={len(train_manifest_rows)}, val={len(val_manifest_rows)}, total={len(manifest_rows)}",
        "- 每类框数量:",
    ]
    for class_name in OUTPUT_CLASS_ORDER:
        build_log_lines.append(f"  - {class_name}: {box_distribution.get(class_name, 0)}")
    build_log_lines.append("- boundary_category 分布:")
    for key in EXPECTED_BOUNDARY_COUNTS:
        build_log_lines.append(f"  - {key}: {boundary_distribution.get(key, 0)}")
    build_log_lines.append("- related_failure_case 分布:")
    for key in EXPECTED_RELATED_CASE_COUNTS:
        build_log_lines.append(f"  - {key}: {related_distribution.get(key, 0)}")
    build_log_lines.extend(
        [
            "- no-leak 检查结果:",
            f"  - acceptance_leak_count: {no_leak['acceptance_leak_count']}",
            f"  - acceptance_only_leak_count: {no_leak['acceptance_only_leak_count']}",
            f"  - test_leak_count: {no_leak['test_leak_count']}",
            f"  - focus_case_leak_count: {no_leak['focus_case_leak_count']}",
            f"  - duplicate_sha256_count: {no_leak['duplicate_sha256_count']}",
            f"  - missing_image_count: {no_leak['missing_image_count']}",
            f"  - missing_label_count: {no_leak['missing_label_count']}",
            f"  - invalid_label_count: {no_leak['invalid_label_count']}",
            f"  - pass: {str(no_leak['pass']).lower()}",
            f"- semantic presence failure count: {len(semantic_presence_failures)}",
            f"- 是否 ready_for_training: {str(ready_for_training).lower()}",
            "- 是否训练模型: NO",
            "- 是否替换权重: NO",
            "- 是否修改 .env: NO",
            "- 是否修改正式告警链路: NO",
            f"- 最终结果: {summary['stage_result']}",
            "",
            "## 逐文件 remap 摘要",
        ]
    )
    for row in remap_log_rows:
        build_log_lines.append(f"- {row['item_id']} ({row['correct_class']}): {row['remap_notes']}")
    write_text(output_root / "build_log.md", "\n".join(build_log_lines) + "\n")


if __name__ == "__main__":
    main()
