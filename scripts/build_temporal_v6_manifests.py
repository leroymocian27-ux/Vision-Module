from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build temporal v6 regression manifests from reviewed labels.")
    parser.add_argument(
        "--labels",
        default=str(ROOT / "data" / "phase6_labels" / "phase6_labels.jsonl"),
        help="Reviewed video label JSONL.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "evaluations" / "fall_temporal_v6"),
        help="Directory for generated manifests.",
    )
    parser.add_argument(
        "--dataset",
        default="ur_fall",
        help="Source dataset to include. Current offline video paths are resolved for ur_fall.",
    )
    args = parser.parse_args()

    labels = load_labels(Path(args.labels), source_dataset=args.dataset)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    generated = {
        "fp_regression": write_manifest(
            output_dir / "fp_regression_manifest.json",
            [row for row in labels if row.get("binary_label") == "non_fall" and row.get("usable_for_training") is True],
            purpose="hard_negative_false_positive_regression",
        ),
        "ur_full": write_manifest(
            output_dir / "temporal_v6_ur_full_manifest.json",
            [
                row
                for row in labels
                if row.get("binary_label") == "fall"
                or (row.get("binary_label") == "non_fall" and row.get("usable_for_training") is True)
            ],
            purpose="full_reviewed_ur_fall_regression",
        ),
        "slow_fall_review": write_manifest(
            output_dir / "slow_fall_review_manifest.json",
            [row for row in labels if row.get("binary_label") == "fall"],
            purpose="fall_recall_and_slow_path_candidate_review",
        ),
    }
    print(json.dumps(generated, ensure_ascii=False, indent=2))
    return 0


def load_labels(path: Path, *, source_dataset: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("source_dataset") != source_dataset:
            continue
        video_id = str(row.get("video_id") or "")
        if not video_id.endswith(".mp4"):
            continue
        rows.append(row)
    return sorted(rows, key=lambda item: str(item.get("video_id") or ""))


def write_manifest(path: Path, labels: list[dict[str, Any]], *, purpose: str) -> dict[str, Any]:
    videos = [manifest_item(row, manifest_path=path) for row in labels]
    payload = {
        "purpose": purpose,
        "source_labels": str((ROOT / "data" / "phase6_labels" / "phase6_labels.jsonl").resolve()),
        "review_status": "reviewed_labels_only",
        "videos": videos,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    subtype_counts: dict[str, int] = {}
    for item in videos:
        subtype = item.get("hard_negative_type") or item.get("label") or "unknown"
        subtype_counts[subtype] = subtype_counts.get(subtype, 0) + 1
    return {
        "path": str(path.resolve()),
        "video_count": len(videos),
        "subtype_counts": subtype_counts,
    }


def manifest_item(row: dict[str, Any], *, manifest_path: Path) -> dict[str, Any]:
    video_id = str(row["video_id"])
    dataset, filename = video_id.split("/", 1)
    video_path = ROOT / "datasets" / dataset / "videos" / filename
    label = "fall" if row.get("binary_label") == "fall" else "non_fall"
    item: dict[str, Any] = {
        "path": relative_path(video_path, manifest_path.parent),
        "video_id": video_id,
        "label": label,
        "expected_alarm": label == "fall",
        "scene_type": "floor_risk_zone" if label == "fall" else scene_type_for(row),
        "fall_start_ms": None,
        "low_posture_start_ms": None,
        "support_surface": support_surface_for(row),
        "review_status": "approved" if row.get("usable_for_training") is True or label == "fall" else "needs_review",
        "source_dataset": row.get("source_dataset"),
        "split_group": row.get("split_group"),
        "notes": row.get("notes") or "",
    }
    if label == "non_fall":
        item["hard_negative_type"] = row.get("non_fall_subtype") or "unknown_adl"
    return item


def scene_type_for(row: dict[str, Any]) -> str:
    subtype = str(row.get("non_fall_subtype") or "")
    notes = str(row.get("notes") or "").lower()
    if subtype == "lying_down_normal" and ("bed" in notes or "sofa" in notes):
        return "support_surface_zone"
    if subtype == "sitting":
        return "chair_or_support_zone"
    return "adl_floor_or_mixed_zone"


def support_surface_for(row: dict[str, Any]) -> str:
    notes = str(row.get("notes") or "").lower()
    if "bed" in notes:
        return "bed"
    if "sofa" in notes:
        return "sofa"
    if "chair" in notes:
        return "chair"
    return "none"


def relative_path(path: Path, start: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), start.resolve()).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
