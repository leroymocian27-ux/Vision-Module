from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.post_fall_v2.domain_evidence import (
    analyze_domain_evidence,
    load_domain_frame_records,
    render_markdown_report,
    write_json,
)


DEFAULT_THRESHOLD = 0.3979087471961975


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    if not fieldnames:
        fieldnames = ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def scenario_rows(analysis: dict) -> list[dict]:
    return [
        {"scenario_label": scenario, **stats}
        for scenario, stats in analysis["scenario_probability_stats"].items()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze Post-Fall V2 current-camera domain evidence and emit threshold transfer gates."
    )
    parser.add_argument("--input", type=Path, required=True, help="Collection run directory or domain_frame_results.jsonl.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--no-calibration-sweep", action="store_true")
    parser.add_argument("--allow-empty", action="store_true", help="Emit blocked gates when no JSONL evidence exists.")
    args = parser.parse_args()

    output_dir = args.output_dir or (args.input if args.input.is_dir() else args.input.parent)
    try:
        records = load_domain_frame_records(args.input)
    except FileNotFoundError:
        if not args.allow_empty:
            raise
        records = []
    if not records and not args.allow_empty:
        raise SystemExit("no domain evidence records found; pass --allow-empty to emit blocked gates")

    analysis = analyze_domain_evidence(
        records,
        threshold=args.threshold,
        run_calibration_sweep=not args.no_calibration_sweep,
    )
    write_json(output_dir / "threshold_transfer_report.json", analysis)
    write_csv(output_dir / "clip_session_statistics.csv", analysis["clip_session_statistics"])
    write_csv(output_dir / "scenario_probability_stats.csv", scenario_rows(analysis))
    markdown = render_markdown_report(analysis)
    (output_dir / "post_fall_v2_current_camera_domain_evidence_report.md").write_text(markdown, encoding="utf-8")
    print(
        {
            "records": analysis["record_count"],
            "valid_frames": analysis["valid_frame_count"],
            "domain_dataset_gate": analysis["gates"]["Domain Dataset Gate"],
            "threshold_transfer_gate": analysis["gates"]["Threshold Transfer Gate"],
            "domain_validation_gate": analysis["gates"]["Domain Validation Gate"],
            "p3_allowed": analysis["gates"]["P3_ALLOWED"],
            "output_dir": str(output_dir),
        }
    )


if __name__ == "__main__":
    main()
