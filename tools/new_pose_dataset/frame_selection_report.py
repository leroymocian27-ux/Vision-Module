from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def build_report(manifest_path: Path, rows: list[dict[str, Any]]) -> str:
    frames_by_action = Counter()
    frames_by_phase = Counter()
    quality_warning_counts = Counter()
    sessions = defaultdict(list)
    negative_frames = 0
    annotation_needed_frames = 0
    hard_case_frames = 0
    excluded_frames = 0

    for row in rows:
        frames_by_action[row["action_label"]] += 1
        frames_by_phase[row["action_phase"]] += 1
        for warning in row.get("quality_warnings") or []:
            quality_warning_counts[warning] += 1
        sessions[row["session_id"]].append(row)
        if row.get("negative_sample"):
            negative_frames += 1
        if row.get("needs_pose_annotation"):
            annotation_needed_frames += 1
        if row.get("hard_case_candidate"):
            hard_case_frames += 1
        if row.get("excluded"):
            excluded_frames += 1

    sessions_need_review = []
    for session_id, session_rows in sorted(sessions.items()):
        warning_total = sum(len(item.get("quality_warnings") or []) for item in session_rows)
        if warning_total > max(5, len(session_rows) // 4):
            sessions_need_review.append(session_id)

    recommended_train = sum(1 for row in rows if row.get("split_hint") == "train" and row.get("needs_pose_annotation"))
    recommended_eval = sum(1 for row in rows if row.get("split_hint") in {"val", "eval"})
    recommended_hard = sum(1 for row in rows if row.get("hard_case_candidate"))
    recommended_negative = sum(1 for row in rows if row.get("negative_sample"))

    lines = [
        "# New Pose Frame Selection Report",
        "",
        f"- manifest: `{manifest_path}`",
        f"- total_sessions: `{len(sessions)}`",
        f"- total_frames_extracted: `{len(rows)}`",
        f"- negative_frames: `{negative_frames}`",
        f"- annotation_needed_frames: `{annotation_needed_frames}`",
        f"- hard_case_frames: `{hard_case_frames}`",
        f"- excluded_frames: `{excluded_frames}`",
        "",
        "## Frames By Action",
        "",
    ]

    for action, count in sorted(frames_by_action.items()):
        lines.append(f"- `{action}`: `{count}`")

    lines.extend(["", "## Frames By Phase", ""])
    for phase, count in sorted(frames_by_phase.items()):
        lines.append(f"- `{phase}`: `{count}`")

    lines.extend(["", "## Quality Warning Counts", ""])
    if quality_warning_counts:
        for name, count in sorted(quality_warning_counts.items()):
            lines.append(f"- `{name}`: `{count}`")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Candidate Summary",
            "",
            f"- recommended_train_candidates: `{recommended_train}`",
            f"- recommended_eval_candidates: `{recommended_eval}`",
            f"- recommended_hard_cases: `{recommended_hard}`",
            f"- recommended_negative_samples: `{recommended_negative}`",
            "",
            "## Sessions Need Review",
            "",
        ]
    )

    if sessions_need_review:
        for session_id in sessions_need_review:
            lines.append(f"- `{session_id}`")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Action Coverage",
            "",
            f"- action_coverage: `{'PASS' if len(frames_by_action) >= 16 else 'PARTIAL'}`",
            "",
            "## Next Step Recommendation",
            "",
            "- Proceed to Phase 5 annotation guideline and pre-annotation QA.",
            "- Keep `A01 no_person` as negative/eval reference and do not move it into the keypoint-primary annotation pool.",
            "- Review warnings before final annotation export, but light blur warnings alone do not require retake.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a markdown summary for extracted new-pose frames.")
    parser.add_argument("--manifest", required=True, help="Global frame manifest jsonl path.")
    parser.add_argument("--output", required=True, help="Output markdown report path.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    manifest_path = (Path(args.manifest) if Path(args.manifest).is_absolute() else repo_root / args.manifest).resolve()
    output_path = (Path(args.output) if Path(args.output).is_absolute() else repo_root / args.output).resolve()
    rows = read_jsonl(manifest_path)
    report = build_report(manifest_path, rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
