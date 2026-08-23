from __future__ import annotations

import argparse
import json
import os
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path


ACTION_SPECS = {
    "no_person": {"purpose": "negative empty-scene sample", "duration_sec": 20, "repeats": 3},
    "no_person_retake": {"purpose": "clean empty-scene negative retake", "duration_sec": 15, "repeats": 1},
    "standing_front": {"purpose": "upright baseline front view", "duration_sec": 30, "repeats": 3},
    "standing_side": {"purpose": "upright baseline side view", "duration_sec": 30, "repeats": 3},
    "standing_back": {"purpose": "upright baseline back view", "duration_sec": 30, "repeats": 3},
    "walking_slow": {"purpose": "slow movement baseline", "duration_sec": 30, "repeats": 3},
    "sitting_normal": {"purpose": "sitting false-positive protection", "duration_sec": 30, "repeats": 3},
    "sitting_normal_retake": {"purpose": "clean upright sitting retake", "duration_sec": 15, "repeats": 1},
    "sitting_side": {"purpose": "side sitting coverage", "duration_sec": 30, "repeats": 3},
    "sitting_side_retake": {"purpose": "clean side-sitting retake", "duration_sec": 15, "repeats": 1},
    "bending_pickup": {"purpose": "bending false-positive protection", "duration_sec": 30, "repeats": 3},
    "bending_pickup_retake": {"purpose": "clean bending retake", "duration_sec": 20, "repeats": 1},
    "squat": {"purpose": "low-posture non-fall coverage", "duration_sec": 30, "repeats": 3},
    "squat_retake": {"purpose": "clean squat retake", "duration_sec": 20, "repeats": 1},
    "lying_side": {"purpose": "side-lying static posture", "duration_sec": 30, "repeats": 3},
    "lying_back": {"purpose": "supine static posture", "duration_sec": 30, "repeats": 3},
    "lying_back_retake": {"purpose": "clean supine retake", "duration_sec": 15, "repeats": 1},
    "lying_prone": {"purpose": "prone static posture", "duration_sec": 30, "repeats": 3},
    "lying_prone_retake": {"purpose": "clean prone retake", "duration_sec": 15, "repeats": 1},
    "fall_simulated_side": {"purpose": "controlled side fall simulation", "duration_sec": 20, "repeats": 3},
    "fall_simulated_back": {"purpose": "controlled back fall simulation", "duration_sec": 20, "repeats": 3},
    "fall_simulated_back_retake": {"purpose": "clean controlled back-fall retake", "duration_sec": 30, "repeats": 1},
    "fallen_hold": {"purpose": "fallen hold posture", "duration_sec": 30, "repeats": 3},
    "recovery_standing": {"purpose": "recovery from low posture", "duration_sec": 20, "repeats": 3},
    "recovery_standing_retake": {"purpose": "clean recovery-to-standing retake", "duration_sec": 20, "repeats": 1},
    "partial_occlusion": {"purpose": "occlusion hard case", "duration_sec": 20, "repeats": 3},
    "near_edge": {"purpose": "frame-edge hard case", "duration_sec": 20, "repeats": 3},
    "low_light": {"purpose": "low-light hard case", "duration_sec": 20, "repeats": 2},
    "far_distance": {"purpose": "far-distance hard case", "duration_sec": 20, "repeats": 3},
    "close_distance": {"purpose": "close-distance hard case", "duration_sec": 20, "repeats": 3},
    "loose_clothes": {"purpose": "loose-clothes hard case", "duration_sec": 20, "repeats": 2},
    "dark_clothes": {"purpose": "dark-clothes appearance variation", "duration_sec": 20, "repeats": 2},
    "bright_clothes": {"purpose": "bright-clothes appearance variation", "duration_sec": 20, "repeats": 2},
}

METADATA_TEMPLATE = {
    "schema_version": "new_pose_raw_session_v1",
    "session_id": "",
    "camera_id": "",
    "source_url_masked": "",
    "recorded_at": "",
    "recorded_by": "",
    "runtime_profile": "current_camera_live",
    "pose_provider": "disabled_placeholder",
    "pose_enabled": False,
    "resolution": "",
    "fps": None,
    "duration_sec": None,
    "action_labels": [],
    "primary_action": "",
    "person_count": 1,
    "scene": "indoor",
    "lighting": "normal",
    "camera_view": "",
    "person_clothing": "",
    "has_occlusion": False,
    "has_near_edge": False,
    "safety_notes": "",
    "privacy_notes": "",
    "quality_notes": "",
    "usable_for_training": None,
    "usable_for_eval": None,
    "hard_case": False,
}


def mask_rtsp(url: str) -> str:
    if not url:
        return ""
    return re.sub(r"(rtsp://[^:/?#]+:)([^@/]+)(@)", r"\1***\3", url)


def build_action_script(action: str, session_id: str) -> str:
    spec = ACTION_SPECS[action]
    return "\n".join(
        [
            f"# Action Script: {action}",
            "",
            f"- session_id: `{session_id}`",
            f"- action: `{action}`",
            f"- purpose: `{spec['purpose']}`",
            f"- suggested_duration_sec: `{spec['duration_sec']}`",
            f"- suggested_repeats: `{spec['repeats']}`",
            "- start_cue: fill in on site",
            "- end_cue: fill in on site",
            "- person_position: fill in on site",
            "- safety_notes: fill in on site",
            "- retry_conditions: fill in on site",
            "- remarks: fill in on site",
            "",
            "This file is generated as a collection template only.",
            "It does not enable any real pose runtime.",
        ]
    ) + "\n"


def build_notes_template(action: str) -> str:
    return "\n".join(
        [
            f"# Notes for {action}",
            "",
            "- actual_start_time:",
            "- actual_end_time:",
            "- lighting_notes:",
            "- occlusion_notes:",
            "- edge_notes:",
            "- clothing_notes:",
            "- safety_notes:",
            "- quality_notes:",
            "- retake_required:",
            "- extra_comments:",
            "",
        ]
    )


def build_qa_template(action: str) -> str:
    return "\n".join(
        [
            f"# QA Report for {action}",
            "",
            "- metadata_present: pending",
            "- video_present: pending",
            "- preview_present: pending",
            "- duration_reasonable: pending",
            "- full_body_visible: pending",
            "- action_clear: pending",
            "- privacy_check: pending",
            "- recommended_use: pending",
            "",
        ]
    )


def create_session(args: argparse.Namespace) -> Path:
    timestamp = args.timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"session_{timestamp}_{args.action}"
    if args.session_suffix:
        session_id = f"{session_id}_{args.session_suffix}"
    root = Path(args.root).resolve()
    session_dir = root / args.camera_id / session_id
    session_dir.mkdir(parents=True, exist_ok=False)

    metadata = deepcopy(METADATA_TEMPLATE)
    metadata["session_id"] = session_id
    metadata["camera_id"] = args.camera_id
    metadata["source_url_masked"] = mask_rtsp(args.source_url or os.getenv("DEFAULT_RTSP_URL", ""))
    metadata["recorded_at"] = args.recorded_at or ""
    metadata["recorded_by"] = args.recorded_by or ""
    metadata["runtime_profile"] = args.runtime_profile
    metadata["action_labels"] = [args.action]
    metadata["primary_action"] = args.action
    metadata["person_count"] = 0 if args.action in {"no_person", "no_person_retake"} else 1
    metadata["has_occlusion"] = args.action == "partial_occlusion"
    metadata["has_near_edge"] = args.action == "near_edge"
    metadata["hard_case"] = args.action in {
        "partial_occlusion",
        "near_edge",
        "low_light",
        "far_distance",
        "close_distance",
        "loose_clothes",
        "dark_clothes",
        "bright_clothes",
        "bending_pickup_retake",
        "squat_retake",
        "fall_simulated_back_retake",
        "recovery_standing_retake",
    }
    metadata["safety_notes"] = "Use soft mat and controlled motion for fall simulations." if "fall" in args.action or "lying" in args.action else ""

    (session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (session_dir / "action_script.md").write_text(build_action_script(args.action, session_id), encoding="utf-8")
    (session_dir / "notes.md").write_text(build_notes_template(args.action), encoding="utf-8")
    (session_dir / "qa_report.md").write_text(build_qa_template(args.action), encoding="utf-8")
    (session_dir / "frames_optional").mkdir(exist_ok=True)

    return session_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a new raw session folder for new pose data collection.")
    parser.add_argument("--camera-id", required=True, help="Camera id such as camera_01.")
    parser.add_argument("--action", required=True, choices=sorted(ACTION_SPECS.keys()), help="Standardized action label.")
    parser.add_argument("--root", default="datasets/new_pose_raw", help="Root directory for raw sessions.")
    parser.add_argument("--timestamp", default=None, help="Optional fixed timestamp in YYYYMMDD_HHMMSS.")
    parser.add_argument("--recorded-at", default="", help="Optional recorded_at value.")
    parser.add_argument("--recorded-by", default="", help="Optional operator alias.")
    parser.add_argument("--runtime-profile", default="current_camera_live", help="Runtime profile label to store in metadata.")
    parser.add_argument("--source-url", default="", help="Optional RTSP URL. Password will be masked before writing.")
    parser.add_argument("--session-suffix", default="", help="Optional suffix appended to the generated session id.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    session_dir = create_session(args)
    print(session_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
