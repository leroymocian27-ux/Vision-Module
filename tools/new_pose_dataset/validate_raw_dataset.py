from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


VALID_ACTIONS = {
    "no_person",
    "no_person_retake",
    "standing_front",
    "standing_side",
    "standing_back",
    "walking_slow",
    "sitting_normal",
    "sitting_normal_retake",
    "sitting_side",
    "sitting_side_retake",
    "bending_pickup",
    "bending_pickup_retake",
    "squat",
    "squat_retake",
    "lying_side",
    "lying_back",
    "lying_back_retake",
    "lying_prone",
    "lying_prone_retake",
    "fall_simulated_side",
    "fall_simulated_back",
    "fall_simulated_back_retake",
    "fallen_hold",
    "recovery_standing",
    "recovery_standing_retake",
    "partial_occlusion",
    "near_edge",
    "low_light",
    "far_distance",
    "close_distance",
    "loose_clothes",
    "dark_clothes",
    "bright_clothes",
}


def contains_secret(url: str) -> bool:
    return bool(re.search(r"rtsp://[^:/?#]+:[^*@/]+@", url or "", flags=re.IGNORECASE))


def validate_session(session_dir: Path) -> dict:
    metadata_path = session_dir / "metadata.json"
    video_path = session_dir / "video.mp4"
    preview_path = session_dir / "preview.gif"
    notes_path = session_dir / "notes.md"
    status_path = session_dir / "status_samples.jsonl"
    integration_path = session_dir / "integration_latest_samples.jsonl"
    qa_path = session_dir / "qa_report.md"

    result = {
        "session": session_dir.name,
        "valid": True,
        "missing_metadata": False,
        "missing_video": False,
        "missing_preview": False,
        "missing_notes": False,
        "missing_status_samples": False,
        "missing_integration_samples": False,
        "invalid_action_label": False,
        "possible_secret_leak": False,
        "duration_problem": False,
        "quality_status": None,
        "retake_recommended": False,
        "usable_for_training": False,
        "usable_for_eval": False,
        "hard_case": False,
        "actions": [],
        "issues": [],
    }

    if not metadata_path.exists():
        result["valid"] = False
        result["missing_metadata"] = True
        result["issues"].append("missing_metadata")
        return result

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    actions = metadata.get("action_labels") or []
    result["actions"] = actions

    if not video_path.exists():
        result["valid"] = False
        result["missing_video"] = True
        result["issues"].append("missing_video")

    if not preview_path.exists():
        result["valid"] = False
        result["missing_preview"] = True
        result["issues"].append("missing_preview")

    if not notes_path.exists():
        result["valid"] = False
        result["missing_notes"] = True
        result["issues"].append("missing_notes")

    if not status_path.exists() or status_path.stat().st_size <= 0:
        result["valid"] = False
        result["missing_status_samples"] = True
        result["issues"].append("missing_status_samples")

    if not integration_path.exists() or integration_path.stat().st_size <= 0:
        result["valid"] = False
        result["missing_integration_samples"] = True
        result["issues"].append("missing_integration_samples")

    if not actions or any(action not in VALID_ACTIONS for action in actions):
        result["valid"] = False
        result["invalid_action_label"] = True
        result["issues"].append("invalid_action_label")

    if contains_secret(str(metadata.get("source_url_masked") or "")):
        result["valid"] = False
        result["possible_secret_leak"] = True
        result["issues"].append("possible_secret_leak")

    duration = metadata.get("duration_sec")
    if duration is not None:
        try:
            duration_value = float(duration)
            if duration_value <= 0 or duration_value > 3600:
                result["duration_problem"] = True
                result["issues"].append("duration_problem")
        except (TypeError, ValueError):
            result["duration_problem"] = True
            result["issues"].append("duration_problem")

    result["usable_for_training"] = bool(metadata.get("usable_for_training"))
    result["usable_for_eval"] = bool(metadata.get("usable_for_eval"))
    result["hard_case"] = bool(metadata.get("hard_case"))

    if qa_path.exists():
        qa_text = qa_path.read_text(encoding="utf-8")
        for line in qa_text.splitlines():
            if line.startswith("- quality_status:"):
                result["quality_status"] = line.split("`")[1] if "`" in line else line.split(":", 1)[1].strip()
            if line.startswith("- retake_reason:"):
                value = line.split("`")[1] if "`" in line else line.split(":", 1)[1].strip()
                if value not in {"None", "null", "", "None`"}:
                    result["retake_recommended"] = True
        if str(result["quality_status"]).upper() == "FAIL":
            result["valid"] = False
            result["issues"].append("quality_fail")
        if str(result["quality_status"]).upper() == "RETAKE_RECOMMENDED":
            result["retake_recommended"] = True

    if metadata.get("usable_for_training") is None:
        result["usable_for_training"] = bool(
            result["valid"] and not result["retake_recommended"] and actions not in (["no_person"], ["no_person_retake"])
        )
    if metadata.get("usable_for_eval") is None:
        result["usable_for_eval"] = bool(result["valid"])
    if not result["hard_case"]:
        result["hard_case"] = any(
            action in {"partial_occlusion", "near_edge", "low_light", "far_distance", "close_distance"}
            for action in actions
        )

    return result


def build_report(root: Path, session_results: list[dict]) -> str:
    total_sessions = len(session_results)
    valid_sessions = sum(1 for item in session_results if item["valid"])
    invalid_sessions = total_sessions - valid_sessions
    missing_metadata = sum(1 for item in session_results if item["missing_metadata"])
    missing_video = sum(1 for item in session_results if item["missing_video"])
    missing_preview = sum(1 for item in session_results if item["missing_preview"])
    missing_status_samples = sum(1 for item in session_results if item["missing_status_samples"])
    missing_integration_samples = sum(1 for item in session_results if item["missing_integration_samples"])
    invalid_action_label = sum(1 for item in session_results if item["invalid_action_label"])
    possible_secret_leak = sum(1 for item in session_results if item["possible_secret_leak"])
    needs_retake_sessions = sum(1 for item in session_results if item["retake_recommended"])
    usable_for_training_sessions = sum(1 for item in session_results if item["usable_for_training"])
    usable_for_eval_sessions = sum(1 for item in session_results if item["usable_for_eval"])
    hard_case_sessions = sum(1 for item in session_results if item["hard_case"])
    action_distribution = Counter()
    for item in session_results:
        for action in item["actions"]:
            action_distribution[action] += 1

    lines = [
        "# Raw Dataset QA Report",
        "",
        f"- root: `{root}`",
        f"- total_sessions: `{total_sessions}`",
        f"- valid_sessions: `{valid_sessions}`",
        f"- invalid_sessions: `{invalid_sessions}`",
        f"- missing_metadata: `{missing_metadata}`",
        f"- missing_video: `{missing_video}`",
        f"- missing_preview: `{missing_preview}`",
        f"- missing_status_samples: `{missing_status_samples}`",
        f"- missing_integration_samples: `{missing_integration_samples}`",
        f"- invalid_action_label: `{invalid_action_label}`",
        f"- possible_secret_leak: `{possible_secret_leak}`",
        f"- needs_retake_sessions: `{needs_retake_sessions}`",
        f"- usable_for_training_sessions: `{usable_for_training_sessions}`",
        f"- usable_for_eval_sessions: `{usable_for_eval_sessions}`",
        f"- hard_case_sessions: `{hard_case_sessions}`",
        "",
        "## Action Distribution",
        "",
    ]

    if action_distribution:
        for action, count in sorted(action_distribution.items()):
            lines.append(f"- `{action}`: `{count}`")
    else:
        lines.append("- none")

    lines.extend(["", "## Session Details", ""])
    if not session_results:
        lines.append("- no sessions found")
    else:
        for item in session_results:
            issue_text = ", ".join(item["issues"]) if item["issues"] else "none"
            lines.append(
                f"- `{item['session']}` valid=`{item['valid']}` quality_status=`{item['quality_status']}` "
                f"retake_recommended=`{item['retake_recommended']}` issues=`{issue_text}`"
            )

    lines.extend(
        [
            "",
            "## Recommended Next Actions",
            "",
            "- Fill in missing `video.mp4` and `preview.gif` after real collection.",
            "- Keep `source_url_masked` sanitized.",
            "- Use only standardized action labels.",
            "- Do not treat template-only sessions as production data until metadata is completed.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate raw new-pose dataset session folders.")
    parser.add_argument("--root", default="datasets/new_pose_raw", help="Root directory for raw dataset sessions.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = Path(args.root).resolve()
    session_dirs = [path for path in root.glob("*/*") if path.is_dir()]
    session_results = [validate_session(session_dir) for session_dir in sorted(session_dirs)]
    report = build_report(root, session_results)
    output_path = root / "dataset_raw_qa_report.md"
    output_path.write_text(report, encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
