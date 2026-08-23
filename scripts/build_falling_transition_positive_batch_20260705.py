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
OUTPUT_ROOT = ROOT / "datasets" / "falling_transition_positive_batch_20260705"

REVIEWED_ALL_ROOT = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"
REVIEWED_ALL_MANIFEST = REVIEWED_ALL_ROOT / "meta" / "manifest.csv"
REVIEWED_ALL_INVALID_LABELS = REVIEWED_ALL_ROOT / "meta" / "relabel_invalid_labels.csv"
REVIEWED_ALL_UNTRUSTED = REVIEWED_ALL_ROOT / "meta" / "relabel_untrusted_frames.csv"
REVIEWED_ALL_CLASS_CONFLICTS = REVIEWED_ALL_ROOT / "meta" / "relabel_duplicate_class_conflicts.csv"

CLEAN_REVIEWED_MANIFEST = ROOT / "datasets" / "fall_hint_v2_clean_reviewed_only_noaug_20260703" / "meta" / "manifest.csv"
V3_MANIFEST = ROOT / "datasets" / "fall_hint_v3_balanced_hardcase_202607" / "manifest.csv"
FIXED_ACCEPTANCE_MANIFEST = ROOT / "datasets" / "fall_hint_acceptance_fixed_202607_v1" / "manifest.csv"
ACCEPTANCE_ONLY_CSV = ROOT / "datasets" / "fall_false_positive_bank_202607" / "subsets" / "acceptance_only.csv"

CATEGORY_ORDER = [
    "falling_transition_positive",
    "fallen_boundary_positive",
    "slow_fall_positive",
    "real_fall_low_posture_hold",
]

ITEM_PREFIX = {
    "falling_transition_positive": "ftp",
    "fallen_boundary_positive": "fbp",
    "slow_fall_positive": "sfp",
    "real_fall_low_posture_hold": "rlh",
}

MIN_TARGETS = {
    "falling_transition_positive": 40,
    "fallen_boundary_positive": 30,
    "slow_fall_positive": 10,
    "real_fall_low_posture_hold": 20,
}

DESIRED_COUNTS = {
    "falling_transition_positive": 50,
    "fallen_boundary_positive": 40,
    "slow_fall_positive": 10,
    "real_fall_low_posture_hold": 20,
}


@dataclass
class SourceCandidate:
    batch_id: str
    class_name: str
    source_video: str
    source_video_id: str
    scene: str
    group: str
    original_image: str
    original_image_path: Path
    original_label_path: Path
    original_meta_path: Path
    archive_image_path: Path
    archive_label_path: Path
    frame_index: int
    image_sha256: str
    width: int
    height: int


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


def read_image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return image.size


def frame_index_from_name(filename: str) -> int:
    match = re.search(r"_(\d{6})(?=\.[^.]+$)", filename)
    return int(match.group(1)) if match else -1


def is_adl_video(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    basename = Path(path).name.lower()
    return "/adl/" in lowered or "adl-" in basename or re.search(r"actor_\d+_adl_", basename) is not None


def is_fallish_video(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    basename = Path(path).name.lower()
    return any(token in lowered for token in ["fall", "fallen_hold", "fall_candidate", "simulated"]) or re.search(
        r"actor_\d+_fall_", basename
    ) is not None


def is_slow_fall_family(path: str, video_id: str) -> bool:
    lowered = path.lower()
    video_lowered = video_id.lower()
    tokens = [
        "manual_fall_20260625",
        "fall_candidate",
        "simulated_side",
        "desktop_fall",
        "574c42749fa162a487f7e3d3e84bb181_raw",
    ]
    return any(token in lowered or token in video_lowered for token in tokens)


def is_hold_family(path: str, video_id: str, scene: str) -> bool:
    lowered = path.lower()
    return "fallen_hold" in lowered or "fallen_hold" in video_id.lower() or "fallen_hold" in scene.lower()


def near_miss_pattern(category: str, class_name: str, source_video: str, video_id: str) -> str:
    if category == "falling_transition_positive":
        if "actor_3_fall_11" in video_id.lower() or "11_320dd3e8d3" in video_id.lower():
            return "boundary_shift_to_bending"
        if "desktop_fall_20ea" in video_id.lower():
            return "boundary_shift_to_kneeling"
        return "falling_transition_recall_support"
    if category == "fallen_boundary_positive":
        if class_name == "kneeling":
            return "boundary_shift_to_kneeling"
        if class_name == "bending":
            return "boundary_shift_to_bending"
        if class_name == "sitting":
            return "boundary_shift_to_sitting"
        if class_name == "lying":
            return "low_posture_boundary"
        return "fallen_boundary_reference"
    if category == "slow_fall_positive":
        if class_name == "kneeling":
            return "slow_fall_boundary_to_kneeling"
        if class_name == "bending":
            return "slow_fall_boundary_to_bending"
        return "slow_fall_like_recall_support"
    if category == "real_fall_low_posture_hold":
        if class_name == "bending":
            return "real_fall_hold_boundary_to_bending"
        if class_name == "lying":
            return "real_fall_hold_low_posture"
        return "real_fall_low_posture_hold"
    return ""


def priority_score(category: str, item: SourceCandidate) -> tuple[int, int, int, str, int]:
    class_bias = {
        "falling_transition_positive": {"falling": 0},
        "fallen_boundary_positive": {"kneeling": 0, "bending": 1, "sitting": 2, "lying": 3, "fallen": 4},
        "slow_fall_positive": {"falling": 0, "fallen": 1, "kneeling": 2, "bending": 3, "lying": 4, "sitting": 5},
        "real_fall_low_posture_hold": {"fallen": 0, "lying": 1, "falling": 2, "bending": 3},
    }
    family_bias = 5
    lowered = item.source_video.lower()
    if "actor_3_fall_11" in item.source_video_id.lower() or "11_320dd3e8d3" in item.source_video_id.lower():
        family_bias = 0
    elif "desktop_fall" in item.source_video_id.lower() or "574c42749fa162a487f7e3d3e84bb181_raw" in lowered:
        family_bias = 1
    elif "fallen_hold" in lowered:
        family_bias = 2
    elif "manual_fall_20260625" in lowered or "fall_candidate" in lowered:
        family_bias = 3
    return (
        family_bias,
        class_bias.get(category, {}).get(item.class_name, 9),
        0 if item.group == "fall" else 1,
        item.source_video_id,
        item.frame_index if item.frame_index >= 0 else 999999,
    )


def round_robin_select(
    candidates: list[SourceCandidate],
    *,
    category: str,
    desired_count: int,
    per_video_cap: int,
    global_used: set[str],
) -> list[SourceCandidate]:
    grouped: dict[str, list[SourceCandidate]] = defaultdict(list)
    for item in candidates:
        key = str(item.original_image_path.resolve())
        if key in global_used:
            continue
        grouped[item.source_video_id].append(item)

    for items in grouped.values():
        items.sort(key=lambda item: priority_score(category, item))

    selected: list[SourceCandidate] = []
    used_per_video: Counter[str] = Counter()
    while len(selected) < desired_count:
        progressed = False
        for video_id in sorted(grouped.keys()):
            if used_per_video[video_id] >= per_video_cap:
                continue
            items = grouped[video_id]
            while items:
                candidate = items.pop(0)
                key = str(candidate.original_image_path.resolve())
                if key in global_used:
                    continue
                global_used.add(key)
                used_per_video[video_id] += 1
                selected.append(candidate)
                progressed = True
                break
            if len(selected) >= desired_count:
                break
        if not progressed:
            break
    return selected


def select_hold_samples(
    candidates: list[SourceCandidate],
    *,
    desired_count: int,
    global_used: set[str],
) -> list[SourceCandidate]:
    grouped: dict[str, list[SourceCandidate]] = defaultdict(list)
    for item in candidates:
        key = str(item.original_image_path.resolve())
        if key in global_used:
            continue
        grouped[item.source_video_id].append(item)
    for items in grouped.values():
        items.sort(key=lambda item: priority_score("real_fall_low_posture_hold", item))

    selected: list[SourceCandidate] = []
    while len(selected) < desired_count:
        progressed = False
        for video_id in sorted(grouped.keys()):
            items = grouped[video_id]
            if not items:
                continue
            candidate = items.pop(0)
            key = str(candidate.original_image_path.resolve())
            if key in global_used:
                continue
            global_used.add(key)
            selected.append(candidate)
            progressed = True
            if len(selected) >= desired_count:
                break
        if not progressed:
            break
    return selected


def load_latest_reviewed_candidates() -> list[SourceCandidate]:
    reviewed_rows = read_csv(REVIEWED_ALL_MANIFEST)
    invalid_images = {row["image"] for row in read_csv(REVIEWED_ALL_INVALID_LABELS)}
    untrusted_images = {row["image"] for row in read_csv(REVIEWED_ALL_UNTRUSTED)}
    conflict_archive_images = {row["archive_image"] for row in read_csv(REVIEWED_ALL_CLASS_CONFLICTS)}

    latest_by_source: dict[str, tuple[int, dict[str, str]]] = {}
    for row in reviewed_rows:
        source_path = str(Path(row["original_image_path"]).resolve())
        batch_token = row["batch_id"].split("_")[1] if "_" in row["batch_id"] else "-1"
        batch_number = int(batch_token) if batch_token.isdigit() else -1
        previous = latest_by_source.get(source_path)
        if previous is None or batch_number > previous[0]:
            latest_by_source[source_path] = (batch_number, row)

    candidates: list[SourceCandidate] = []
    for _batch_number, row in latest_by_source.values():
        original_image = row["original_image"]
        archive_name = Path(row["new_image"]).name
        if original_image in invalid_images or original_image in untrusted_images or archive_name in conflict_archive_images:
            continue

        image_path = REVIEWED_ALL_ROOT / row["new_image"]
        label_path = REVIEWED_ALL_ROOT / row["new_label"]
        if not image_path.exists() or not label_path.exists():
            continue

        class_counts = json.loads(row["class_counts"]) if row["class_counts"] else {}
        if len(class_counts) != 1 or row["is_empty_label"].lower() == "true" or row["box_count"] != "1":
            continue

        class_name = next(iter(class_counts.keys()))
        if class_name not in {"falling", "fallen", "lying", "sitting", "bending", "kneeling"}:
            continue
        if not is_fallish_video(row["source_video"]) or is_adl_video(row["source_video"]):
            continue

        width, height = read_image_size(image_path)
        candidates.append(
            SourceCandidate(
                batch_id=row["batch_id"],
                class_name=class_name,
                source_video=row["source_video"],
                source_video_id=row["video_id"],
                scene=row.get("scene", ""),
                group=row.get("group", ""),
                original_image=row["original_image"],
                original_image_path=Path(row["original_image_path"]),
                original_label_path=Path(row["original_label_path"]),
                original_meta_path=Path(row["original_meta_path"]),
                archive_image_path=image_path,
                archive_label_path=label_path,
                frame_index=frame_index_from_name(row["original_image"]),
                image_sha256=sha256_file(image_path),
                width=width,
                height=height,
            )
        )
    return candidates


def build_exclusion_sets() -> dict[str, set[str]]:
    fixed_rows = read_csv(FIXED_ACCEPTANCE_MANIFEST)
    v3_rows = read_csv(V3_MANIFEST)
    acceptance_only_rows = read_csv(ACCEPTANCE_ONLY_CSV)
    clean_rows = read_csv(CLEAN_REVIEWED_MANIFEST)

    fixed_hashes = {row["image_sha256"] for row in fixed_rows if row.get("image_sha256")}
    acceptance_only_hashes = {
        sha256_file(Path(row["bank_image_path"]))
        for row in acceptance_only_rows
        if Path(row["bank_image_path"]).exists()
    }
    test_hashes = {row["image_hash"] for row in v3_rows if row.get("split") == "test" and row.get("image_hash")}
    acceptance_split_hashes = {
        row["image_hash"] for row in v3_rows if row.get("split") == "acceptance" and row.get("image_hash")
    }
    clean_test_pairs = {
        (row["source_video"], row["source_original_image"])
        for row in clean_rows
        if row.get("split") == "test"
    }

    return {
        "fixed_hashes": fixed_hashes,
        "acceptance_only_hashes": acceptance_only_hashes,
        "test_hashes": test_hashes,
        "acceptance_split_hashes": acceptance_split_hashes,
        "clean_test_pairs": clean_test_pairs,
    }


def filter_no_leak_candidates(candidates: list[SourceCandidate], exclusion_sets: dict[str, set[str]]) -> list[SourceCandidate]:
    filtered: list[SourceCandidate] = []
    for item in candidates:
        if item.image_sha256 in exclusion_sets["fixed_hashes"]:
            continue
        if item.image_sha256 in exclusion_sets["acceptance_only_hashes"]:
            continue
        if item.image_sha256 in exclusion_sets["test_hashes"]:
            continue
        if item.image_sha256 in exclusion_sets["acceptance_split_hashes"]:
            continue
        if (item.source_video, item.original_image) in exclusion_sets["clean_test_pairs"]:
            continue
        filtered.append(item)
    return filtered


def dedupe_candidates_by_sha256(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    deduped: dict[str, SourceCandidate] = {}
    for item in sorted(
        candidates,
        key=lambda candidate: (
            candidate.source_video_id,
            candidate.frame_index if candidate.frame_index >= 0 else 999999,
            candidate.batch_id,
            candidate.original_image,
        ),
    ):
        deduped.setdefault(item.image_sha256, item)
    return list(deduped.values())


def choose_category_items(candidates: list[SourceCandidate]) -> tuple[dict[str, list[SourceCandidate]], list[str]]:
    global_used: set[str] = set()

    hold_candidates = [
        item
        for item in candidates
        if is_hold_family(item.source_video, item.source_video_id, item.scene)
        and item.class_name in {"fallen", "falling", "lying", "bending"}
    ]
    hold_selected = select_hold_samples(
        hold_candidates,
        desired_count=DESIRED_COUNTS["real_fall_low_posture_hold"],
        global_used=global_used,
    )

    slow_candidates = [
        item
        for item in candidates
        if not is_hold_family(item.source_video, item.source_video_id, item.scene)
        and is_slow_fall_family(item.source_video, item.source_video_id)
        and item.class_name in {"falling", "fallen", "lying", "bending", "kneeling", "sitting"}
    ]
    slow_selected = round_robin_select(
        slow_candidates,
        category="slow_fall_positive",
        desired_count=DESIRED_COUNTS["slow_fall_positive"],
        per_video_cap=2,
        global_used=global_used,
    )

    falling_candidates = [
        item
        for item in candidates
        if not is_hold_family(item.source_video, item.source_video_id, item.scene)
        and not is_slow_fall_family(item.source_video, item.source_video_id)
        and item.class_name == "falling"
    ]
    falling_selected = round_robin_select(
        falling_candidates,
        category="falling_transition_positive",
        desired_count=DESIRED_COUNTS["falling_transition_positive"],
        per_video_cap=2,
        global_used=global_used,
    )

    boundary_candidates = [
        item
        for item in candidates
        if not is_hold_family(item.source_video, item.source_video_id, item.scene)
        and not is_slow_fall_family(item.source_video, item.source_video_id)
        and item.class_name in {"fallen", "bending", "kneeling", "sitting", "lying"}
    ]
    boundary_selected = round_robin_select(
        boundary_candidates,
        category="fallen_boundary_positive",
        desired_count=DESIRED_COUNTS["fallen_boundary_positive"],
        per_video_cap=2,
        global_used=global_used,
    )

    selected = {
        "falling_transition_positive": falling_selected,
        "fallen_boundary_positive": boundary_selected,
        "slow_fall_positive": slow_selected,
        "real_fall_low_posture_hold": hold_selected,
    }

    known_gaps: list[str] = []
    for category, minimum in MIN_TARGETS.items():
        actual = len(selected[category])
        if actual < minimum:
            known_gaps.append(f"{category} only {actual} clean no-leak candidates found (< {minimum} target)")
    return selected, known_gaps


def safe_rebuild_output_root() -> None:
    if OUTPUT_ROOT.exists():
        resolved = OUTPUT_ROOT.resolve()
        workspace = ROOT.resolve()
        if workspace not in resolved.parents:
            raise RuntimeError(f"unsafe output path outside workspace: {resolved}")
        shutil.rmtree(resolved)
    for category in CATEGORY_ORDER:
        (OUTPUT_ROOT / "images" / category).mkdir(parents=True, exist_ok=True)
        (OUTPUT_ROOT / "labels" / category).mkdir(parents=True, exist_ok=True)


def copy_dataset(selected: dict[str, list[SourceCandidate]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    manifest_rows: list[dict[str, object]] = []
    review_rows: list[dict[str, object]] = []
    category_counters: dict[str, int] = defaultdict(int)

    for category in CATEGORY_ORDER:
        items = sorted(selected[category], key=lambda item: priority_score(category, item))
        for item in items:
            category_counters[category] += 1
            item_id = f"{ITEM_PREFIX[category]}_{category_counters[category]:04d}"
            image_ext = item.archive_image_path.suffix.lower()
            target_image_path = OUTPUT_ROOT / "images" / category / f"{item_id}{image_ext}"
            target_label_path = OUTPUT_ROOT / "labels" / category / f"{item_id}.txt"
            shutil.copy2(item.archive_image_path, target_image_path)
            shutil.copy2(item.archive_label_path, target_label_path)
            label_sha = sha256_file(target_label_path)
            manifest_rows.append(
                {
                    "item_id": item_id,
                    "category": category,
                    "class_name": item.class_name,
                    "source_dataset": "fall_hint_v2_reviewed_all_b001_b029",
                    "source_image_path": str(item.archive_image_path),
                    "source_label_path": str(item.archive_label_path),
                    "target_image_path": str(target_image_path),
                    "target_label_path": str(target_label_path),
                    "source_video_id": item.source_video_id,
                    "frame_index": item.frame_index,
                    "near_miss_pattern": near_miss_pattern(category, item.class_name, item.source_video, item.source_video_id),
                    "is_positive_repair": True,
                    "use_in_training_future": "pending",
                    "use_in_validation_future": "pending",
                    "use_in_acceptance": False,
                    "manual_review_required": True,
                    "reason": "strict_no_leak_latest_reviewed_positive_candidate",
                    "image_sha256": item.image_sha256,
                    "label_sha256": label_sha,
                    "width": item.width,
                    "height": item.height,
                    "notes": (
                        f"batch_id={item.batch_id}; scene={item.scene}; group={item.group}; "
                        f"original_image={item.original_image}; source_video={item.source_video}; "
                        f"meta={item.original_meta_path}"
                    ),
                }
            )
            review_rows.append(
                {
                    "item_id": item_id,
                    "category": category,
                    "target_image_path": str(target_image_path),
                    "target_label_path": str(target_label_path),
                    "review_decision": "pending",
                    "correct_class": "",
                    "usable_for_training": "pending",
                    "usable_for_validation": "pending",
                    "reject_reason": "",
                    "review_notes": "",
                }
            )
    return manifest_rows, review_rows


def run_no_leak_check(manifest_rows: list[dict[str, object]], exclusion_sets: dict[str, set[str]]) -> dict[str, object]:
    image_hashes = [str(row["image_sha256"]) for row in manifest_rows]
    acceptance_leak_count = sum(1 for row in manifest_rows if str(row["image_sha256"]) in exclusion_sets["fixed_hashes"])
    acceptance_only_leak_count = sum(
        1 for row in manifest_rows if str(row["image_sha256"]) in exclusion_sets["acceptance_only_hashes"]
    )
    test_leak_count = sum(1 for row in manifest_rows if str(row["image_sha256"]) in exclusion_sets["test_hashes"])
    acceptance_split_leak_count = sum(
        1 for row in manifest_rows if str(row["image_sha256"]) in exclusion_sets["acceptance_split_hashes"]
    )
    duplicate_sha256_count = sum(count - 1 for count in Counter(image_hashes).values() if count > 1)
    missing_image_count = sum(1 for row in manifest_rows if not Path(str(row["target_image_path"])).exists())
    missing_label_count = sum(1 for row in manifest_rows if not Path(str(row["target_label_path"])).exists())
    return {
        "acceptance_leak_count": acceptance_leak_count,
        "acceptance_only_leak_count": acceptance_only_leak_count,
        "test_leak_count": test_leak_count,
        "acceptance_split_leak_count": acceptance_split_leak_count,
        "duplicate_sha256_count": duplicate_sha256_count,
        "missing_image_count": missing_image_count,
        "missing_label_count": missing_label_count,
        "pass": all(
            [
                acceptance_leak_count == 0,
                acceptance_only_leak_count == 0,
                test_leak_count == 0,
                acceptance_split_leak_count == 0,
                duplicate_sha256_count == 0,
                missing_image_count == 0,
                missing_label_count == 0,
            ]
        ),
    }


def build_category_distribution(manifest_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_category: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in manifest_rows:
        by_category[str(row["category"])].append(row)
    for category in CATEGORY_ORDER:
        items = by_category.get(category, [])
        rows.append(
            {
                "category": category,
                "count": len(items),
                "class_distribution": json.dumps(Counter(str(item["class_name"]) for item in items), ensure_ascii=False),
            }
        )
    rows.append(
        {
            "category": "total",
            "count": len(manifest_rows),
            "class_distribution": json.dumps(Counter(str(item["class_name"]) for item in manifest_rows), ensure_ascii=False),
        }
    )
    return rows


def render_readme(summary: dict[str, object], no_leak: dict[str, object]) -> str:
    gap_lines = [f"- {item}" for item in summary["known_gaps"]]
    if not gap_lines:
        gap_lines = ["- 当前没有发现低于最低目标的类别缺口。"]
    return "\n".join(
        [
            "# falling_transition_positive_batch_20260705",
            "",
            "这个目录是一批为后续 real_fall_miss 修复准备的正样本候选包。",
            "",
            "## 这是什么",
            "",
            "- 它不是最终训练集，而是一批已经做过 no-leak 排查、等待人工复核的 falling / fallen 正样本候选。",
            "- 样本按四类组织：falling_transition_positive、fallen_boundary_positive、slow_fall_positive、real_fall_low_posture_hold。",
            "",
            "## 为什么要专门补 falling transition",
            "",
            "- 上一阶段 `candidate_v3_c_real_fall_recall_repair_20260705` 的失败点，不是流程没跑通，而是可用的 no-leak falling transition 正样本太少。",
            "- 当前最明显的漏检模式是 `boundary_shift_to_kneeling` 和 `boundary_shift_to_bending`，所以这批数据优先服务这两类边界问题。",
            "",
            "## 这不是最终训练集",
            "",
            "- 本目录里的样本还没有人工二次审核结论。",
            "- `review_queue.csv` 才是后续人工快速审核的入口。",
            "",
            "## 为什么必须先人工审核",
            "",
            "- 这些样本虽然已经过基础筛选和 no-leak 检查，但仍然可能存在边界标签偏差、类别选择不稳、同视频近重复过多等问题。",
            "- 只有人工审核通过的样本，后续才可以进入 `real_fall_recall_repair_r2` 训练集。",
            "",
            "## 为什么不能包含 acceptance / test 泄漏",
            "",
            "- 这批样本的目标是补训练，不是刷分。",
            "- 如果把 acceptance 或 test 样本混进去，后面的 recall 修复就会失真，所以本批明确排除了 fixed acceptance、acceptance_only、test split 和 acceptance split。",
            "",
            "## 后续如何用于 real_fall_recall_repair_r2",
            "",
            "- 第一步：人工审核 `review_queue.csv`。",
            "- 第二步：只保留 `review_decision=accepted` 且 `usable_for_training/usable_for_validation` 明确通过的样本。",
            "- 第三步：把审核通过样本并入下一轮 recall repair 数据集，再单独做一次 no-leak 校验后训练。",
            "",
            "## 当前已知缺口",
            "",
            *gap_lines,
            "",
            "## 当前结果",
            "",
            f"- total_items: {summary['total_items']}",
            f"- no_leak_pass: {summary['no_leak_pass']}",
            f"- manual_review_required: {summary['manual_review_required']}",
            f"- stage_result: {summary['stage_result']}",
            "",
            "## 安全确认",
            "",
            "- 本阶段没有训练模型。",
            "- 本阶段没有替换任何权重。",
            "- 本阶段没有修改 `.env`。",
            "- 本阶段没有修改正式告警链路。",
            "",
            "## no-leak 摘要",
            "",
            f"- acceptance_leak_count: {no_leak['acceptance_leak_count']}",
            f"- acceptance_only_leak_count: {no_leak['acceptance_only_leak_count']}",
            f"- test_leak_count: {no_leak['test_leak_count']}",
            f"- duplicate_sha256_count: {no_leak['duplicate_sha256_count']}",
        ]
    ) + "\n"


def render_build_log(
    *,
    start_ts: str,
    end_ts: str,
    manifest_rows: list[dict[str, object]],
    no_leak: dict[str, object],
    summary: dict[str, object],
) -> str:
    distribution = Counter(str(row["category"]) for row in manifest_rows)
    return "\n".join(
        [
            "# Build Log",
            "",
            f"1. build_start_time: {start_ts}",
            f"2. build_end_time: {end_ts}",
            "3. input_sources: datasets/fall_hint_v2_reviewed_all_b001_b029, datasets/fall_hint_v2_clean_reviewed_only_noaug_20260703, datasets/fall_hint_v2_raw, runs",
            "4. excluded_sources: fixed_acceptance_v1, acceptance_only.csv, all test split samples, all acceptance split samples, invalid labels, untrusted frames, duplicate class conflicts",
            "5. selection_rules: latest reviewed label per raw frame, strict no-leak by image hash, non-ADL fallish videos only, per-video diversity caps, manual-review-first output",
            f"6. category_counts: {json.dumps(distribution, ensure_ascii=False)}",
            f"7. no_leak_check: {json.dumps(no_leak, ensure_ascii=False)}",
            "8. generated_review_queue: YES",
            "9. trained_model: NO",
            "10. replaced_weights: NO",
            "11. modified_env: NO",
            "12. modified_alert_chain: NO",
            f"13. stage_result: {summary['stage_result']}",
        ]
    ) + "\n"


def main() -> int:
    start_ts = datetime.now().isoformat(timespec="seconds")
    exclusion_sets = build_exclusion_sets()
    candidates = load_latest_reviewed_candidates()
    candidates = filter_no_leak_candidates(candidates, exclusion_sets)
    candidates = dedupe_candidates_by_sha256(candidates)
    selected, known_gaps = choose_category_items(candidates)

    safe_rebuild_output_root()
    manifest_rows, review_rows = copy_dataset(selected)
    no_leak = run_no_leak_check(manifest_rows, exclusion_sets)
    category_distribution_rows = build_category_distribution(manifest_rows)

    if not no_leak["pass"]:
        stage_result = "FAIL"
    elif known_gaps:
        stage_result = "PARTIAL"
    else:
        stage_result = "PASS"

    summary = {
        "dataset_name": "falling_transition_positive_batch_20260705",
        "stage": "positive_repair_batch_build",
        "purpose": "repair_real_fall_miss_by_adding_high_quality_falling_transition_samples",
        "total_items": len(manifest_rows),
        "category_distribution": {row["category"]: row["count"] for row in category_distribution_rows if row["category"] != "total"},
        "manual_review_required": True,
        "no_leak_pass": no_leak["pass"],
        "known_gaps": known_gaps if known_gaps else [],
        "safety": {
            "trained_model": False,
            "replaced_weights": False,
            "modified_env": False,
            "modified_alert_chain": False,
        },
        "stage_result": stage_result,
    }

    write_csv(OUTPUT_ROOT / "manifest.csv", manifest_rows)
    write_csv(OUTPUT_ROOT / "category_distribution.csv", category_distribution_rows)
    write_json(OUTPUT_ROOT / "no_leak_check.json", no_leak)
    write_csv(OUTPUT_ROOT / "review_queue.csv", review_rows)
    write_json(OUTPUT_ROOT / "summary.json", summary)
    write_text(OUTPUT_ROOT / "README.md", render_readme(summary, no_leak))
    write_text(
        OUTPUT_ROOT / "build_log.md",
        render_build_log(
            start_ts=start_ts,
            end_ts=datetime.now().isoformat(timespec="seconds"),
            manifest_rows=manifest_rows,
            no_leak=no_leak,
            summary=summary,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
