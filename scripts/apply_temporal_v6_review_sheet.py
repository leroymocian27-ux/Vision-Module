from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_temporal_v6_review_seed import validate_rows

DEFAULT_SHEET = ROOT / "data" / "temporal_v6_review" / "professor_review_packet" / "residual_fn_review_sheet.csv"
DEFAULT_INPUT = ROOT / "data" / "temporal_v6_review" / "residual_fn_review_seed.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "temporal_v6_review" / "residual_fn_review_seed.jsonl"

REVIEW_FIELDS = [
    "review_status",
    "usable_for_training",
    "review_decision",
    "fall_start_ms",
    "ground_contact_start_ms",
    "low_posture_start_ms",
    "motion_end_ms",
    "recovery_start_ms",
    "recovered_within_5s",
    "scene_type",
    "support_surface",
    "occlusion_level",
    "track_quality_issue",
    "pose_quality_issue",
    "fall_subtype",
    "reviewer",
    "review_notes",
]

BOOL_FIELDS = {
    "usable_for_training",
    "recovered_within_5s",
    "track_quality_issue",
    "pose_quality_issue",
}

NUMBER_FIELDS = {
    "fall_start_ms",
    "ground_contact_start_ms",
    "low_posture_start_ms",
    "motion_end_ms",
    "recovery_start_ms",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply professor temporal v6 review sheet CSV back to review JSONL.")
    parser.add_argument("--sheet", default=str(DEFAULT_SHEET), help="Professor review CSV sheet.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Existing residual review seed JSONL.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Updated review JSONL output.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print summary without writing output.")
    args = parser.parse_args()

    result = apply_review_sheet(
        sheet_path=Path(args.sheet),
        input_path=Path(args.input),
        output_path=Path(args.output),
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["validation"]["error_count"] else 0


def apply_review_sheet(*, sheet_path: Path, input_path: Path, output_path: Path, dry_run: bool) -> dict[str, Any]:
    seed_rows = read_jsonl(input_path)
    sheet_rows = read_sheet(sheet_path)
    sheet_by_video = {str(row.get("video_id") or ""): row for row in sheet_rows if row.get("video_id")}
    updated_rows: list[dict[str, Any]] = []
    changed_videos: list[str] = []
    missing_in_sheet: list[str] = []

    for seed in seed_rows:
        video_id = str(seed.get("video_id") or "")
        sheet = sheet_by_video.get(video_id)
        if sheet is None:
            missing_in_sheet.append(video_id)
            updated_rows.append(seed)
            continue
        updated = update_seed_row(seed, sheet)
        if comparable(seed) != comparable(updated):
            changed_videos.append(video_id)
        updated_rows.append(updated)

    validation = validate_rows(updated_rows, source=output_path)
    should_write = (
        not dry_run
        and not validation["error_count"]
        and (bool(changed_videos) or output_path.resolve() != input_path.resolve())
    )
    if should_write:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(output_path, updated_rows)

    return {
        "sheet": str(sheet_path.resolve()),
        "input": str(input_path.resolve()),
        "output": str(output_path.resolve()),
        "dry_run": dry_run,
        "seed_rows": len(seed_rows),
        "sheet_rows": len(sheet_rows),
        "changed_count": len(changed_videos),
        "changed_videos": changed_videos,
        "missing_in_sheet": missing_in_sheet,
        "validation": validation,
        "written": should_write,
    }


def update_seed_row(seed: dict[str, Any], sheet: dict[str, str]) -> dict[str, Any]:
    updated = dict(seed)
    updated.pop("_line_number", None)
    for field in REVIEW_FIELDS:
        if field not in sheet:
            continue
        parsed = parse_field(field, sheet.get(field))
        if parsed is _EMPTY:
            continue
        updated[field] = parsed
    return updated


def parse_field(field: str, value: str | None) -> Any:
    raw = "" if value is None else str(value).strip()
    if raw == "":
        return _EMPTY
    if field in BOOL_FIELDS:
        return parse_bool(raw)
    if field in NUMBER_FIELDS:
        return parse_number(raw)
    return raw


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def parse_number(value: str) -> int | float:
    number = float(value)
    return int(number) if number.is_integer() else number


def comparable(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in REVIEW_FIELDS}


def read_sheet(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


class _Empty:
    pass


_EMPTY = _Empty()


if __name__ == "__main__":
    raise SystemExit(main())
