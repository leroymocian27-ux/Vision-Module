from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets"
OUTPUT = DATASETS / "fall_hint_acceptance_fixed_202607_v1"
FALSE_POSITIVE_BANK = DATASETS / "fall_false_positive_bank_202607"
ACCEPTANCE_ONLY_CSV = FALSE_POSITIVE_BANK / "subsets" / "acceptance_only.csv"
FALSE_POSITIVE_MANIFEST = FALSE_POSITIVE_BANK / "manifest.csv"
CLEAN_REVIEWED = DATASETS / "fall_hint_v2_clean_reviewed_only_noaug_20260703"
CLEAN_MANIFEST = CLEAN_REVIEWED / "meta" / "manifest.csv"

CATEGORIES = [
    "empty_scene",
    "sitting_as_fall",
    "bending_as_fall",
    "kneeling_as_fall",
    "lying_adl_as_fall",
    "slow_fall_like",
    "low_posture",
    "real_fall",
    "normal_standing",
    "edge_cases",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build fixed Fall Hint acceptance dataset v1.")
    parser.add_argument("--output", type=Path, default=OUTPUT)
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


def ensure_output(output: Path, overwrite: bool) -> None:
    if output.exists():
        if not overwrite:
            raise SystemExit(f"output already exists, pass --overwrite to rebuild: {output}")
        shutil.rmtree(output)
    for category in CATEGORIES:
        (output / "images" / category).mkdir(parents=True, exist_ok=True)
        (output / "labels" / category).mkdir(parents=True, exist_ok=True)


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def copy_item(
    *,
    acceptance_id: str,
    category: str,
    source_dataset: str,
    source_image_path: Path,
    source_label_path: Path,
    output_root: Path,
    expected_behavior: str,
    should_trigger_fall_alarm: bool,
    is_hard_negative: bool,
    reason: str,
    notes: str,
) -> dict[str, Any]:
    image_ext = source_image_path.suffix.lower() or ".jpg"
    target_image = output_root / "images" / category / f"{acceptance_id}{image_ext}"
    target_label = output_root / "labels" / category / f"{acceptance_id}.txt"
    shutil.copy2(source_image_path, target_image)
    shutil.copy2(source_label_path, target_label)
    width, height = image_size(target_image)
    return {
        "acceptance_id": acceptance_id,
        "category": category,
        "source_dataset": source_dataset,
        "source_image_path": str(source_image_path),
        "source_label_path": str(source_label_path),
        "target_image_path": str(target_image),
        "target_label_path": str(target_label),
        "expected_behavior": expected_behavior,
        "should_trigger_fall_alarm": "true" if should_trigger_fall_alarm else "false",
        "use_in_training": "false",
        "use_in_validation": "false",
        "is_hard_negative": "true" if is_hard_negative else "false",
        "is_acceptance_only": "true",
        "reason": reason,
        "image_sha256": sha256_of_file(target_image),
        "label_sha256": sha256_of_file(target_label),
        "width": width,
        "height": height,
        "notes": notes,
    }


def build_from_acceptance_only(output_root: Path, manifest_rows: list[dict[str, Any]], selected_source_hashes: set[str]) -> tuple[int, int]:
    rows = read_csv(ACCEPTANCE_ONLY_CSV)
    imported = 0
    for index, row in enumerate(rows, start=1):
        source_image_path = Path(row["bank_image_path"])
        selected_source_hashes.add(sha256_of_file(source_image_path))
        acceptance_id = f"acc_{len(manifest_rows) + 1:06d}"
        category = row["category"]
        manifest_rows.append(
            copy_item(
                acceptance_id=acceptance_id,
                category=category,
                source_dataset="fall_false_positive_bank_202607.acceptance_only",
                source_image_path=source_image_path,
                source_label_path=Path(row["bank_label_path"]),
                output_root=output_root,
                expected_behavior="no_fall_alarm",
                should_trigger_fall_alarm=False,
                is_hard_negative=True,
                reason=row.get("reason", ""),
                notes=f"acceptance_only_source_index={index}; bank_id={row.get('bank_id', '')}",
            )
        )
        imported += 1
    return len(rows), imported


def stable_sort(rows: list[dict[str, str]], *keys: str) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: tuple(row.get(key, "") for key in keys))


def select_low_posture(output_root: Path, manifest_rows: list[dict[str, Any]], selected_source_hashes: set[str], limit: int = 3) -> int:
    rows = [row for row in read_csv(FALSE_POSITIVE_MANIFEST) if row.get("category") == "low_posture"]
    rows = stable_sort(rows, "bank_id", "bank_image_path")
    imported = 0
    for row in rows:
        if imported >= limit:
            break
        source_image_path = Path(row["bank_image_path"])
        source_hash = sha256_of_file(source_image_path)
        if source_hash in selected_source_hashes:
            continue
        selected_source_hashes.add(source_hash)
        acceptance_id = f"acc_{len(manifest_rows) + 1:06d}"
        manifest_rows.append(
            copy_item(
                acceptance_id=acceptance_id,
                category="low_posture",
                source_dataset="fall_false_positive_bank_202607.manifest",
                source_image_path=source_image_path,
                source_label_path=Path(row["bank_label_path"]),
                output_root=output_root,
                expected_behavior="no_fall_alarm",
                should_trigger_fall_alarm=False,
                is_hard_negative=True,
                reason=row.get("reason", ""),
                notes=f"bank_id={row.get('bank_id', '')}",
            )
        )
        imported += 1
    return imported


def select_clean_rows(class_name: str, split: str, limit: int) -> list[dict[str, str]]:
    rows = [
        row
        for row in read_csv(CLEAN_MANIFEST)
        if row.get("split") == split and row.get("class_names", "") == class_name
    ]
    return stable_sort(rows, "source_batch_id", "source_original_image", "image")[:limit]


def select_real_fall_rows(limit: int = 4) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    selected.extend(select_clean_rows("falling", "test", 2))
    remaining = max(0, limit - len(selected))
    selected.extend(select_clean_rows("fallen", "test", remaining))
    if len(selected) < limit:
        extra = [
            row
            for row in read_csv(CLEAN_MANIFEST)
            if row.get("split") == "val" and row.get("class_names", "") in {"falling", "fallen"}
        ]
        for row in stable_sort(extra, "source_batch_id", "source_original_image", "image"):
            if len(selected) >= limit:
                break
            if row not in selected:
                selected.append(row)
    return selected[:limit]


def import_clean_rows(
    *,
    rows: list[dict[str, str]],
    output_root: Path,
    manifest_rows: list[dict[str, Any]],
    category: str,
    expected_behavior: str,
    should_trigger_fall_alarm: bool,
    is_hard_negative: bool,
    reason_prefix: str,
    selected_source_hashes: set[str],
    limit: int | None = None,
) -> int:
    imported = 0
    for row in rows:
        if limit is not None and imported >= limit:
            break
        source_image = CLEAN_REVIEWED / row["image"]
        source_label = CLEAN_REVIEWED / row["label"]
        source_hash = sha256_of_file(source_image)
        if source_hash in selected_source_hashes:
            continue
        selected_source_hashes.add(source_hash)
        acceptance_id = f"acc_{len(manifest_rows) + 1:06d}"
        manifest_rows.append(
            copy_item(
                acceptance_id=acceptance_id,
                category=category,
                source_dataset="fall_hint_v2_clean_reviewed_only_noaug_20260703",
                source_image_path=source_image,
                source_label_path=source_label,
                output_root=output_root,
                expected_behavior=expected_behavior,
                should_trigger_fall_alarm=should_trigger_fall_alarm,
                is_hard_negative=is_hard_negative,
                reason=f"{reason_prefix}; class={row.get('class_names', '')}",
                notes=f"split={row.get('split', '')}; source_batch={row.get('source_batch_id', '')}; source_original_image={row.get('source_original_image', '')}",
            )
        )
        imported += 1
    return imported


def write_readme(output_root: Path, summary: dict[str, Any], known_gaps: list[str]) -> None:
    lines = [
        "# Fall Hint 固定验收集 v1",
        "",
        "## 1. 这是什么",
        "",
        "这是一个固定验收集，只用于比较不同 Fall Hint candidate 模型在典型误报场景和少量正样本场景中的表现。",
        "",
        "## 2. 为什么要建它",
        "",
        "因为普通训练指标不足以反映真实误报风险，尤其是 sitting / kneeling / lying ADL / empty scene 这类场景，需要固定样本做重复验收。",
        "",
        "## 3. 它不能用于训练",
        "",
        "- 不能用于训练",
        "- 不能用于微调",
        "- 不能用于增强",
        "- 不能用于采样调参",
        "- manifest 里所有样本都固定为 `use_in_training=false`、`use_in_validation=false`、`is_acceptance_only=true`",
        "",
        "## 4. 当前包含的类别",
        "",
        *[f"- {category}: {count}" for category, count in summary["category_distribution"].items()],
        "",
        "## 5. 如何读取 manifest.csv",
        "",
        "`manifest.csv` 记录了每个 acceptance 样本的来源、目标路径、预期行为、是否应该触发告警、图像与标签 hash。",
        "",
        "## 6. 后续如何用它评估 candidate 模型",
        "",
        "对每个 candidate 模型都在这套固定样本上跑一次离线推理，然后比较：",
        "",
        "- empty_scene 是否还误报",
        "- sitting / bending / kneeling / lying_adl 是否还被打成 fallen/falling",
        "- real_fall 是否允许触发 fall_alarm",
        "- normal_standing 是否不会触发告警",
        "",
        "## 7. 当前已知缺口",
        "",
        *[f"- {gap}" for gap in known_gaps],
        "",
        "## 8. 下一步建议",
        "",
        "- 用 `train_hard_negative.csv` 构建后续 v3 hard-negative 训练集",
        "- 用 `val_hard_negative.csv` 构建后续 v3 验证集",
        "- 保持 `acceptance_only.csv` 和本固定验收集不进入训练",
    ]
    (output_root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build() -> dict[str, Any]:
    args = parse_args()
    output_root = args.output.resolve()
    ensure_output(output_root, args.overwrite)

    manifest_rows: list[dict[str, Any]] = []
    selected_source_hashes: set[str] = set()
    acceptance_source_count, acceptance_imported_count = build_from_acceptance_only(output_root, manifest_rows, selected_source_hashes)
    low_posture_count = select_low_posture(output_root, manifest_rows, selected_source_hashes, limit=3)
    real_fall_count = import_clean_rows(
        rows=select_real_fall_rows(4),
        output_root=output_root,
        manifest_rows=manifest_rows,
        category="real_fall",
        expected_behavior="fall_alarm_allowed",
        should_trigger_fall_alarm=True,
        is_hard_negative=False,
        reason_prefix="reviewed real fall acceptance positive",
        selected_source_hashes=selected_source_hashes,
        limit=4,
    )
    normal_standing_count = import_clean_rows(
        rows=select_clean_rows("standing", "test", 12),
        output_root=output_root,
        manifest_rows=manifest_rows,
        category="normal_standing",
        expected_behavior="no_fall_alarm",
        should_trigger_fall_alarm=False,
        is_hard_negative=True,
        reason_prefix="reviewed normal standing acceptance negative",
        selected_source_hashes=selected_source_hashes,
        limit=4,
    )

    manifest_fields = [
        "acceptance_id",
        "category",
        "source_dataset",
        "source_image_path",
        "source_label_path",
        "target_image_path",
        "target_label_path",
        "expected_behavior",
        "should_trigger_fall_alarm",
        "use_in_training",
        "use_in_validation",
        "is_hard_negative",
        "is_acceptance_only",
        "reason",
        "image_sha256",
        "label_sha256",
        "width",
        "height",
        "notes",
    ]
    write_csv(output_root / "manifest.csv", manifest_rows, manifest_fields)

    category_distribution = Counter(str(row["category"]) for row in manifest_rows)
    category_csv_rows = [{"category": category, "count": category_distribution.get(category, 0)} for category in CATEGORIES]
    write_csv(output_root / "category_distribution.csv", category_csv_rows, ["category", "count"])

    known_gaps = []
    for gap_category in ["edge_cases"]:
        if category_distribution.get(gap_category, 0) == 0:
            known_gaps.append(f"{gap_category}: 当前 v1 中无样本")
    known_gaps.extend(
        [
            "occlusion / low_light / sit_to_floor 尚未单独纳入 v1 目录结构，后续可在 v2 扩充",
            "real_fall 当前只补入少量固定正样本，仍不足以覆盖全部跌倒变体",
        ]
    )

    duplicate_image_sha256_count = sum(count - 1 for count in Counter(row["image_sha256"] for row in manifest_rows).values() if count > 1)
    missing_image_count = sum(1 for row in manifest_rows if not Path(row["target_image_path"]).exists())
    missing_label_count = sum(1 for row in manifest_rows if not Path(row["target_label_path"]).exists())
    use_in_training_all_false = all(row["use_in_training"] == "false" for row in manifest_rows)
    use_in_validation_all_false = all(row["use_in_validation"] == "false" for row in manifest_rows)
    all_acceptance_only_true = all(row["is_acceptance_only"] == "true" for row in manifest_rows)
    pass_flag = all(
        [
            output_root.exists(),
            (output_root / "manifest.csv").exists(),
            acceptance_source_count == 19,
            acceptance_imported_count == 19,
            missing_image_count == 0,
            missing_label_count == 0,
            use_in_training_all_false,
            use_in_validation_all_false,
            all_acceptance_only_true,
            duplicate_image_sha256_count == 0,
        ]
    )

    should_trigger_counter = Counter(row["should_trigger_fall_alarm"] for row in manifest_rows)
    summary = {
        "dataset_name": "fall_hint_acceptance_fixed_202607_v1",
        "purpose": "fixed_acceptance_eval_only",
        "total_items": len(manifest_rows),
        "source_acceptance_only_count": acceptance_source_count,
        "imported_acceptance_only_count": acceptance_imported_count,
        "category_distribution": {category: category_distribution.get(category, 0) for category in CATEGORIES},
        "should_trigger_fall_alarm_distribution": dict(should_trigger_counter),
        "use_in_training": False,
        "use_in_validation": False,
        "known_gaps": known_gaps,
        "safety": {
            "trained_model": False,
            "replaced_weights": False,
            "modified_env": False,
            "modified_alert_chain": False,
        },
        "pass": pass_flag,
    }
    (output_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    build_log_lines = [
        "# Build Log",
        "",
        f"1. 构建时间: {datetime.now().isoformat(timespec='seconds')}",
        f"2. 输入来源: `{ACCEPTANCE_ONLY_CSV}`, `{FALSE_POSITIVE_MANIFEST}`, `{CLEAN_MANIFEST}`",
        f"3. 输出目录: `{output_root}`",
        "4. 纳入类别:",
        *[f"   - {category}: {category_distribution.get(category, 0)}" for category in CATEGORIES],
        f"5. 19 个 acceptance_only 是否全部导入: {'YES' if acceptance_imported_count == 19 else 'NO'}",
        f"6. 是否发现缺失文件: {'YES' if (missing_image_count or missing_label_count) else 'NO'}",
        f"7. 是否发现重复: {'YES' if duplicate_image_sha256_count else 'NO'}",
        "8. 已知缺口:",
        *[f"   - {gap}" for gap in known_gaps],
        "9. 安全确认:",
        "   - trained_model: false",
        "   - replaced_weights: false",
        "   - modified_env: false",
        "   - modified_alert_chain: false",
        f"10. 最终结论: {'PASS' if pass_flag else 'FAIL'}",
        "",
        "Supplement counts:",
        f"- low_posture_count: {low_posture_count}",
        f"- real_fall_count: {real_fall_count}",
        f"- normal_standing_count: {normal_standing_count}",
    ]
    (output_root / "build_log.md").write_text("\n".join(build_log_lines) + "\n", encoding="utf-8")

    write_readme(output_root, summary, known_gaps)

    self_check = {
        "target_dir_exists": output_root.exists(),
        "manifest_exists": (output_root / "manifest.csv").exists(),
        "summary_exists": (output_root / "summary.json").exists(),
        "readme_exists": (output_root / "README.md").exists(),
        "build_log_exists": (output_root / "build_log.md").exists(),
        "total_items": len(manifest_rows),
        "acceptance_only_source_count": acceptance_source_count,
        "acceptance_only_imported_count": acceptance_imported_count,
        "missing_acceptance_only_count": acceptance_source_count - acceptance_imported_count,
        "duplicate_image_sha256_count": duplicate_image_sha256_count,
        "missing_image_count": missing_image_count,
        "missing_label_count": missing_label_count,
        "use_in_training_all_false": use_in_training_all_false,
        "use_in_validation_all_false": use_in_validation_all_false,
        "all_acceptance_only_true": all_acceptance_only_true,
        "category_distribution": {category: category_distribution.get(category, 0) for category in CATEGORIES},
        "known_gaps": known_gaps,
        "pass": pass_flag,
    }
    (output_root / "self_check.json").write_text(json.dumps(self_check, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "summary": summary,
        "self_check": self_check,
    }


def main() -> int:
    result = build()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
