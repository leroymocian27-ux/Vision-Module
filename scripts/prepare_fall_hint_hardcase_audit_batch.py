from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"
REVIEWED_ROOT = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"
EVAL_ROOT = ROOT / "runs" / "fall_hint_seed_finetune_20260703_v2" / "eval_acceptance"
DEFAULT_BATCH_ID = "batch_031_hardcase_audit"

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
    parser = argparse.ArgumentParser(
        description="Prepare a focused Fall Hint hard-case audit batch from reviewed samples and empty-scene false positives."
    )
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--diagnostic-csv", default=str(EVAL_ROOT / "runtime_current_diagnostic.csv"))
    parser.add_argument("--empty-csv", default=str(EVAL_ROOT / "runtime_current_empty_holdout.csv"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch_dir = RAW_ROOT / args.batch_id
    if batch_dir.exists():
        if not args.overwrite:
            raise SystemExit(f"{batch_dir} already exists; pass --overwrite only if intentionally rebuilding")
        shutil.rmtree(batch_dir)

    frames_dir = batch_dir / "frames"
    prelabels_dir = batch_dir / "prelabels" / "hf_human_fall_yolo11_mapped" / "labels"
    review_labels_dir = batch_dir / "human_review" / "labels"
    review_meta_dir = batch_dir / "human_review" / "meta"
    meta_dir = batch_dir / "meta"
    for path in [frames_dir, prelabels_dir, review_labels_dir, review_meta_dir, meta_dir]:
        path.mkdir(parents=True, exist_ok=True)

    reviewed_manifest = read_csv(REVIEWED_ROOT / "meta" / "manifest.csv")
    reviewed_by_image = {row["new_image"]: row for row in reviewed_manifest}

    diagnostic_rows = read_csv(Path(args.diagnostic_csv))
    empty_rows = read_csv(Path(args.empty_csv))

    candidates = build_candidates(diagnostic_rows, empty_rows, reviewed_by_image)
    selected = select_candidates(candidates, args.limit)

    manifest_rows: list[dict[str, str]] = []
    frame_rows: list[dict[str, str]] = []
    summary_counts: dict[str, int] = defaultdict(int)

    for index, candidate in enumerate(selected, start=1):
        source_image = Path(candidate["source_archive_image"])
        source_label = Path(candidate["source_archive_label"])
        if not source_image.exists() or not source_label.exists():
            continue

        new_name = build_name(
            index=index,
            reason=candidate["audit_reason"],
            batch_id=candidate["source_batch_id"],
            source_stem=source_image.stem,
            suffix=source_image.suffix,
        )
        new_label_name = f"{Path(new_name).stem}.txt"

        shutil.copy2(source_image, frames_dir / new_name)
        shutil.copy2(source_label, prelabels_dir / new_label_name)

        manifest_rows.append(
            {
                "audit_index": f"{index:04d}",
                "audit_image": new_name,
                "audit_label": new_label_name,
                "audit_reason": candidate["audit_reason"],
                "priority": candidate["priority"],
                "source_batch_id": candidate["source_batch_id"],
                "source_original_image": candidate["source_original_image"],
                "source_archive_image": str(source_image.relative_to(ROOT)).replace("\\", "/"),
                "source_archive_label": str(source_label.relative_to(ROOT)).replace("\\", "/"),
                "source_video": candidate["source_video"],
                "gt_classes": candidate["gt_classes"],
                "predicted_top_class": candidate["predicted_top_class"],
                "prediction_box_count": candidate["prediction_box_count"],
                "source_split": candidate["source_split"],
                "note": candidate["note"],
            }
        )
        frame_rows.append(
            {
                "image": new_name,
                "video_id": candidate["source_original_image"],
                "scene": candidate["audit_reason"],
                "group": candidate["priority"],
                "source_video": candidate["source_video"],
                "frame_index": "",
            }
        )
        summary_counts[candidate["audit_reason"]] += 1

    write_csv(meta_dir / "audit_manifest.csv", manifest_rows)
    write_csv(meta_dir / "frame_manifest.csv", frame_rows)
    write_classes(batch_dir / "classes.txt")
    write_readme(batch_dir / "README.md", manifest_rows)

    summary = {
        "batch_id": args.batch_id,
        "batch_dir": str(batch_dir),
        "item_count": len(manifest_rows),
        "requested_limit": args.limit,
        "reason_counts": dict(sorted(summary_counts.items())),
        "review_instruction": "Open in the Fall Hint labeler, verify/correct every bbox and class, save every item as reviewed.",
        "diagnostic_csv": str(Path(args.diagnostic_csv).resolve()),
        "empty_csv": str(Path(args.empty_csv).resolve()),
    }
    (meta_dir / "prepare_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_candidates(
    diagnostic_rows: list[dict[str, str]],
    empty_rows: list[dict[str, str]],
    reviewed_by_image: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []

    for row in diagnostic_rows:
        archive_image = row["image"]
        reviewed = reviewed_by_image.get(archive_image)
        if reviewed is None:
            continue

        gt_classes = row.get("gt_classes", "")
        top_class = row.get("top_class", "")
        reason = ""
        priority = ""
        note = ""
        if row.get("false_fallen_on_adl", "").lower() == "true":
            reason = "adl_false_fallen"
            priority = "must_review"
            note = "ADL sample predicted as fallen."
        elif row.get("kneeling_lying_confusion", "").lower() == "true":
            if gt_classes == "lying":
                reason = "lying_boundary_confusion"
            elif gt_classes == "kneeling":
                reason = "kneeling_boundary_confusion"
            else:
                reason = "hard_boundary_confusion"
            priority = "must_review"
            note = "Hard-case positive with class confusion."
        elif top_class == "none" and gt_classes in {"fallen", "lying", "kneeling", "sitting", "bending", "falling"}:
            reason = "positive_missed_as_none"
            priority = "must_review"
            note = "True positive sample missed completely."
        else:
            continue

        candidates.append(
            {
                "audit_reason": reason,
                "priority": priority,
                "source_batch_id": reviewed["batch_id"],
                "source_original_image": reviewed["original_image"],
                "source_archive_image": str((REVIEWED_ROOT / archive_image).resolve()),
                "source_archive_label": str((REVIEWED_ROOT / reviewed["new_label"]).resolve()),
                "source_video": reviewed.get("source_video", ""),
                "gt_classes": gt_classes,
                "predicted_top_class": top_class,
                "prediction_box_count": reviewed.get("box_count", ""),
                "source_split": row.get("split", ""),
                "note": note,
            }
        )

    for row in empty_rows:
        try:
            prediction_box_count = int(float(row.get("prediction_box_count", "0")))
        except ValueError:
            prediction_box_count = 0
        if prediction_box_count <= 0:
            continue

        archive_image = row["image"]
        archive_key = archive_image.replace("audits/empty_holdout/", "")
        reviewed = reviewed_by_image.get(archive_key)
        if reviewed is None:
            continue

        top_class = row.get("top_class", "")
        reason = "empty_false_positive"
        if top_class == "kneeling":
            reason = "empty_false_positive_kneeling"
        elif top_class == "standing":
            reason = "empty_false_positive_standing"
        elif top_class == "fallen":
            reason = "empty_false_positive_fallen"

        candidates.append(
            {
                "audit_reason": reason,
                "priority": "must_review",
                "source_batch_id": reviewed["batch_id"],
                "source_original_image": reviewed["original_image"],
                "source_archive_image": str((REVIEWED_ROOT / archive_key).resolve()),
                "source_archive_label": str((REVIEWED_ROOT / reviewed["new_label"]).resolve()),
                "source_video": reviewed.get("source_video", ""),
                "gt_classes": "empty",
                "predicted_top_class": top_class,
                "prediction_box_count": str(prediction_box_count),
                "source_split": "empty_holdout",
                "note": "Reviewed empty-label sample that still triggers a false positive.",
            }
        )

    # Add reviewed boundary samples directly from the trusted archive so the batch
    # is not limited to eval/export artifacts only. These are the classes most
    # strongly tied to current confusion and false-fallen drift.
    boundary_reason_by_scene = {
        "lying": "manual_boundary_lying",
        "kneeling": "manual_boundary_kneeling",
        "sitting": "manual_boundary_sitting",
        "bending": "manual_boundary_bending",
        "adl_unknown": "manual_boundary_adl_unknown",
        "unknown": "manual_boundary_unknown",
    }
    for reviewed in reviewed_by_image.values():
        scene = reviewed.get("scene", "")
        group = reviewed.get("group", "")
        reason = boundary_reason_by_scene.get(scene, "")
        if not reason and group == "hardneg":
            reason = "manual_boundary_hardneg"
        if not reason:
            continue
        candidates.append(
            {
                "audit_reason": reason,
                "priority": "targeted_review",
                "source_batch_id": reviewed["batch_id"],
                "source_original_image": reviewed["original_image"],
                "source_archive_image": str((REVIEWED_ROOT / reviewed["new_image"]).resolve()),
                "source_archive_label": str((REVIEWED_ROOT / reviewed["new_label"]).resolve()),
                "source_video": reviewed.get("source_video", ""),
                "gt_classes": reviewed.get("class_counts", ""),
                "predicted_top_class": "",
                "prediction_box_count": reviewed.get("box_count", ""),
                "source_split": "reviewed_archive",
                "note": "Trusted reviewed hard-case sample added for boundary cleanup.",
            }
        )

    return candidates


def select_candidates(candidates: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in candidates:
        buckets[row["audit_reason"]].append(row)

    targets = [
        ("lying_boundary_confusion", 32),
        ("kneeling_boundary_confusion", 18),
        ("adl_false_fallen", 16),
        ("positive_missed_as_none", 20),
        ("empty_false_positive_kneeling", 12),
        ("empty_false_positive_standing", 10),
        ("empty_false_positive_fallen", 6),
        ("empty_false_positive", 6),
        ("hard_boundary_confusion", 8),
        ("manual_boundary_lying", 18),
        ("manual_boundary_kneeling", 18),
        ("manual_boundary_sitting", 12),
        ("manual_boundary_bending", 12),
        ("manual_boundary_adl_unknown", 10),
        ("manual_boundary_hardneg", 18),
        ("manual_boundary_unknown", 6),
    ]

    selected: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str]] = set()
    for reason, target in targets:
        for row in buckets.get(reason, [])[:target]:
            key = (row["source_batch_id"], row["source_original_image"])
            if key in seen_keys:
                continue
            selected.append(row)
            seen_keys.add(key)
            if len(selected) >= limit:
                return selected[:limit]

    for row in candidates:
        key = (row["source_batch_id"], row["source_original_image"])
        if key in seen_keys:
            continue
        selected.append(row)
        seen_keys.add(key)
        if len(selected) >= limit:
            break
    return selected[:limit]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Missing required CSV: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def build_name(index: int, reason: str, batch_id: str, source_stem: str, suffix: str) -> str:
    clean_reason = safe_token(reason)[:28]
    clean_batch = safe_token(batch_id)
    clean_stem = safe_token(source_stem)[:48]
    return f"hardcase_{index:04d}_{clean_reason}_{clean_batch}_{clean_stem}{suffix.lower()}"


def safe_token(value: str) -> str:
    chars = []
    for char in value:
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("_")
    return "_".join("".join(chars).strip("_").split("_"))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        if not fieldnames:
            fh.write("")
            return
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_classes(path: Path) -> None:
    path.write_text(
        "\n".join(CLASS_NAMES[index] for index in sorted(CLASS_NAMES)) + "\n",
        encoding="utf-8",
    )


def write_readme(path: Path, rows: list[dict[str, str]]) -> None:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["audit_reason"]] += 1
    text = "\n".join(
        [
            "# Fall Hint Hard-Case Audit Batch",
            "",
            "This batch is for error-boundary cleanup before the next Fall Hint finetune.",
            "",
            "Focus:",
            "",
            "- lying / kneeling / sitting / bending boundary cases",
            "- ADL falsely drifting toward fallen",
            "- reviewed empty scenes that still trigger false positives",
            "- true positives that the model misses completely",
            "",
            "Review rules:",
            "",
            "1. Keep only the visible, semantically correct class for each box.",
            "2. If the image is truly empty/no person, save an empty label file.",
            "3. If the draft box/class is wrong, correct it rather than trying to preserve the model guess.",
            "4. Save every image so `human_review/meta/*.json` becomes the reviewed ground truth.",
            "",
            "Reason counts:",
            "",
            *[f"- `{reason}`: {count}" for reason, count in sorted(counts.items())],
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
