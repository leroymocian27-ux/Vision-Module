from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PRIMARY_A = {
    "session_20260621_160200_standing_front",
    "session_20260621_160300_standing_side",
    "session_20260621_160400_standing_back",
    "session_20260621_160500_walking_slow",
}

REVIEW_B = {
    "session_20260621_161000_lying_side",
    "session_20260621_161300_fall_simulated_side",
    "session_20260621_161500_fallen_hold",
}

EXCLUDED_C = {
    "session_20260621_160100_no_person",
    "session_20260621_160600_sitting_normal",
    "session_20260621_160700_sitting_side",
    "session_20260621_160900_squat",
    "session_20260621_161100_lying_back",
    "session_20260621_161400_fall_simulated_back",
    "session_20260621_161600_recovery_standing",
}

REVIEW_D = {
    "session_20260621_160800_bending_pickup",
    "session_20260621_161200_lying_prone",
}

RETAKE_MANUAL_PASS = {
    "session_20260621_151601_recovery_standing_retake_b",
}

RETAKE_MANUAL_REVIEW = {
    "session_20260621_151401_lying_back_retake_b",
}

RETAKE_MANUAL_FAIL = {
    "session_20260621_151001_no_person_retake_b",
    "session_20260621_151101_sitting_normal_retake_b",
    "session_20260621_151201_sitting_side_retake_b",
    "session_20260621_151301_squat_retake_b",
    "session_20260621_151501_fall_simulated_back_retake_b",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(repo_root().resolve()).as_posix()


def load_all_frames(frames_root: Path, camera_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manifest_path in sorted((frames_root / camera_id).glob("*/frame_manifest.jsonl")):
        rows.extend(read_jsonl(manifest_path))
    return rows


def retake_status(raw_root: Path, camera_id: str, session_id: str) -> tuple[str, str | None]:
    qa_path = raw_root / camera_id / session_id / "qa_report.md"
    if not qa_path.exists():
        return "RETAKE_FAIL", "missing_qa_report"
    quality_status = None
    retake_reason = None
    for line in qa_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- quality_status:"):
            quality_status = line.split("`")[1] if "`" in line else line.split(":", 1)[1].strip()
        if line.startswith("- retake_reason:"):
            retake_reason = line.split("`")[1] if "`" in line else line.split(":", 1)[1].strip()
    if str(quality_status).upper() == "PASS":
        return "RETAKE_PASS", None
    if str(quality_status).upper() == "RETAKE_RECOMMENDED":
        return "RETAKE_FAIL", retake_reason or "retake_recommended"
    return "RETAKE_FAIL", retake_reason or "quality_not_pass"


def classify_row(raw_root: Path, camera_id: str, row: dict[str, Any]) -> dict[str, Any]:
    session_id = row["session_id"]
    action_label = row["action_label"]
    dataset_quality_group = "C"
    curated_include = False
    curated_role = "excluded"
    exclusion_reason = "not_classified"
    needs_human_review = False
    retake_of = None

    if session_id in PRIMARY_A:
        dataset_quality_group = "A"
        curated_include = True
        curated_role = "negative_candidate" if row.get("negative_sample") else "train_candidate"
        exclusion_reason = None
    elif session_id in REVIEW_B:
        dataset_quality_group = "B"
        curated_include = False
        curated_role = "hard_case_review"
        exclusion_reason = "batch_a_review_pool_pending_manual_confirmation"
        needs_human_review = True
    elif session_id in EXCLUDED_C:
        dataset_quality_group = "C"
        curated_include = False
        curated_role = "excluded"
        exclusion_reason = "batch_a_excluded_due_to_action_contamination"
    elif session_id in REVIEW_D:
        dataset_quality_group = "D"
        curated_include = False
        curated_role = "hard_case_review"
        exclusion_reason = "batch_a_needs_manual_review"
        needs_human_review = True
    elif "_retake_b" in session_id:
        dataset_quality_group, exclusion_reason = retake_status(raw_root, camera_id, session_id)
        if session_id in RETAKE_MANUAL_FAIL:
            dataset_quality_group = "RETAKE_FAIL"
            curated_include = False
            curated_role = "excluded"
            exclusion_reason = "manual_retake_action_mismatch"
        elif session_id in RETAKE_MANUAL_REVIEW:
            dataset_quality_group = "RETAKE_REVIEW"
            curated_include = False
            curated_role = "hard_case_review"
            exclusion_reason = "manual_retake_partial_use_only"
            needs_human_review = True
        elif action_label == "no_person_retake" and dataset_quality_group == "RETAKE_PASS" and session_id in RETAKE_MANUAL_PASS:
            curated_include = True
            curated_role = "negative_candidate"
            exclusion_reason = None
        elif dataset_quality_group == "RETAKE_PASS" and session_id in RETAKE_MANUAL_PASS:
            curated_include = True
            curated_role = "train_candidate"
            exclusion_reason = None
        else:
            curated_include = False
            curated_role = "excluded"
            if dataset_quality_group == "RETAKE_PASS":
                dataset_quality_group = "RETAKE_FAIL"
                exclusion_reason = exclusion_reason or "manual_retake_not_approved"
        retake_of = action_label.replace("_retake", "")
    else:
        exclusion_reason = "session_not_in_quality_triage"

    enriched = dict(row)
    enriched["dataset_quality_group"] = dataset_quality_group
    enriched["curated_include"] = curated_include
    enriched["curated_role"] = curated_role
    enriched["exclusion_reason"] = exclusion_reason
    enriched["retake_of"] = retake_of
    enriched["needs_human_review"] = needs_human_review
    return enriched


def build_report(output_manifest: Path, rows: list[dict[str, Any]]) -> str:
    curated_rows = [row for row in rows if row["curated_include"]]
    review_rows = [row for row in rows if row["curated_role"] == "hard_case_review"]
    excluded_rows = [row for row in rows if not row["curated_include"]]
    curated_frames_by_action = Counter(row["action_label"] for row in curated_rows)
    excluded_by_reason = Counter(row["exclusion_reason"] or "none" for row in excluded_rows)
    retake_group = defaultdict(set)
    retake_quality = Counter()
    for row in rows:
        if "_retake_b" in row["session_id"]:
            retake_group[row["session_id"]].add(row["action_label"])
            retake_quality[row["dataset_quality_group"]] += 1

    ready_actions = sorted(curated_frames_by_action)
    lines = [
        "# Curated Frame Selection Report",
        "",
        f"- curated_manifest: `{output_manifest}`",
        f"- curated_total_frames: `{len(curated_rows)}`",
        f"- curated_negative_frames: `{sum(1 for row in curated_rows if row.get('negative_sample'))}`",
        f"- curated_annotation_needed_frames: `{sum(1 for row in curated_rows if row.get('needs_pose_annotation'))}`",
        f"- curated_hard_case_review_frames: `{len(review_rows)}`",
        f"- curated_excluded_frames: `{len(excluded_rows)}`",
        "",
        "## Curated Frames By Action",
        "",
    ]
    for action, count in sorted(curated_frames_by_action.items()):
        lines.append(f"- `{action}`: `{count}`")
    lines.extend(["", "## Excluded By Reason", ""])
    for reason, count in sorted(excluded_by_reason.items()):
        lines.append(f"- `{reason}`: `{count}`")
    lines.extend(["", "## Retake Sessions", ""])
    if retake_group:
        for session_id, actions in sorted(retake_group.items()):
            lines.append(f"- `{session_id}` actions=`{', '.join(sorted(actions))}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Retake Quality Summary", ""])
    if retake_quality:
        for name, count in sorted(retake_quality.items()):
            lines.append(f"- `{name}`: `{count}`")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Ready For Annotation Actions",
            "",
        ]
    )
    if ready_actions:
        for action in ready_actions:
            lines.append(f"- `{action}`")
    else:
        lines.append("- none")
    missing_actions = [
        action
        for action in [
            "no_person_retake",
            "sitting_normal_retake",
            "sitting_side_retake",
            "squat_retake",
            "lying_back_retake",
            "fall_simulated_back_retake",
            "recovery_standing_retake",
        ]
        if action not in curated_frames_by_action
    ]
    lines.extend(
        [
            "",
            "## Actions Still Missing",
            "",
        ]
    )
    if missing_actions:
        for action in missing_actions:
            lines.append(f"- `{action}`")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Next Step Recommendation",
            "",
            "- Use the curated manifest as the only input pool for Phase 5 pre-annotation QA.",
            "- Keep Batch A review-pool frames out of main annotation until manually approved.",
            "- If any required retake action is still missing, do not start full annotation yet.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a curated new-pose manifest from Batch A triage and Batch B retakes.")
    parser.add_argument("--raw-root", default="datasets/new_pose_raw", help="Root raw dataset directory.")
    parser.add_argument("--frames-root", default="datasets/new_pose_frames", help="Root frame dataset directory.")
    parser.add_argument("--camera-id", default="camera_01", help="Camera id.")
    parser.add_argument("--output-manifest", required=True, help="Output curated manifest jsonl path.")
    parser.add_argument("--output-report", required=True, help="Output curated report markdown path.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = repo_root()
    raw_root = (root / args.raw_root).resolve()
    frames_root = (root / args.frames_root).resolve()
    output_manifest = (Path(args.output_manifest) if Path(args.output_manifest).is_absolute() else root / args.output_manifest).resolve()
    output_report = (Path(args.output_report) if Path(args.output_report).is_absolute() else root / args.output_report).resolve()

    rows = load_all_frames(frames_root, args.camera_id)
    enriched = [classify_row(raw_root, args.camera_id, row) for row in rows]

    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    if output_manifest.exists():
        output_manifest.unlink()
    for row in enriched:
        append_jsonl(output_manifest, row)

    report = build_report(output_manifest, enriched)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_report.write_text(report, encoding="utf-8")
    print(json.dumps({"manifest": repo_relative(output_manifest), "report": repo_relative(output_report)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
