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
FINAL_ROOT = ROOT / "datasets" / "person_yolo"


@dataclass(frozen=True)
class SourceVideo:
    video_id: str
    source_path: Path
    group: str
    scene: str
    frames: int
    start_ratio: float = 0.05
    end_ratio: float = 0.95
    source_dataset: str = "local_project_data"
    license: str = "local_project_data"
    note: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a 120-image YOLO person human-label batch.")
    parser.add_argument("--batch-id", default="batch_001")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    batch_dir = RAW_ROOT / args.batch_id
    if batch_dir.exists() and args.overwrite:
        shutil.rmtree(batch_dir)
    create_structure(batch_dir)

    if args.batch_id == "batch_001":
        all_sources = batch_001_sources()
        sources = [source for source in all_sources if source.source_path.exists()]
        missing = [source for source in all_sources if not source.source_path.exists()]
        rows = extract_frames(sources, batch_dir / "frames")
        rows.extend(copy_curated_frame_sets(batch_dir / "frames"))
    elif args.batch_id == "batch_002":
        all_sources = batch_002_sources()
        sources = [source for source in all_sources if source.source_path.exists()]
        missing = [source for source in all_sources if not source.source_path.exists()]
        rows = extract_frames(sources, batch_dir / "frames")
        rows.extend(copy_batch_002_curated_frame_sets(batch_dir / "frames"))
    else:
        raise SystemExit(f"Unsupported batch id: {args.batch_id}")

    write_source_videos(batch_dir / "meta" / "source_videos.csv", sources, missing)
    write_frame_manifest(batch_dir / "meta" / "frame_manifest.csv", rows)
    write_labeling_guide(batch_dir / "meta" / "labeling_guide.md")
    write_data_yaml(FINAL_ROOT / "data.yaml")
    write_summary(batch_dir / "meta" / "prepare_summary.json", sources, missing, rows)

    print(f"[OK] batch_dir={batch_dir}")
    print(f"[OK] source_videos={len(sources)} missing={len(missing)}")
    print(f"[OK] extracted_frames={len(rows)}")
    print("[NEXT] Start tools/person_labeler/server.py and label only class 0: person.")
    return 0


def create_structure(batch_dir: Path) -> None:
    for path in [
        batch_dir / "frames",
        batch_dir / "human_review" / "labels",
        batch_dir / "human_review" / "meta",
        batch_dir / "meta",
        FINAL_ROOT / "images" / "train",
        FINAL_ROOT / "images" / "val",
        FINAL_ROOT / "images" / "test",
        FINAL_ROOT / "labels" / "train",
        FINAL_ROOT / "labels" / "val",
        FINAL_ROOT / "labels" / "test",
        FINAL_ROOT / "meta",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def batch_001_sources() -> list[SourceVideo]:
    local = ROOT / "datasets" / "new_pose_raw" / "camera_01"
    return [
        SourceVideo(
            "local_no_person",
            local / "session_20260621_160100_no_person" / "video.mp4",
            "no_person",
            "no_person",
            12,
            start_ratio=0.0,
            end_ratio=0.03,
            note="empty room negative",
        ),
        SourceVideo(
            "local_standing_front",
            local / "session_20260621_160200_standing_front" / "video.mp4",
            "standing",
            "standing",
            4,
        ),
        SourceVideo(
            "local_standing_side",
            local / "session_20260621_160300_standing_side" / "video.mp4",
            "standing",
            "standing",
            4,
        ),
        SourceVideo(
            "local_recovery_standing",
            local / "session_20260621_161600_recovery_standing" / "video.mp4",
            "standing",
            "standing",
            4,
        ),
        SourceVideo(
            "local_walking_slow",
            local / "session_20260621_160500_walking_slow" / "video.mp4",
            "walking",
            "walking",
            8,
            start_ratio=0.15,
            end_ratio=0.9,
        ),
        SourceVideo(
            "ur_adl_walking_like",
            ROOT / "datasets" / "ur_fall" / "videos" / "adl-10.mp4",
            "walking",
            "walking",
            4,
            source_dataset="ur_fall",
            license="CC BY-NC-SA 4.0",
            note="public ADL sample for viewpoint diversity",
        ),
        SourceVideo(
            "local_sitting_normal",
            local / "session_20260621_160600_sitting_normal" / "video.mp4",
            "sitting",
            "sitting",
            4,
            start_ratio=0.25,
            end_ratio=0.9,
        ),
        SourceVideo(
            "local_sitting_side",
            local / "session_20260621_160700_sitting_side" / "video.mp4",
            "sitting",
            "sitting",
            4,
            start_ratio=0.25,
            end_ratio=0.9,
        ),
        SourceVideo(
            "local_sitting_retake",
            local / "session_20260621_151101_sitting_normal_retake_b" / "video.mp4",
            "sitting",
            "sitting",
            4,
            start_ratio=0.25,
            end_ratio=0.9,
        ),
        SourceVideo(
            "local_bending_pickup",
            local / "session_20260621_160800_bending_pickup" / "video.mp4",
            "bending",
            "bending",
            8,
            start_ratio=0.25,
            end_ratio=0.9,
        ),
        SourceVideo(
            "ur_adl_bending_like",
            ROOT / "datasets" / "ur_fall" / "videos" / "adl-24.mp4",
            "bending",
            "bending",
            4,
            source_dataset="ur_fall",
            license="CC BY-NC-SA 4.0",
        ),
        SourceVideo(
            "ur_fall_fallen_late",
            ROOT / "datasets" / "ur_fall" / "videos" / "fall-01.mp4",
            "fallen",
            "fallen",
            12,
            start_ratio=0.65,
            end_ratio=0.95,
            source_dataset="ur_fall",
            license="CC BY-NC-SA 4.0",
        ),
        SourceVideo(
            "fixture_person_bus_loop",
            ROOT / "tests" / "fixtures" / "person_bus_loop.mp4",
            "multi_occlusion_complex",
            "multi_person_complex_background",
            12,
            source_dataset="test_fixture",
            license="project_fixture",
            note="multi-person/complex background sample",
        ),
    ]


def batch_002_sources() -> list[SourceVideo]:
    local = ROOT / "datasets" / "new_pose_raw" / "camera_01"
    return [
        SourceVideo(
            "b002_local_no_person_clean",
            local / "session_20260621_160100_no_person" / "video.mp4",
            "no_person",
            "no_person",
            18,
            start_ratio=0.0,
            end_ratio=0.03,
            note="empty room negative with monitor/chair edges",
        ),
        SourceVideo(
            "b002_local_bending_pickup_late",
            local / "session_20260621_160800_bending_pickup" / "video.mp4",
            "bending",
            "bending",
            6,
            start_ratio=0.45,
            end_ratio=0.95,
        ),
        SourceVideo(
            "b002_ur_adl_bending_like",
            ROOT / "datasets" / "ur_fall" / "videos" / "adl-24.mp4",
            "bending",
            "bending",
            6,
            start_ratio=0.10,
            end_ratio=0.90,
            source_dataset="ur_fall",
            license="CC BY-NC-SA 4.0",
        ),
        SourceVideo(
            "b002_fixture_person_bus_loop",
            ROOT / "tests" / "fixtures" / "person_bus_loop.mp4",
            "multi_occlusion_complex",
            "multi_person_complex_background",
            12,
            start_ratio=0.02,
            end_ratio=0.98,
            source_dataset="test_fixture",
            license="project_fixture",
            note="multi-person/occlusion complex background",
        ),
    ]


def extract_frames(sources: list[SourceVideo], frame_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in sources:
        cap = cv2.VideoCapture(str(source.source_path))
        if not cap.isOpened():
            print(f"[WARN] Could not open {source.source_path}")
            continue
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        indices = sample_indices(total, source.frames, source.start_ratio, source.end_ratio)
        for out_index, frame_index in enumerate(indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok or frame is None:
                print(f"[WARN] Could not read frame {frame_index} from {source.source_path}")
                continue
            image_name = f"{source.video_id}_{out_index:03d}.jpg"
            image_path = frame_dir / image_name
            cv2.imwrite(str(image_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            rows.append(
                {
                    "image": image_name,
                    "image_path": str(image_path.relative_to(ROOT)).replace("\\", "/"),
                    "video_id": source.video_id,
                    "source_video": str(source.source_path),
                    "source_dataset": source.source_dataset,
                    "license": source.license,
                    "group": source.group,
                    "scene": source.scene,
                    "source_frame_index": frame_index,
                    "timestamp_ms": int(round((frame_index / fps) * 1000)) if fps > 0 else "",
                    "start_ratio": source.start_ratio,
                    "end_ratio": source.end_ratio,
                    "annotation_status": "needs_human_review",
                    "note": source.note,
                }
            )
        cap.release()
    return rows


def copy_curated_frame_sets(frame_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    rows.extend(
        copy_curated_frames(
            frame_dir=frame_dir,
            source_batch=ROOT / "datasets" / "fall_hint_v2_raw" / "batch_009",
            output_prefix="curated_lying_b009",
            group="lying",
            scene="lying",
            count=12,
            source_dataset="fall_hint_v2_raw",
            license_name="mixed_existing_sources",
            note="curated lying raw frames copied from fall_hint_v2_raw batch_009; labels reset for person task",
        )
    )
    rows.extend(
        copy_curated_frames(
            frame_dir=frame_dir,
            source_batch=ROOT / "datasets" / "fall_hint_v2_raw" / "batch_012",
            output_prefix="curated_kneeling_b012",
            group="kneeling",
            scene="kneeling",
            count=12,
            source_dataset="local_targeted_recording",
            license_name="local_project_data",
            note="curated kneeling raw frames copied from fall_hint_v2_raw batch_012; labels reset for person task",
        )
    )
    rows.extend(
        copy_curated_frames(
            frame_dir=frame_dir,
            source_batch=ROOT / "datasets" / "fall_hint_v2_raw" / "batch_008",
            output_prefix="curated_falling_b008",
            group="falling",
            scene="falling",
            count=6,
            source_dataset="gmdcsa24",
            license_name="CC BY 4.0",
            note="curated fall transition raw frames copied from fall_hint_v2_raw batch_008; labels reset for person task",
        )
    )
    rows.extend(
        copy_curated_frames(
            frame_dir=frame_dir,
            source_batch=ROOT / "datasets" / "fall_hint_v2_raw" / "batch_011",
            output_prefix="curated_falling_b011",
            group="falling",
            scene="falling",
            count=6,
            source_dataset="gmdcsa24",
            license_name="CC BY 4.0",
            note="curated fall transition raw frames copied from fall_hint_v2_raw batch_011; labels reset for person task",
        )
    )
    return rows


def copy_batch_002_curated_frame_sets(frame_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    rows.extend(
        copy_curated_frames(
            frame_dir=frame_dir,
            source_batch=ROOT / "datasets" / "fall_hint_v2_raw" / "batch_002",
            output_prefix="b002_sitting_b002",
            group="sitting",
            scene="sitting",
            count=6,
            source_dataset="fall_hint_v2_raw",
            license_name="mixed_existing_sources",
            note="sitting/low seated posture; labels reset for person task",
        )
    )
    rows.extend(
        copy_curated_frames(
            frame_dir=frame_dir,
            source_batch=ROOT / "datasets" / "fall_hint_v2_raw" / "batch_004",
            output_prefix="b002_lying_b004",
            group="lying",
            scene="lying",
            count=12,
            source_dataset="fall_hint_v2_raw",
            license_name="mixed_existing_sources",
            note="lying hard person recall frames; labels reset for person task",
        )
    )
    rows.extend(
        copy_curated_frames(
            frame_dir=frame_dir,
            source_batch=ROOT / "datasets" / "fall_hint_v2_raw" / "batch_006",
            output_prefix="b002_lying_b006",
            group="lying",
            scene="lying",
            count=6,
            source_dataset="fall_hint_v2_raw",
            license_name="mixed_existing_sources",
            note="lying hard person recall frames; labels reset for person task",
        )
    )
    rows.extend(
        copy_curated_frames(
            frame_dir=frame_dir,
            source_batch=ROOT / "datasets" / "fall_hint_v2_raw" / "batch_007",
            output_prefix="b002_falling_b007",
            group="falling",
            scene="falling",
            count=12,
            source_dataset="user_desktop",
            license_name="local_project_data",
            note="fall transition / low posture frames; labels reset for person task",
        )
    )
    rows.extend(
        copy_curated_frames(
            frame_dir=frame_dir,
            source_batch=ROOT / "datasets" / "fall_hint_v2_raw" / "batch_010",
            output_prefix="b002_falling_b010",
            group="falling",
            scene="falling",
            count=12,
            source_dataset="gmdcsa24",
            license_name="CC BY 4.0",
            note="fall transition / low posture frames; labels reset for person task",
        )
    )
    rows.extend(
        copy_curated_frames(
            frame_dir=frame_dir,
            source_batch=ROOT / "datasets" / "fall_hint_v2_raw" / "batch_012",
            output_prefix="b002_kneeling_b012",
            group="kneeling",
            scene="kneeling",
            count=18,
            source_dataset="local_targeted_recording",
            license_name="local_project_data",
            note="targeted kneeling frames; labels reset for person task",
        )
    )
    rows.extend(
        copy_curated_frames(
            frame_dir=frame_dir,
            source_batch=ROOT / "datasets" / "fall_hint_v2_raw" / "batch_009",
            output_prefix="b002_bed_edge_b009",
            group="hard_negative_object",
            scene="lying",
            count=12,
            source_dataset="fall_hint_v2_raw",
            license_name="mixed_existing_sources",
            note="bed/curtain/edge hard negatives; label visible humans only, leave furniture unboxed",
        )
    )
    return rows


def copy_curated_frames(
    frame_dir: Path,
    source_batch: Path,
    output_prefix: str,
    group: str,
    scene: str,
    count: int,
    source_dataset: str,
    license_name: str,
    note: str,
) -> list[dict[str, object]]:
    source_frames = source_batch / "frames"
    manifest_path = source_batch / "meta" / "frame_manifest.csv"
    if not source_frames.exists() or not manifest_path.exists():
        print(f"[WARN] Missing curated frame set: {source_batch}")
        return []
    source_rows = list(csv.DictReader(manifest_path.open("r", newline="", encoding="utf-8")))
    source_rows = [row for row in source_rows if row.get("scene") in {scene, "fall", "kneeling"}]
    if not source_rows:
        source_rows = list(csv.DictReader(manifest_path.open("r", newline="", encoding="utf-8")))
    indices = sample_indices(len(source_rows), count, 0.15, 0.85)
    rows: list[dict[str, object]] = []
    for out_index, row_index in enumerate(indices):
        source_row = source_rows[row_index]
        src = source_frames / str(source_row["image"])
        if not src.exists():
            continue
        image_name = f"{output_prefix}_{out_index:03d}{src.suffix.lower()}"
        dst = frame_dir / image_name
        shutil.copy2(src, dst)
        rows.append(
            {
                "image": image_name,
                "image_path": str(dst.relative_to(ROOT)).replace("\\", "/"),
                "video_id": output_prefix,
                "source_video": source_row.get("source_video", str(src)),
                "source_dataset": source_dataset,
                "license": license_name,
                "group": group,
                "scene": scene,
                "source_frame_index": source_row.get("source_frame_index", ""),
                "timestamp_ms": source_row.get("timestamp_ms", ""),
                "start_ratio": "",
                "end_ratio": "",
                "annotation_status": "needs_human_review",
                "note": note,
            }
        )
    return rows


def sample_indices(total_frames: int, count: int, start_ratio: float, end_ratio: float) -> list[int]:
    if total_frames <= 0 or count <= 0:
        return []
    start = max(0, min(total_frames - 1, int(total_frames * start_ratio)))
    end = max(start, min(total_frames - 1, int(total_frames * end_ratio)))
    if count == 1:
        return [(start + end) // 2]
    span = max(1, end - start)
    return [min(total_frames - 1, start + round(span * i / (count - 1))) for i in range(count)]


def write_source_videos(path: Path, sources: list[SourceVideo], missing: list[SourceVideo]) -> None:
    fieldnames = [
        "video_id",
        "source_path",
        "group",
        "scene",
        "frames",
        "start_ratio",
        "end_ratio",
        "source_dataset",
        "license",
        "exists",
        "note",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for source, exists in [(item, True) for item in sources] + [(item, False) for item in missing]:
            writer.writerow(
                {
                    "video_id": source.video_id,
                    "source_path": str(source.source_path),
                    "group": source.group,
                    "scene": source.scene,
                    "frames": source.frames,
                    "start_ratio": source.start_ratio,
                    "end_ratio": source.end_ratio,
                    "source_dataset": source.source_dataset,
                    "license": source.license,
                    "exists": exists,
                    "note": source.note,
                }
            )


def write_frame_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "annotation_status",
        "group",
        "scene",
        "image",
        "image_path",
        "license",
        "source_dataset",
        "source_frame_index",
        "source_video",
        "start_ratio",
        "end_ratio",
        "timestamp_ms",
        "video_id",
        "note",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_labeling_guide(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# YOLO person batch labeling guide",
                "",
                "Class list:",
                "",
                "- 0 person",
                "",
                "Rules:",
                "",
                "- Label every visible human as class 0 person.",
                "- Standing, walking, sitting, bending, kneeling, lying, falling, and fallen people are all person.",
                "- Do not label action classes such as falling, fallen, sitting, kneeling, or bending.",
                "- Draw one bbox per visible person.",
                "- For no-person frames, leave the label file empty and save.",
                "- Prefer a tight visible-body box; include visible limbs and torso, but do not guess fully hidden parts.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_data_yaml(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                f"path: {FINAL_ROOT.as_posix()}",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                "names:",
                "  0: person",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_summary(
    path: Path,
    sources: list[SourceVideo],
    missing: list[SourceVideo],
    rows: list[dict[str, object]],
) -> None:
    groups: dict[str, int] = {}
    for row in rows:
        group = str(row["group"])
        groups[group] = groups.get(group, 0) + 1
    payload = {
        "batch_id": path.parents[1].name,
        "source_video_count": len(sources),
        "missing_source_video_count": len(missing),
        "image_count": len(rows),
        "groups": dict(sorted(groups.items())),
        "classes": ["person"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
