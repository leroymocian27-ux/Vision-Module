from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"
FINAL_ROOT = ROOT / "datasets" / "fall_hint_v2"

CLASS_NAMES = [
    "falling",
    "fallen",
    "lying",
    "sitting",
    "bending",
    "kneeling",
    "standing",
]

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


@dataclass(frozen=True)
class SourceVideo:
    video_id: str
    source_path: Path
    group: str
    scene: str
    target_fps: float
    source_dataset: str
    license: str
    note: str
    start_ratio: float = 0.0
    end_ratio: float = 1.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a small human-review batch for the fall_hint_v2 YOLO dataset."
    )
    parser.add_argument("--batch-id", default="batch_001")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--max-frames-per-video", type=int, default=12)
    args = parser.parse_args()

    batch_dir = RAW_ROOT / args.batch_id
    if batch_dir.exists() and args.overwrite:
        shutil.rmtree(batch_dir)
    batch_dir.mkdir(parents=True, exist_ok=True)

    create_structure(batch_dir)
    write_data_yaml(FINAL_ROOT / "data.yaml")

    sources = build_batch_sources(args.batch_id)
    write_source_videos(batch_dir / "meta" / "source_videos.csv", sources)
    frame_rows = extract_frames(
        sources=sources,
        frame_dir=batch_dir / "frames",
        max_frames_per_video=args.max_frames_per_video,
    )
    write_frame_manifest(batch_dir / "meta" / "frame_manifest.csv", frame_rows)
    write_labeling_guide(batch_dir / "meta" / "labeling_guide.md")
    write_summary(batch_dir / "meta" / "prepare_summary.json", sources, frame_rows)

    print(f"[OK] batch_dir={batch_dir}")
    print(f"[OK] source_videos={len(sources)}")
    print(f"[OK] extracted_frames={len(frame_rows)}")
    print(f"[NEXT] Run prelabel step, then import frames into Label Studio/CVAT for human review.")
    return 0


def create_structure(batch_dir: Path) -> None:
    for path in [
        RAW_ROOT / "videos" / "fall",
        RAW_ROOT / "videos" / "adl",
        RAW_ROOT / "videos" / "lying",
        RAW_ROOT / "videos" / "hardneg",
        RAW_ROOT / "videos" / "no_person",
        RAW_ROOT / "meta",
        batch_dir / "frames",
        batch_dir / "prelabels",
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


def build_batch_sources(batch_id: str) -> list[SourceVideo]:
    if batch_id == "batch_002":
        candidates = batch_002_sources()
    elif batch_id == "batch_003":
        candidates = batch_003_sources()
    elif batch_id == "batch_004":
        candidates = batch_004_sources()
    elif batch_id == "batch_005":
        candidates = batch_005_sources()
    elif batch_id == "batch_006":
        candidates = batch_006_sources()
    elif batch_id == "batch_007":
        candidates = batch_007_sources()
    elif batch_id == "batch_008":
        candidates = batch_008_sources()
    elif batch_id == "batch_009":
        candidates = batch_009_sources()
    elif batch_id == "batch_010":
        candidates = batch_010_sources()
    elif batch_id == "batch_011":
        candidates = batch_011_sources()
    elif batch_id == "batch_012":
        candidates = batch_012_sources()
    elif batch_id == "batch_013":
        candidates = batch_013_sources()
    else:
        candidates = batch_001_sources()
    return [item for item in candidates if item.source_path.exists()]


def batch_001_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "local_no_person_retake_b",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151001_no_person_retake_b/video.mp4",
            "no_person",
            "no_person",
            1.0,
            "new_pose_raw",
            "local_project_data",
            "empty room / no person hard negative",
        ),
        SourceVideo(
            "local_standing_front",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160200_standing_front/video.mp4",
            "adl",
            "standing",
            2.0,
            "new_pose_raw",
            "local_project_data",
            "standing normal",
        ),
        SourceVideo(
            "local_sitting_normal",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160600_sitting_normal/video.mp4",
            "adl",
            "sitting",
            2.0,
            "new_pose_raw",
            "local_project_data",
            "sitting normal",
        ),
        SourceVideo(
            "local_bending_pickup",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160800_bending_pickup/video.mp4",
            "hardneg",
            "bending",
            3.0,
            "new_pose_raw",
            "local_project_data",
            "bending/pickup hard negative",
        ),
        SourceVideo(
            "local_squat",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160900_squat/video.mp4",
            "hardneg",
            "kneeling",
            3.0,
            "new_pose_raw",
            "local_project_data",
            "squat/kneeling hard negative",
        ),
        SourceVideo(
            "local_lying_side",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161000_lying_side/video.mp4",
            "lying",
            "lying",
            2.0,
            "new_pose_raw",
            "local_project_data",
            "normal lying side",
        ),
        SourceVideo(
            "local_fall_simulated_side",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161300_fall_simulated_side/video.mp4",
            "fall",
            "fall",
            5.0,
            "new_pose_raw",
            "local_project_data",
            "simulated fall side",
        ),
        SourceVideo(
            "local_fallen_hold",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161500_fallen_hold/video.mp4",
            "fall",
            "fallen_hold",
            3.0,
            "new_pose_raw",
            "local_project_data",
            "fallen hold",
        ),
        SourceVideo(
            "ur_fall_fall_01",
            ROOT / "datasets/ur_fall/videos/fall-01.mp4",
            "fall",
            "fall",
            5.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "public fall sample for human review",
        ),
        SourceVideo(
            "ur_fall_adl_07_sitting",
            ROOT / "datasets/ur_fall/videos/adl-07.mp4",
            "adl",
            "sitting",
            2.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "public sitting ADL sample for human review",
        ),
    ]


def batch_002_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "local_no_person_room",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160100_no_person/video.mp4",
            "no_person",
            "no_person",
            1.0,
            "new_pose_raw",
            "local_project_data",
            "empty room / no person",
        ),
        SourceVideo(
            "local_walking_slow",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160500_walking_slow/video.mp4",
            "adl",
            "standing",
            2.0,
            "new_pose_raw",
            "local_project_data",
            "walking slow",
        ),
        SourceVideo(
            "local_sitting_side",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160700_sitting_side/video.mp4",
            "adl",
            "sitting",
            2.0,
            "new_pose_raw",
            "local_project_data",
            "sitting side",
        ),
        SourceVideo(
            "local_lying_back",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161100_lying_back/video.mp4",
            "lying",
            "lying",
            2.0,
            "new_pose_raw",
            "local_project_data",
            "normal lying back",
        ),
        SourceVideo(
            "local_lying_prone",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161200_lying_prone/video.mp4",
            "lying",
            "lying",
            2.0,
            "new_pose_raw",
            "local_project_data",
            "normal lying prone",
        ),
        SourceVideo(
            "local_fall_simulated_back",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161400_fall_simulated_back/video.mp4",
            "fall",
            "fall",
            5.0,
            "new_pose_raw",
            "local_project_data",
            "simulated fall back",
        ),
        SourceVideo(
            "local_recovery_standing",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161600_recovery_standing/video.mp4",
            "adl",
            "standing",
            2.0,
            "new_pose_raw",
            "local_project_data",
            "recovery to standing",
        ),
        SourceVideo(
            "ur_fall_fall_02",
            ROOT / "datasets/ur_fall/videos/fall-02.mp4",
            "fall",
            "fall",
            5.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "public fall sample for human review",
        ),
        SourceVideo(
            "ur_fall_adl_10_lying",
            ROOT / "datasets/ur_fall/videos/adl-10.mp4",
            "lying",
            "lying",
            2.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "public normal lying sample for human review",
        ),
        SourceVideo(
            "ur_fall_adl_15_bending",
            ROOT / "datasets/ur_fall/videos/adl-15.mp4",
            "hardneg",
            "bending",
            3.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "public bending ADL sample for human review",
        ),
    ]


def batch_003_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "local_squat_retake_b",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151301_squat_retake_b/video.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "squat/kneeling retake",
        ),
        SourceVideo(
            "local_lying_back_retake_b",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151401_lying_back_retake_b/video.mp4",
            "lying",
            "lying",
            3.0,
            "new_pose_raw",
            "local_project_data",
            "normal lying back retake",
        ),
        SourceVideo(
            "local_fall_simulated_back_retake_b",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151501_fall_simulated_back_retake_b/video.mp4",
            "fall",
            "fall",
            6.0,
            "new_pose_raw",
            "local_project_data",
            "simulated fall back retake",
        ),
        SourceVideo(
            "ur_fall_adl_04_bending",
            ROOT / "datasets/ur_fall/videos/adl-04.mp4",
            "hardneg",
            "bending",
            4.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "public bend/pickup hard negative",
        ),
        SourceVideo(
            "ur_fall_adl_12_squat",
            ROOT / "datasets/ur_fall/videos/adl-12.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "public squat/kneel hard negative",
        ),
        SourceVideo(
            "ur_fall_adl_19_lying",
            ROOT / "datasets/ur_fall/videos/adl-19.mp4",
            "lying",
            "lying",
            3.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "public normal recline/lying sample",
        ),
        SourceVideo(
            "ur_fall_fall_03",
            ROOT / "datasets/ur_fall/videos/fall-03.mp4",
            "fall",
            "fall",
            6.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "public fall sample for human review",
        ),
        SourceVideo(
            "gmdcsa_actor1_fall_03",
            ROOT / "datasets/gmdcsa24/videos/actor_1_fall_03.mp4",
            "fall",
            "fall",
            6.0,
            "gmdcsa24",
            "CC BY 4.0",
            "GMDCSA fall sample for human review",
        ),
        SourceVideo(
            "gmdcsa_actor1_adl_11",
            ROOT / "datasets/gmdcsa24/videos/actor_1_adl_11.mp4",
            "hardneg",
            "bending",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "GMDCSA ADL hard-negative sample",
        ),
        SourceVideo(
            "gmdcsa_actor2_adl_24",
            ROOT / "datasets/gmdcsa24/videos/actor_2_adl_24.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "GMDCSA low-posture ADL sample",
        ),
    ]


def batch_004_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "local_lying_back_late",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161100_lying_back/video.mp4",
            "lying",
            "lying",
            3.0,
            "new_pose_raw",
            "local_project_data",
            "normal lying back later segment",
            0.35,
            1.0,
        ),
        SourceVideo(
            "local_lying_prone_late",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161200_lying_prone/video.mp4",
            "lying",
            "lying",
            3.0,
            "new_pose_raw",
            "local_project_data",
            "normal lying prone later segment",
            0.35,
            1.0,
        ),
        SourceVideo(
            "local_fallen_hold_late",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161500_fallen_hold/video.mp4",
            "fall",
            "fallen_hold",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "fallen hold later segment",
            0.10,
            1.0,
        ),
        SourceVideo(
            "local_fall_side_midlate",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161300_fall_simulated_side/video.mp4",
            "fall",
            "fall",
            6.0,
            "new_pose_raw",
            "local_project_data",
            "fall side mid/late segment",
            0.20,
            0.90,
        ),
        SourceVideo(
            "local_fall_back_midlate",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161400_fall_simulated_back/video.mp4",
            "fall",
            "fall",
            6.0,
            "new_pose_raw",
            "local_project_data",
            "fall back mid/late segment",
            0.20,
            0.90,
        ),
        SourceVideo(
            "ur_fall_adl_10_lying_late",
            ROOT / "datasets/ur_fall/videos/adl-10.mp4",
            "lying",
            "lying",
            3.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR normal lying later segment",
            0.45,
            0.95,
        ),
        SourceVideo(
            "ur_fall_adl_11_lying_late",
            ROOT / "datasets/ur_fall/videos/adl-11.mp4",
            "lying",
            "lying",
            3.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR normal lying later segment",
            0.45,
            0.95,
        ),
        SourceVideo(
            "ur_fall_adl_12_squat_mid",
            ROOT / "datasets/ur_fall/videos/adl-12.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR squat/kneel middle segment",
            0.20,
            0.75,
        ),
        SourceVideo(
            "ur_fall_fall_01_midlate",
            ROOT / "datasets/ur_fall/videos/fall-01.mp4",
            "fall",
            "fall",
            6.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR fall mid/late segment",
            0.25,
            0.95,
        ),
        SourceVideo(
            "ur_fall_fall_02_midlate",
            ROOT / "datasets/ur_fall/videos/fall-02.mp4",
            "fall",
            "fall",
            6.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR fall mid/late segment",
            0.25,
            0.95,
        ),
    ]


def batch_005_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "local_squat_retake_b_midlate",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151301_squat_retake_b/video.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "squat/kneeling retake middle/later segment",
            0.15,
            0.95,
        ),
        SourceVideo(
            "local_squat_midlate",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160900_squat/video.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "squat/kneeling middle/later segment",
            0.15,
            0.95,
        ),
        SourceVideo(
            "local_lying_side_late_b005",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161000_lying_side/video.mp4",
            "lying",
            "lying",
            3.0,
            "new_pose_raw",
            "local_project_data",
            "normal lying side later segment",
            0.35,
            1.0,
        ),
        SourceVideo(
            "local_lying_back_retake_b_late",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151401_lying_back_retake_b/video.mp4",
            "lying",
            "lying",
            3.0,
            "new_pose_raw",
            "local_project_data",
            "normal lying back retake later segment",
            0.35,
            1.0,
        ),
        SourceVideo(
            "local_fallen_hold_full_b005",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161500_fallen_hold/video.mp4",
            "fall",
            "fallen_hold",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "fallen hold full segment",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_fall_back_retake_b_midlate",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151501_fall_simulated_back_retake_b/video.mp4",
            "fall",
            "fall",
            6.0,
            "new_pose_raw",
            "local_project_data",
            "simulated fall back retake middle/later segment",
            0.18,
            0.95,
        ),
        SourceVideo(
            "ur_fall_adl_12_squat_late_b005",
            ROOT / "datasets/ur_fall/videos/adl-12.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR squat/kneel later segment",
            0.30,
            0.90,
        ),
        SourceVideo(
            "ur_fall_adl_19_lying_late_b005",
            ROOT / "datasets/ur_fall/videos/adl-19.mp4",
            "lying",
            "lying",
            3.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR normal lying later segment",
            0.40,
            0.95,
        ),
        SourceVideo(
            "ur_fall_fall_04_midlate",
            ROOT / "datasets/ur_fall/videos/fall-04.mp4",
            "fall",
            "fall",
            6.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR fall middle/later segment",
            0.22,
            0.95,
        ),
        SourceVideo(
            "ur_fall_fall_05_midlate",
            ROOT / "datasets/ur_fall/videos/fall-05.mp4",
            "fall",
            "fall",
            6.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR fall middle/later segment",
            0.22,
            0.95,
        ),
    ]


def batch_006_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "local_lying_back_late_b006",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161100_lying_back/video.mp4",
            "lying",
            "lying",
            3.0,
            "new_pose_raw",
            "local_project_data",
            "normal lying back later segment; label as lying if no fall impact is visible",
            0.45,
            1.0,
        ),
        SourceVideo(
            "local_lying_prone_late_b006",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161200_lying_prone/video.mp4",
            "lying",
            "lying",
            3.0,
            "new_pose_raw",
            "local_project_data",
            "normal prone lying later segment; label as lying if no fall impact is visible",
            0.45,
            1.0,
        ),
        SourceVideo(
            "local_lying_side_late_b006",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161000_lying_side/video.mp4",
            "lying",
            "lying",
            3.0,
            "new_pose_raw",
            "local_project_data",
            "normal side lying later segment; label as lying if no fall impact is visible",
            0.45,
            1.0,
        ),
        SourceVideo(
            "ur_fall_adl_10_lying_tail_b006",
            ROOT / "datasets/ur_fall/videos/adl-10.mp4",
            "lying",
            "lying",
            3.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR normal lying tail segment; hard negative against fallen",
            0.55,
            0.98,
        ),
        SourceVideo(
            "local_squat_mid_b006",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160900_squat/video.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "squat/kneeling middle segment; label low non-fall posture as kneeling",
            0.25,
            0.90,
        ),
        SourceVideo(
            "local_squat_retake_b_mid_b006",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151301_squat_retake_b/video.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "squat/kneeling retake middle segment; label low non-fall posture as kneeling",
            0.25,
            0.90,
        ),
        SourceVideo(
            "ur_fall_adl_12_squat_mid_b006",
            ROOT / "datasets/ur_fall/videos/adl-12.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR squat/kneel middle segment",
            0.25,
            0.85,
        ),
        SourceVideo(
            "local_fall_side_transition_b006",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161300_fall_simulated_side/video.mp4",
            "fall",
            "fall",
            6.0,
            "new_pose_raw",
            "local_project_data",
            "fall side transition; label active descent as falling and final abnormal down posture as fallen",
            0.10,
            0.80,
        ),
        SourceVideo(
            "ur_fall_fall_06_mid_b006",
            ROOT / "datasets/ur_fall/videos/fall-06.mp4",
            "fall",
            "fall",
            6.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR fall middle segment",
            0.15,
            0.90,
        ),
        SourceVideo(
            "ur_fall_fall_07_mid_b006",
            ROOT / "datasets/ur_fall/videos/fall-07.mp4",
            "fall",
            "fall",
            6.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR fall middle segment",
            0.15,
            0.90,
        ),
    ]


def batch_007_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "desktop_fall_574c_midlate_b007",
            Path(r"C:/Users/YANG/Desktop/574c42749fa162a487f7e3d3e84bb181_raw.mp4"),
            "fall",
            "fall",
            6.0,
            "user_desktop",
            "local_project_data",
            "user-provided fall candidate; label active descent as falling and abnormal down posture as fallen",
            0.10,
            0.95,
        ),
        SourceVideo(
            "desktop_fall_a64f_window_b007",
            Path(r"C:/Users/YANG/Desktop/a64f9bce58dfda706d4ba830a7749ae2.mp4"),
            "fall",
            "fall",
            4.0,
            "user_desktop",
            "local_project_data",
            "user-provided long fall candidate; use source hint but final label by image",
            0.35,
            0.70,
        ),
        SourceVideo(
            "desktop_fall_ec4c_window_b007",
            Path(r"C:/Users/YANG/Desktop/ec4c9594a3fee498abcee80566372029.mp4"),
            "fall",
            "fall",
            4.0,
            "user_desktop",
            "local_project_data",
            "user-provided long fall candidate; use source hint but final label by image",
            0.35,
            0.70,
        ),
        SourceVideo(
            "desktop_fall_20ea_midlate_b007",
            Path(r"C:/Users/YANG/Desktop/20eab7404c5cac9c3038a059cf6d0bbc.mp4"),
            "fall",
            "fall",
            6.0,
            "user_desktop",
            "local_project_data",
            "user-provided fall candidate; label active descent as falling and abnormal down posture as fallen",
            0.10,
            0.95,
        ),
        SourceVideo(
            "gmd_actor1_adl01_lying_b007",
            ROOT / "datasets/gmdcsa24/videos/actor_1_adl_01.mp4",
            "lying",
            "lying",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "bed sitting-to-sleeping right side; normal lying hard negative",
            0.45,
            0.98,
        ),
        SourceVideo(
            "gmd_actor2_adl02_lying_b007",
            ROOT / "datasets/gmdcsa24/videos/actor_2_adl_02.mp4",
            "lying",
            "lying",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "bed sitting-to-sleeping left side; normal lying hard negative",
            0.45,
            0.98,
        ),
        SourceVideo(
            "gmd_actor3_adl03_lying_b007",
            ROOT / "datasets/gmdcsa24/videos/actor_3_adl_03.mp4",
            "lying",
            "lying",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "bed sleeping left side/ceiling; normal lying hard negative",
            0.45,
            0.98,
        ),
        SourceVideo(
            "gmd_actor2_fall05_b007",
            ROOT / "datasets/gmdcsa24/videos/actor_2_fall_05.mp4",
            "fall",
            "fall",
            6.0,
            "gmdcsa24",
            "CC BY 4.0",
            "walking to falling; right side fall",
            0.15,
            0.95,
        ),
        SourceVideo(
            "gmd_actor3_fall09_b007",
            ROOT / "datasets/gmdcsa24/videos/actor_3_fall_09.mp4",
            "fall",
            "fall",
            6.0,
            "gmdcsa24",
            "CC BY 4.0",
            "standing to forward fall",
            0.15,
            0.95,
        ),
        SourceVideo(
            "mcfd_chute05_cam1_b007",
            ROOT / "datasets/fall_clean_v1/raw_public_supplement_manual/mcfd/dataset/dataset/chute05/cam1.avi",
            "fall",
            "fall",
            5.0,
            "mcfd",
            "public_dataset_manual_review",
            "MCFD fall chute cam1; multi-view diversity",
            0.20,
            0.95,
        ),
    ]


def batch_008_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "local_squat_mid_b008",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160900_squat/video.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "squat/kneeling middle segment; label low non-fall posture as kneeling",
            0.20,
            0.92,
        ),
        SourceVideo(
            "local_squat_retake_b_mid_b008",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151301_squat_retake_b/video.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "squat/kneeling retake; label low non-fall posture as kneeling",
            0.18,
            0.95,
        ),
        SourceVideo(
            "gmd_actor2_adl09_crouch_b008",
            ROOT / "datasets/gmdcsa24/videos/actor_2_adl_09.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "GMDCSA crouch hard negative; label crouch/low posture as kneeling",
            0.15,
            0.90,
        ),
        SourceVideo(
            "gmd_actor2_adl19_crouch_b008",
            ROOT / "datasets/gmdcsa24/videos/actor_2_adl_19.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "GMDCSA crouch hard negative; label crouch/low posture as kneeling",
            0.15,
            0.90,
        ),
        SourceVideo(
            "ur_fall_adl12_crouch_b008",
            ROOT / "datasets/ur_fall/videos/adl-12.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR squat/kneel hard negative",
            0.18,
            0.88,
        ),
        SourceVideo(
            "gmd_actor1_fall05_transition_b008",
            ROOT / "datasets/gmdcsa24/videos/actor_1_fall_05.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "walking to falling; focus active descent frames as falling",
            0.25,
            0.85,
        ),
        SourceVideo(
            "gmd_actor1_fall08_transition_b008",
            ROOT / "datasets/gmdcsa24/videos/actor_1_fall_08.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "walking to falling; focus active descent frames as falling",
            0.25,
            0.85,
        ),
        SourceVideo(
            "gmd_actor2_fall07_transition_b008",
            ROOT / "datasets/gmdcsa24/videos/actor_2_fall_07.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "fall after picking bottle; distinguish bending/kneeling from active fall",
            0.20,
            0.88,
        ),
        SourceVideo(
            "ur_fall_fall08_transition_b008",
            ROOT / "datasets/ur_fall/videos/fall-08.mp4",
            "fall",
            "fall",
            8.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR fall transition; label active descent as falling and final posture as fallen",
            0.12,
            0.82,
        ),
        SourceVideo(
            "gmd_actor2_adl01_lying_b008",
            ROOT / "datasets/gmdcsa24/videos/actor_2_adl_01.mp4",
            "lying",
            "lying",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "normal lie-down hard negative; label normal bed/ground lying as lying",
            0.45,
            0.98,
        ),
    ]


def batch_009_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "gmd_actor1_adl02_lying_tail_b009",
            ROOT / "datasets/gmdcsa24/videos/actor_1_adl_02.mp4",
            "lying",
            "lying",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "normal sleeping left side on bed; label as lying",
            0.50,
            0.98,
        ),
        SourceVideo(
            "gmd_actor1_adl03_lying_tail_b009",
            ROOT / "datasets/gmdcsa24/videos/actor_1_adl_03.mp4",
            "lying",
            "lying",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "normal sleeping left side/ceiling on bed; label as lying",
            0.45,
            0.98,
        ),
        SourceVideo(
            "gmd_actor2_adl03_lying_tail_b009",
            ROOT / "datasets/gmdcsa24/videos/actor_2_adl_03.mp4",
            "lying",
            "lying",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "walking/removing dust then sleeping on bed; tail segment should be normal lying",
            0.65,
            0.98,
        ),
        SourceVideo(
            "gmd_actor2_adl12_lying_tail_b009",
            ROOT / "datasets/gmdcsa24/videos/actor_2_adl_12.mp4",
            "lying",
            "lying",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "going to bed and sleeping prone; label as lying",
            0.50,
            0.98,
        ),
        SourceVideo(
            "gmd_actor2_adl16_lying_tail_b009",
            ROOT / "datasets/gmdcsa24/videos/actor_2_adl_16.mp4",
            "lying",
            "lying",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "half-sleeping/lying on bed; label as lying if no fall impact",
            0.40,
            0.90,
        ),
        SourceVideo(
            "gmd_actor2_adl23_lying_tail_b009",
            ROOT / "datasets/gmdcsa24/videos/actor_2_adl_23.mp4",
            "lying",
            "lying",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "sitting to sleeping on ground; tail segment should be normal lying",
            0.50,
            0.98,
        ),
        SourceVideo(
            "gmd_actor3_adl08_lying_tail_b009",
            ROOT / "datasets/gmdcsa24/videos/actor_3_adl_08.mp4",
            "lying",
            "lying",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "sitting to sleeping on floor; tail segment should be normal lying",
            0.45,
            0.98,
        ),
        SourceVideo(
            "gmd_actor3_fall01_transition_b009",
            ROOT / "datasets/gmdcsa24/videos/actor_3_fall_01.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "falling forward; focus active descent as falling",
            0.10,
            0.85,
        ),
        SourceVideo(
            "gmd_actor3_fall05_transition_b009",
            ROOT / "datasets/gmdcsa24/videos/actor_3_fall_05.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "slow fall from standing to floor; label transition as falling",
            0.20,
            0.82,
        ),
        SourceVideo(
            "gmd_actor3_fall16_transition_b009",
            ROOT / "datasets/gmdcsa24/videos/actor_3_fall_16.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "walking then falling left side; label active descent as falling",
            0.15,
            0.85,
        ),
    ]


def batch_010_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "gmd_actor2_fall02_transition_b010",
            ROOT / "datasets/gmdcsa24/videos/actor_2_fall_02.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "right side fall after walking; label active descent as falling",
            0.18,
            0.78,
        ),
        SourceVideo(
            "gmd_actor2_fall06_transition_b010",
            ROOT / "datasets/gmdcsa24/videos/actor_2_fall_06.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "walking while using phone then fall backward; label active descent as falling",
            0.18,
            0.82,
        ),
        SourceVideo(
            "gmd_actor2_fall09_transition_b010",
            ROOT / "datasets/gmdcsa24/videos/actor_2_fall_09.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "falling backward after walking; focus transition frames",
            0.18,
            0.82,
        ),
        SourceVideo(
            "gmd_actor2_fall12_transition_b010",
            ROOT / "datasets/gmdcsa24/videos/actor_2_fall_12.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "drinking water then falling backward; focus transition frames",
            0.18,
            0.82,
        ),
        SourceVideo(
            "gmd_actor3_fall07_transition_b010",
            ROOT / "datasets/gmdcsa24/videos/actor_3_fall_07.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "falling on floor from standing; focus active descent as falling",
            0.18,
            0.82,
        ),
        SourceVideo(
            "gmd_actor3_fall08_transition_b010",
            ROOT / "datasets/gmdcsa24/videos/actor_3_fall_08.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "right-side fall from standing; focus active descent as falling",
            0.18,
            0.82,
        ),
        SourceVideo(
            "gmd_actor3_fall20_transition_b010",
            ROOT / "datasets/gmdcsa24/videos/actor_3_fall_20.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "walking then falling forward; focus active descent as falling",
            0.16,
            0.82,
        ),
        SourceVideo(
            "local_squat_mid_b010",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160900_squat/video.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "local squat/low posture; label as kneeling only when clearly crouched or kneeling",
            0.25,
            0.88,
        ),
        SourceVideo(
            "local_squat_retake_b_mid_b010",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151301_squat_retake_b/video.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "local squat retake; label as kneeling only when clearly crouched or kneeling",
            0.25,
            0.88,
        ),
        SourceVideo(
            "ur_fall_adl12_crouch_b010",
            ROOT / "datasets/ur_fall/videos/adl-12.mp4",
            "hardneg",
            "kneeling",
            4.0,
            "ur_fall",
            "CC BY-NC-SA 4.0",
            "UR squat/kneel hard negative; use image evidence over source hint",
            0.20,
            0.80,
        ),
    ]


def batch_011_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "gmd_actor1_fall01_transition_b011",
            ROOT / "datasets/gmdcsa24/videos/actor_1_fall_01.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "chair-to-ground fall; label active descent as falling",
            0.15,
            0.80,
        ),
        SourceVideo(
            "gmd_actor1_fall02_transition_b011",
            ROOT / "datasets/gmdcsa24/videos/actor_1_fall_02.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "chair-to-ground fall; label active descent as falling",
            0.15,
            0.80,
        ),
        SourceVideo(
            "gmd_actor1_fall03_transition_b011",
            ROOT / "datasets/gmdcsa24/videos/actor_1_fall_03.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "chair-to-ground side fall; label active descent as falling",
            0.15,
            0.82,
        ),
        SourceVideo(
            "gmd_actor2_fall10_transition_b011",
            ROOT / "datasets/gmdcsa24/videos/actor_2_fall_10.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "right-side then backward fall; label active descent as falling",
            0.15,
            0.82,
        ),
        SourceVideo(
            "gmd_actor2_fall11_transition_b011",
            ROOT / "datasets/gmdcsa24/videos/actor_2_fall_11.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "falling from bed to ground; label active descent as falling",
            0.15,
            0.82,
        ),
        SourceVideo(
            "gmd_actor2_fall13_transition_b011",
            ROOT / "datasets/gmdcsa24/videos/actor_2_fall_13.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "backward fall side view; label active descent as falling",
            0.15,
            0.82,
        ),
        SourceVideo(
            "gmd_actor3_fall15_transition_b011",
            ROOT / "datasets/gmdcsa24/videos/actor_3_fall_15.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "drink water then fall; label active descent as falling",
            0.15,
            0.82,
        ),
        SourceVideo(
            "gmd_actor3_fall18_transition_b011",
            ROOT / "datasets/gmdcsa24/videos/actor_3_fall_18.mp4",
            "fall",
            "fall",
            8.0,
            "gmdcsa24",
            "CC BY 4.0",
            "sitting on bed then falling to floor; label active descent as falling",
            0.15,
            0.82,
        ),
        SourceVideo(
            "gmd_actor1_adl15_bending_b011",
            ROOT / "datasets/gmdcsa24/videos/actor_1_adl_15.mp4",
            "hardneg",
            "bending",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "walking to picking object; bending hard negative",
            0.25,
            0.85,
        ),
        SourceVideo(
            "gmd_actor2_adl04_bending_b011",
            ROOT / "datasets/gmdcsa24/videos/actor_2_adl_04.mp4",
            "hardneg",
            "bending",
            4.0,
            "gmdcsa24",
            "CC BY 4.0",
            "exercise bending body; bending hard negative",
            0.15,
            0.90,
        ),
    ]


def batch_012_sources() -> list[SourceVideo]:
    return [
        SourceVideo(
            "local_target_kneeling_front_b012",
            Path(r"C:\Users\YANG\Desktop\46c44a059808aad3a22e666ae6a6597a.mp4"),
            "hardneg",
            "kneeling",
            12.0,
            "local_targeted_recording",
            "local_project_data",
            "targeted kneeling/low-posture hard negative; label visible posture from image evidence",
        ),
        SourceVideo(
            "local_target_kneeling_side_b012",
            Path(r"C:\Users\YANG\Desktop\398f048bebe7b52e92a64a5778233c3f.mp4"),
            "hardneg",
            "kneeling",
            12.0,
            "local_targeted_recording",
            "local_project_data",
            "targeted side-view kneeling/low-posture hard negative",
        ),
        SourceVideo(
            "local_target_kneeling_back_b012",
            Path(r"C:\Users\YANG\Desktop\a8f91f5ad1a879903e20a1d92610d782.mp4"),
            "hardneg",
            "kneeling",
            12.0,
            "local_targeted_recording",
            "local_project_data",
            "targeted back-view kneeling/low-posture hard negative",
        ),
        SourceVideo(
            "local_target_kneeling_side_hold_b012",
            Path(r"C:\Users\YANG\Desktop\b076a6ed63dc6707de17c72d38e825be.mp4"),
            "hardneg",
            "kneeling",
            12.0,
            "local_targeted_recording",
            "local_project_data",
            "targeted kneeling transition and hold hard negative",
        ),
    ]


def batch_013_sources() -> list[SourceVideo]:
    """Hard-negative/positive review batch for LSTM and fusion false-positive control.

    The labels are still fall_hint_v2 frame labels, but the source video and
    timestamp metadata are preserved so the reviewed frames can be traced back
    into temporal hard-negative and hard-positive sequences.
    """

    return [
        SourceVideo(
            "local_sitting_normal_retake_b_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151101_sitting_normal_retake_b/video.mp4",
            "hardneg",
            "sitting",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "local sitting still hard negative; label seated person as sitting, not fallen",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_sitting_side_retake_b_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151201_sitting_side_retake_b/video.mp4",
            "hardneg",
            "sitting",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "local side sitting hard negative; label seated person as sitting",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_sitting_normal_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160600_sitting_normal/video.mp4",
            "hardneg",
            "sitting",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "local sitting normal hard negative",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_sitting_side_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160700_sitting_side/video.mp4",
            "hardneg",
            "sitting",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "local side sitting hard negative",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_bending_pickup_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160800_bending_pickup/video.mp4",
            "hardneg",
            "bending",
            5.0,
            "new_pose_raw",
            "local_project_data",
            "local bending/pickup hard negative; label bent standing posture as bending",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_squat_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160900_squat/video.mp4",
            "hardneg",
            "kneeling",
            5.0,
            "new_pose_raw",
            "local_project_data",
            "local squat/kneeling hard negative; label low controlled posture as kneeling",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_squat_retake_b_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151301_squat_retake_b/video.mp4",
            "hardneg",
            "kneeling",
            5.0,
            "new_pose_raw",
            "local_project_data",
            "local squat/kneeling retake hard negative",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_lying_side_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161000_lying_side/video.mp4",
            "lying",
            "lying",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "normal side lying hard negative; label as lying if no fall impact is visible",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_lying_back_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161100_lying_back/video.mp4",
            "lying",
            "lying",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "normal back lying hard negative; label as lying if no fall impact is visible",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_lying_prone_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161200_lying_prone/video.mp4",
            "lying",
            "lying",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "normal prone lying hard negative; label as lying if no fall impact is visible",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_fall_simulated_side_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161300_fall_simulated_side/video.mp4",
            "fall",
            "fall",
            6.0,
            "new_pose_raw",
            "local_project_data",
            "simulated fall side; label descent as falling and abnormal down result as fallen",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_fall_simulated_back_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161400_fall_simulated_back/video.mp4",
            "fall",
            "fall",
            6.0,
            "new_pose_raw",
            "local_project_data",
            "simulated fall back; label descent as falling and abnormal down result as fallen",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_fall_simulated_back_retake_b_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_151501_fall_simulated_back_retake_b/video.mp4",
            "fall",
            "fall",
            6.0,
            "new_pose_raw",
            "local_project_data",
            "simulated fall retake; label descent as falling and abnormal down result as fallen",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_fallen_hold_full_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_161500_fallen_hold/video.mp4",
            "fall",
            "fallen_hold",
            4.0,
            "new_pose_raw",
            "local_project_data",
            "abnormal down hold after fall; label as fallen if it is a fall result",
            0.0,
            1.0,
        ),
        SourceVideo(
            "local_no_person_room_b013",
            ROOT / "datasets/new_pose_raw/camera_01/session_20260621_160100_no_person/video.mp4",
            "no_person",
            "no_person",
            2.0,
            "new_pose_raw",
            "local_project_data",
            "empty room hard negative; keep labels empty",
            0.0,
            1.0,
        ),
    ]


def extract_frames(
    *,
    sources: list[SourceVideo],
    frame_dir: Path,
    max_frames_per_video: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in sources:
        cap = cv2.VideoCapture(str(source.source_path))
        if not cap.isOpened():
            print(f"[SKIP] could not open {source.source_path}")
            continue

        src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if src_fps <= 0 or total_frames <= 0:
            cap.release()
            print(f"[SKIP] bad video metadata {source.source_path}")
            continue

        start_frame = int(total_frames * max(0.0, min(1.0, source.start_ratio)))
        end_frame = int(total_frames * max(0.0, min(1.0, source.end_ratio)))
        end_frame = max(end_frame, start_frame + 1)
        step = max(int(round(src_fps / max(source.target_fps, 0.1))), 1)
        frame_indices = select_frame_indices(
            start_frame=start_frame,
            end_frame=end_frame,
            step=step,
            max_frames=max_frames_per_video,
        )
        saved = 0
        for frame_index in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok:
                continue
            out_name = f"{source.video_id}_{saved:06d}.jpg"
            out_path = frame_dir / out_name
            cv2.imwrite(str(out_path), frame)
            timestamp_ms = int(round(frame_index * 1000 / src_fps))
            rows.append(
                {
                    "image": out_name,
                    "image_path": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                    "video_id": source.video_id,
                    "source_video": str(source.source_path),
                    "group": source.group,
                    "scene": source.scene,
                    "source_dataset": source.source_dataset,
                    "license": source.license,
                    "source_frame_index": frame_index,
                    "timestamp_ms": timestamp_ms,
                    "target_fps": source.target_fps,
                    "start_ratio": source.start_ratio,
                    "end_ratio": source.end_ratio,
                    "annotation_status": "needs_human_review",
                }
            )
            saved += 1
        cap.release()
        print(f"[OK] {source.video_id}: saved={saved} total_frames={total_frames}")
    return rows


def select_frame_indices(
    *,
    start_frame: int,
    end_frame: int,
    step: int,
    max_frames: int,
) -> list[int]:
    candidates = list(range(start_frame, end_frame, max(step, 1)))
    if not candidates:
        return [start_frame]
    if len(candidates) <= max_frames:
        return candidates
    if max_frames <= 1:
        return [candidates[len(candidates) // 2]]

    last = len(candidates) - 1
    selected: list[int] = []
    for index in range(max_frames):
        selected.append(candidates[round(index * last / (max_frames - 1))])
    return selected


def write_source_videos(path: Path, sources: list[SourceVideo]) -> None:
    rows = [
        {
            "video_id": item.video_id,
            "path": str(item.source_path),
            "group": item.group,
            "scene": item.scene,
            "target_fps": item.target_fps,
            "start_ratio": item.start_ratio,
            "end_ratio": item.end_ratio,
            "source_dataset": item.source_dataset,
            "license": item.license,
            "privacy_ok": "manual_confirm_required",
            "note": item.note,
        }
        for item in sources
    ]
    write_csv(path, rows)


def write_frame_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    write_csv(path, rows)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_data_yaml(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = "\n".join(f"  {index}: {name}" for index, name in enumerate(CLASS_NAMES))
    path.write_text(
        "\n".join(
            [
                f"path: {FINAL_ROOT.as_posix()}",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                "",
                "names:",
                names,
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_labeling_guide(path: Path) -> None:
    path.write_text(
        """# fall_hint_v2 Human Labeling Guide

Labels, in fixed order:

0. falling - active loss of balance or fast descent
1. fallen - abnormal fall result, body down after a fall
2. lying - normal lying/reclining, not necessarily a fall
3. sitting - seated on chair/bed/floor
4. bending - standing legs with upper body bent forward
5. kneeling - squat/kneel/low posture without fall impact
6. standing - standing or walking upright

Rules:

- Draw every visible person in the frame, not only the fallen person.
- Box the full visible body as tightly as practical.
- Keep no-person images with empty labels.
- Treat prelabels as draft only. Correct both class and box.
- Reject frames that are too blurry, too occluded, broken, or impossible to classify.
- Do not mix train/val/test by frame later; split by source video.
""",
        encoding="utf-8",
    )


def write_summary(path: Path, sources: list[SourceVideo], frame_rows: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = {}
    for row in frame_rows:
        counts[str(row["scene"])] = counts.get(str(row["scene"]), 0) + 1
    payload = {
        "class_names": CLASS_NAMES,
        "source_video_count": len(sources),
        "frame_count": len(frame_rows),
        "scene_frame_counts": counts,
        "requires_human_stop": True,
        "next_step": "Run prelabeling, then perform human annotation/review before training.",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
