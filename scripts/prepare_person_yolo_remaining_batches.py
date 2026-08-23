from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "datasets" / "person_yolo_raw"
FALL_HINT_RAW = ROOT / "datasets" / "fall_hint_v2_raw"
FINAL_ROOT = ROOT / "datasets" / "person_yolo"


@dataclass(frozen=True)
class VideoSpec:
    video_id: str
    path: Path
    group: str
    scene: str
    count: int
    start_ratio: float
    end_ratio: float
    source_dataset: str
    license: str
    note: str = ""


@dataclass(frozen=True)
class CuratedSpec:
    source_batch: str
    output_prefix: str
    group: str
    scene: str
    count: int
    start_ratio: float
    end_ratio: float
    source_dataset: str
    license: str
    note: str = ""


def local_video(session: str) -> Path:
    return ROOT / "datasets" / "new_pose_raw" / "camera_01" / session / "video.mp4"


BATCH_SPECS: dict[str, dict[str, list[VideoSpec] | list[CuratedSpec]]] = {
    "batch_003": {
        "videos": [
            VideoSpec("b003_no_person_clean", local_video("session_20260621_160100_no_person"), "no_person", "no_person", 12, 0.00, 0.03, "new_pose_raw", "local_project_data"),
            VideoSpec("b003_ur_adl_walking_10", ROOT / "datasets/ur_fall/videos/adl-10.mp4", "walking", "walking", 8, 0.10, 0.90, "ur_fall", "CC BY-NC-SA 4.0"),
            VideoSpec("b003_ur_adl_sitting_12", ROOT / "datasets/ur_fall/videos/adl-12.mp4", "sitting", "sitting", 8, 0.10, 0.90, "ur_fall", "CC BY-NC-SA 4.0"),
            VideoSpec("b003_multi_bus", ROOT / "tests/fixtures/person_bus_loop.mp4", "multi_occlusion_complex", "multi_person_complex_background", 12, 0.00, 1.00, "test_fixture", "project_fixture"),
        ],
        "curated": [
            CuratedSpec("batch_003", "b003_fallhint_bending_b003", "bending", "bending", 12, 0.00, 0.50, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_003", "b003_fallhint_kneeling_b003", "kneeling", "kneeling", 12, 0.00, 0.50, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_003", "b003_fallhint_lying_b003", "lying", "lying", 12, 0.00, 0.60, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_008", "b003_gmd_falling_b008", "falling", "fall", 16, 0.00, 0.45, "gmdcsa24", "CC BY 4.0"),
            CuratedSpec("batch_004", "b003_fallen_b004", "fallen", "fallen_hold", 12, 0.00, 1.00, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_009", "b003_hard_bed_b009", "hard_negative_object", "lying", 16, 0.00, 0.30, "fall_hint_v2_raw", "mixed_existing_sources", "bed/curtain/furniture hard negatives; label only visible humans"),
        ],
    },
    "batch_004": {
        "videos": [
            VideoSpec("b004_no_person_clean", local_video("session_20260621_160100_no_person"), "no_person", "no_person", 12, 0.00, 0.03, "new_pose_raw", "local_project_data"),
            VideoSpec("b004_local_walking", local_video("session_20260621_160500_walking_slow"), "walking", "walking", 10, 0.20, 0.95, "new_pose_raw", "local_project_data"),
            VideoSpec("b004_local_standing_back", local_video("session_20260621_160400_standing_back"), "standing", "standing", 8, 0.10, 0.90, "new_pose_raw", "local_project_data"),
            VideoSpec("b004_multi_bus", ROOT / "tests/fixtures/person_bus_loop.mp4", "multi_occlusion_complex", "multi_person_complex_background", 10, 0.05, 0.95, "test_fixture", "project_fixture"),
        ],
        "curated": [
            CuratedSpec("batch_004", "b004_lying_b004", "lying", "lying", 18, 0.00, 1.00, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_004", "b004_falling_b004", "falling", "fall", 18, 0.00, 1.00, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_005", "b004_kneeling_b005", "kneeling", "kneeling", 14, 0.00, 0.60, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_011", "b004_bending_b011", "bending", "bending", 12, 0.00, 1.00, "gmdcsa24", "CC BY 4.0"),
            CuratedSpec("batch_010", "b004_gmd_falling_b010", "falling", "fall", 18, 0.45, 0.85, "gmdcsa24", "CC BY 4.0"),
        ],
    },
    "batch_005": {
        "videos": [
            VideoSpec("b005_no_person_clean", local_video("session_20260621_160100_no_person"), "no_person", "no_person", 12, 0.00, 0.03, "new_pose_raw", "local_project_data"),
            VideoSpec("b005_ur_adl_bending_24", ROOT / "datasets/ur_fall/videos/adl-24.mp4", "bending", "bending", 8, 0.10, 0.95, "ur_fall", "CC BY-NC-SA 4.0"),
            VideoSpec("b005_ur_adl_walking_30", ROOT / "datasets/ur_fall/videos/adl-30.mp4", "walking", "walking", 10, 0.05, 0.95, "ur_fall", "CC BY-NC-SA 4.0"),
            VideoSpec("b005_multi_bus", ROOT / "tests/fixtures/person_bus_loop.mp4", "multi_occlusion_complex", "multi_person_complex_background", 12, 0.00, 1.00, "test_fixture", "project_fixture"),
        ],
        "curated": [
            CuratedSpec("batch_005", "b005_lying_b005", "lying", "lying", 18, 0.00, 1.00, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_005", "b005_falling_b005", "falling", "fall", 18, 0.00, 1.00, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_006", "b005_kneeling_b006", "kneeling", "kneeling", 18, 0.00, 0.80, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_007", "b005_user_fall_b007", "falling", "fall", 12, 0.15, 0.45, "user_desktop", "local_project_data"),
            CuratedSpec("batch_009", "b005_hard_bed_b009", "hard_negative_object", "lying", 12, 0.30, 0.60, "fall_hint_v2_raw", "mixed_existing_sources", "bed/edge hard negatives; label only visible humans"),
        ],
    },
    "batch_006": {
        "videos": [
            VideoSpec("b006_no_person_clean", local_video("session_20260621_160100_no_person"), "no_person", "no_person", 12, 0.00, 0.03, "new_pose_raw", "local_project_data"),
            VideoSpec("b006_local_sitting_side", local_video("session_20260621_160700_sitting_side"), "sitting", "sitting", 10, 0.25, 0.95, "new_pose_raw", "local_project_data"),
            VideoSpec("b006_local_bending", local_video("session_20260621_160800_bending_pickup"), "bending", "bending", 10, 0.25, 0.95, "new_pose_raw", "local_project_data"),
            VideoSpec("b006_multi_bus", ROOT / "tests/fixtures/person_bus_loop.mp4", "multi_occlusion_complex", "multi_person_complex_background", 10, 0.00, 1.00, "test_fixture", "project_fixture"),
        ],
        "curated": [
            CuratedSpec("batch_006", "b006_lying_b006", "lying", "lying", 20, 0.00, 1.00, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_006", "b006_falling_b006", "falling", "fall", 18, 0.00, 1.00, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_010", "b006_kneeling_b010", "kneeling", "kneeling", 12, 0.00, 1.00, "fall_hint_v2_raw", "mixed_existing_sources"),
            CuratedSpec("batch_011", "b006_gmd_fall_b011", "falling", "fall", 18, 0.00, 0.35, "gmdcsa24", "CC BY 4.0"),
            CuratedSpec("batch_009", "b006_hard_bed_b009", "hard_negative_object", "lying", 10, 0.60, 0.90, "fall_hint_v2_raw", "mixed_existing_sources", "bed/window/edge hard negatives; label only visible humans"),
        ],
    },
    "batch_007": {
        "videos": [
            VideoSpec("b007_no_person_clean", local_video("session_20260621_160100_no_person"), "no_person", "no_person", 12, 0.00, 0.03, "new_pose_raw", "local_project_data"),
            VideoSpec("b007_ur_fall_late_02", ROOT / "datasets/ur_fall/videos/fall-02.mp4", "fallen", "fallen", 12, 0.60, 0.95, "ur_fall", "CC BY-NC-SA 4.0"),
            VideoSpec("b007_ur_adl_stand_31", ROOT / "datasets/ur_fall/videos/adl-31.mp4", "standing", "standing", 8, 0.05, 0.95, "ur_fall", "CC BY-NC-SA 4.0"),
            VideoSpec("b007_multi_bus", ROOT / "tests/fixtures/person_bus_loop.mp4", "multi_occlusion_complex", "multi_person_complex_background", 12, 0.00, 1.00, "test_fixture", "project_fixture"),
        ],
        "curated": [
            CuratedSpec("batch_007", "b007_user_fall_b007", "falling", "fall", 18, 0.45, 0.85, "user_desktop", "local_project_data"),
            CuratedSpec("batch_008", "b007_gmd_kneeling_b008", "kneeling", "kneeling", 18, 0.00, 1.00, "gmdcsa24", "CC BY 4.0"),
            CuratedSpec("batch_008", "b007_gmd_lying_b008", "lying", "lying", 12, 0.00, 1.00, "gmdcsa24", "CC BY 4.0"),
            CuratedSpec("batch_009", "b007_gmd_lying_b009", "lying", "lying", 18, 0.00, 0.50, "gmdcsa24", "CC BY 4.0"),
            CuratedSpec("batch_011", "b007_bending_b011", "bending", "bending", 10, 0.00, 1.00, "gmdcsa24", "CC BY 4.0"),
        ],
    },
    "batch_008": {
        "videos": [
            VideoSpec("b008_no_person_clean", local_video("session_20260621_160100_no_person"), "no_person", "no_person", 12, 0.00, 0.03, "new_pose_raw", "local_project_data"),
            VideoSpec("b008_local_walking", local_video("session_20260621_160500_walking_slow"), "walking", "walking", 8, 0.10, 0.95, "new_pose_raw", "local_project_data"),
            VideoSpec("b008_ur_adl_sitting_13", ROOT / "datasets/ur_fall/videos/adl-13.mp4", "sitting", "sitting", 8, 0.10, 0.95, "ur_fall", "CC BY-NC-SA 4.0"),
            VideoSpec("b008_multi_bus", ROOT / "tests/fixtures/person_bus_loop.mp4", "multi_occlusion_complex", "multi_person_complex_background", 12, 0.00, 1.00, "test_fixture", "project_fixture"),
        ],
        "curated": [
            CuratedSpec("batch_008", "b008_gmd_fall_b008", "falling", "fall", 18, 0.45, 1.00, "gmdcsa24", "CC BY 4.0"),
            CuratedSpec("batch_009", "b008_gmd_fall_b009", "falling", "fall", 18, 0.00, 1.00, "gmdcsa24", "CC BY 4.0"),
            CuratedSpec("batch_009", "b008_gmd_lying_b009", "lying", "lying", 18, 0.50, 1.00, "gmdcsa24", "CC BY 4.0"),
            CuratedSpec("batch_012", "b008_target_kneeling_b012", "kneeling", "kneeling", 14, 0.60, 0.95, "local_targeted_recording", "local_project_data"),
            CuratedSpec("batch_009", "b008_hard_bed_b009", "hard_negative_object", "lying", 12, 0.10, 0.90, "fall_hint_v2_raw", "mixed_existing_sources", "bed/window/edge hard negatives; label only visible humans"),
        ],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare remaining person YOLO batches batch_003..batch_008.")
    parser.add_argument("--batch-id", action="append", choices=sorted(BATCH_SPECS), help="Generate only this batch id. Can be repeated.")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    batch_ids = args.batch_id or sorted(BATCH_SPECS)
    for batch_id in batch_ids:
        prepare_batch(batch_id, overwrite=args.overwrite)
    return 0


def prepare_batch(batch_id: str, *, overwrite: bool) -> None:
    batch_dir = RAW_ROOT / batch_id
    if batch_dir.exists() and overwrite:
        shutil.rmtree(batch_dir)
    create_structure(batch_dir)

    spec = BATCH_SPECS[batch_id]
    videos: list[VideoSpec] = spec["videos"]  # type: ignore[assignment]
    curated: list[CuratedSpec] = spec["curated"]  # type: ignore[assignment]

    existing_videos = [item for item in videos if item.path.exists()]
    missing_videos = [item for item in videos if not item.path.exists()]
    rows = extract_video_frames(existing_videos, batch_dir / "frames")
    rows.extend(copy_curated_frames(curated, batch_dir / "frames"))
    if len(rows) != 120:
        raise SystemExit(f"{batch_id}: expected 120 frames, got {len(rows)}")

    write_source_videos(batch_dir / "meta" / "source_videos.csv", existing_videos, missing_videos)
    write_frame_manifest(batch_dir / "meta" / "frame_manifest.csv", rows)
    write_labeling_guide(batch_dir / "meta" / "labeling_guide.md")
    write_data_yaml(FINAL_ROOT / "data.yaml")
    write_summary(batch_dir / "meta" / "prepare_summary.json", batch_id, existing_videos, missing_videos, rows)
    write_preview(batch_dir)
    print(f"[OK] {batch_id}: frames={len(rows)} sources={len(existing_videos)} missing={len(missing_videos)}")


def create_structure(batch_dir: Path) -> None:
    for path in [
        batch_dir / "frames",
        batch_dir / "human_review" / "labels",
        batch_dir / "human_review" / "meta",
        batch_dir / "meta",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def extract_video_frames(sources: list[VideoSpec], frame_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in sources:
        cap = cv2.VideoCapture(str(source.path))
        if not cap.isOpened():
            print(f"[WARN] Could not open {source.path}")
            continue
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        for out_index, frame_index in enumerate(sample_indices(total, source.count, source.start_ratio, source.end_ratio)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            image_name = f"{source.video_id}_{out_index:03d}.jpg"
            image_path = frame_dir / image_name
            cv2.imwrite(str(image_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            rows.append(row_for_image(image_name, image_path, source.video_id, str(source.path), source.source_dataset, source.license, source.group, source.scene, frame_index, int(round((frame_index / fps) * 1000)) if fps > 0 else "", source.start_ratio, source.end_ratio, source.note))
        cap.release()
    return rows


def copy_curated_frames(specs: list[CuratedSpec], frame_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for spec in specs:
        batch_dir = FALL_HINT_RAW / spec.source_batch
        source_frames = batch_dir / "frames"
        manifest_path = batch_dir / "meta" / "frame_manifest.csv"
        if not source_frames.exists() or not manifest_path.exists():
            print(f"[WARN] Missing curated source: {batch_dir}")
            continue
        manifest_rows = list(csv.DictReader(manifest_path.open("r", newline="", encoding="utf-8")))
        candidates = filter_scene_rows(manifest_rows, spec.scene)
        indices = sample_indices(len(candidates), spec.count, spec.start_ratio, spec.end_ratio)
        for out_index, row_index in enumerate(indices):
            source_row = candidates[row_index]
            src = source_frames / source_row["image"]
            if not src.exists():
                continue
            image_name = f"{spec.output_prefix}_{out_index:03d}{src.suffix.lower()}"
            dst = frame_dir / image_name
            shutil.copy2(src, dst)
            rows.append(row_for_image(image_name, dst, spec.output_prefix, source_row.get("source_video", str(src)), spec.source_dataset, spec.license, spec.group, spec.scene, source_row.get("source_frame_index", ""), source_row.get("timestamp_ms", ""), spec.start_ratio, spec.end_ratio, spec.note))
    return rows


def filter_scene_rows(rows: list[dict[str, str]], scene: str) -> list[dict[str, str]]:
    aliases = {
        "falling": {"fall", "falling"},
        "fallen": {"fallen_hold", "fallen"},
        "fall": {"fall", "falling"},
        "lying": {"lying"},
        "kneeling": {"kneeling"},
        "bending": {"bending"},
        "sitting": {"sitting"},
        "standing": {"standing"},
        "walking": {"walking"},
        "no_person": {"no_person"},
    }
    wanted = aliases.get(scene, {scene})
    filtered = [row for row in rows if row.get("scene") in wanted]
    return filtered or rows


def sample_indices(total: int, count: int, start_ratio: float, end_ratio: float) -> list[int]:
    if total <= 0 or count <= 0:
        return []
    start = max(0, min(total - 1, int(total * start_ratio)))
    end = max(start, min(total - 1, int(total * end_ratio)))
    if count == 1:
        return [(start + end) // 2]
    span = max(1, end - start)
    return [min(total - 1, start + round(span * index / (count - 1))) for index in range(count)]


def row_for_image(
    image_name: str,
    image_path: Path,
    video_id: str,
    source_video: str,
    source_dataset: str,
    license_name: str,
    group: str,
    scene: str,
    source_frame_index: object,
    timestamp_ms: object,
    start_ratio: object,
    end_ratio: object,
    note: str,
) -> dict[str, object]:
    return {
        "annotation_status": "needs_human_review",
        "group": group,
        "scene": scene,
        "image": image_name,
        "image_path": str(image_path.relative_to(ROOT)).replace("\\", "/"),
        "license": license_name,
        "source_dataset": source_dataset,
        "source_frame_index": source_frame_index,
        "source_video": source_video,
        "start_ratio": start_ratio,
        "end_ratio": end_ratio,
        "timestamp_ms": timestamp_ms,
        "video_id": video_id,
        "note": note,
    }


def write_source_videos(path: Path, sources: list[VideoSpec], missing: list[VideoSpec]) -> None:
    fieldnames = ["video_id", "source_path", "group", "scene", "frames", "start_ratio", "end_ratio", "source_dataset", "license", "exists", "note"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for source, exists in [(item, True) for item in sources] + [(item, False) for item in missing]:
            writer.writerow({
                "video_id": source.video_id,
                "source_path": str(source.path),
                "group": source.group,
                "scene": source.scene,
                "frames": source.count,
                "start_ratio": source.start_ratio,
                "end_ratio": source.end_ratio,
                "source_dataset": source.source_dataset,
                "license": source.license,
                "exists": exists,
                "note": source.note,
            })


def write_frame_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = ["annotation_status", "group", "scene", "image", "image_path", "license", "source_dataset", "source_frame_index", "source_video", "start_ratio", "end_ratio", "timestamp_ms", "video_id", "note"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_labeling_guide(path: Path) -> None:
    path.write_text(
        "\n".join([
            "# YOLO person batch labeling guide",
            "",
            "- Class 0 only: person.",
            "- Label every visible human as person.",
            "- Do not label actions such as falling/fallen/sitting/kneeling/bending.",
            "- No-person frames: leave labels empty and save.",
            "- Hard-negative-object frames: label visible humans only; do not box bed, chair, curtain, cabinet, monitor, shadow, or furniture.",
        ]) + "\n",
        encoding="utf-8",
    )


def write_data_yaml(path: Path) -> None:
    path.write_text(
        "\n".join([f"path: {FINAL_ROOT.as_posix()}", "train: images/train", "val: images/val", "test: images/test", "names:", "  0: person", ""]) ,
        encoding="utf-8",
    )


def write_summary(path: Path, batch_id: str, sources: list[VideoSpec], missing: list[VideoSpec], rows: list[dict[str, object]]) -> None:
    groups: dict[str, int] = {}
    datasets: dict[str, int] = {}
    for row in rows:
        groups[str(row["group"])] = groups.get(str(row["group"]), 0) + 1
        datasets[str(row["source_dataset"])] = datasets.get(str(row["source_dataset"]), 0) + 1
    payload = {
        "batch_id": batch_id,
        "source_video_count": len(sources),
        "missing_source_video_count": len(missing),
        "image_count": len(rows),
        "groups": dict(sorted(groups.items())),
        "source_datasets": dict(sorted(datasets.items())),
        "classes": ["person"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_preview(batch_dir: Path) -> None:
    import numpy as np

    frames = batch_dir / "frames"
    rows = list(csv.DictReader((batch_dir / "meta" / "frame_manifest.csv").open("r", newline="", encoding="utf-8")))
    by_group: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_group.setdefault(row["group"], []).append(row)
    selected: list[dict[str, str]] = []
    for group in sorted(by_group):
        values = by_group[group]
        picks = [0, len(values) // 2, len(values) - 1] if len(values) >= 3 else list(range(len(values)))
        selected.extend(values[index] for index in picks)
    thumbs = []
    for row in selected:
        img = cv2.imread(str(frames / row["image"]))
        if img is None:
            continue
        h, w = img.shape[:2]
        scale = min(220 / w, 140 / h)
        resized = cv2.resize(img, (int(w * scale), int(h * scale)))
        canvas = np.full((172, 244, 3), 245, dtype=np.uint8)
        x = (244 - resized.shape[1]) // 2
        canvas[: resized.shape[0], x : x + resized.shape[1]] = resized
        label = f"{row['group']} | {row['image'][:24]}"
        cv2.putText(canvas, label, (6, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (20, 20, 20), 1, cv2.LINE_AA)
        thumbs.append(canvas)
    cols = 4
    pad = 8
    sheet_h = ((len(thumbs) + cols - 1) // cols) * (172 + pad) + pad
    sheet_w = cols * (244 + pad) + pad
    sheet = np.full((sheet_h, sheet_w, 3), 230, dtype=np.uint8)
    for index, thumb in enumerate(thumbs):
        row, col = divmod(index, cols)
        y = pad + row * (172 + pad)
        x = pad + col * (244 + pad)
        sheet[y : y + 172, x : x + 244] = thumb
    cv2.imwrite(str(batch_dir / "meta" / "preview_contact_sheet.jpg"), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 92])


if __name__ == "__main__":
    raise SystemExit(main())
