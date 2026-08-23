from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


ALLOWED_BINARY_LABELS = {"fall", "non_fall"}
ALLOWED_NON_FALL_SUBTYPES = {
    "standing",
    "walking",
    "sitting",
    "bending",
    "squatting",
    "picking_object",
    "lying_down_normal",
    "unknown_adl",
}

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "datasets" / "dataset_manifest.json"
DEFAULT_LABELS = ROOT / "data" / "phase6_labels" / "phase6_labels.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or validate Phase 6 label manifests.")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate-ur-fall", help="Generate initial labels from datasets/dataset_manifest.json.")
    gen.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    gen.add_argument("--output", default=str(DEFAULT_LABELS))

    validate = sub.add_parser("validate", help="Validate phase6_labels.jsonl.")
    validate.add_argument("--labels", default=str(DEFAULT_LABELS))
    validate.add_argument("--max-unknown-ratio", type=float, default=0.2)
    validate.add_argument("--allow-high-unknown", action="store_true")
    validate.add_argument("--training-only", action="store_true", help="Compute unknown_adl ratio from usable training rows only.")
    validate.add_argument("--summary-output", default=None, help="Optional path for a validation summary JSON.")

    args = parser.parse_args()
    if args.command == "generate-ur-fall":
        generate_ur_fall_labels(Path(args.manifest), Path(args.output))
    elif args.command == "validate":
        validate_labels(
            Path(args.labels),
            max_unknown_ratio=args.max_unknown_ratio,
            allow_high_unknown=args.allow_high_unknown,
            training_only=args.training_only,
            summary_output=Path(args.summary_output) if args.summary_output else None,
        )
    return 0


def generate_ur_fall_labels(manifest_path: Path, output_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ur_fall = manifest.get("ur_fall", {})
    labels = ur_fall.get("labels", {})
    rows = []
    for video_name, raw_label in sorted(labels.items()):
        stem = Path(video_name).stem
        binary_label = "fall" if raw_label == "fall" else "non_fall"
        # UR Fall ADL files are not subtype-labeled in the downloaded manifest.
        # Keep them explicit and non-promotable until manual review assigns subtype.
        subtype = None if binary_label == "fall" else "unknown_adl"
        rows.append(
            {
                "video_id": f"ur_fall/{video_name}",
                "source_dataset": "ur_fall",
                "license": "CC BY-NC-SA 4.0",
                "split_group": f"ur_fall_{stem.replace('-', '_')}",
                "binary_label": binary_label,
                "non_fall_subtype": subtype,
                "event_start_frame": 0,
                "event_end_frame": None,
                "usable_for_training": binary_label == "fall",
                "split": "unassigned",
                "notes": "UR Fall ADL subtype requires manual review before training." if subtype == "unknown_adl" else "",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(output_path), "rows": len(rows)}, ensure_ascii=False, indent=2))


def load_labels(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            row["_line_no"] = line_no
            rows.append(row)
    return rows


def validate_labels(
    path: Path,
    *,
    max_unknown_ratio: float,
    allow_high_unknown: bool,
    training_only: bool = False,
    summary_output: Path | None = None,
) -> dict:
    rows = load_labels(path)
    errors: list[str] = []
    by_split_group: dict[str, set[str]] = defaultdict(set)
    subtype_counts = Counter()
    non_fall_count = 0
    unknown_count = 0
    usable_count = 0

    for row in rows:
        line = row["_line_no"]
        binary = row.get("binary_label")
        if binary not in ALLOWED_BINARY_LABELS:
            errors.append(f"line {line}: invalid binary_label={binary!r}")
        group = row.get("split_group")
        split = row.get("split", "unassigned")
        if not group:
            errors.append(f"line {line}: missing split_group")
        else:
            by_split_group[group].add(split)
        if row.get("usable_for_training"):
            usable_count += 1
        if binary == "non_fall":
            non_fall_count += 1
            subtype = row.get("non_fall_subtype")
            if subtype not in ALLOWED_NON_FALL_SUBTYPES:
                errors.append(f"line {line}: invalid non_fall_subtype={subtype!r}")
            include_for_ratio = bool(row.get("usable_for_training")) if training_only else True
            if include_for_ratio:
                subtype_counts[subtype] += 1
            if subtype == "unknown_adl" and include_for_ratio:
                unknown_count += 1

    leaked = {
        group: sorted(splits - {"unassigned"})
        for group, splits in by_split_group.items()
        if len(splits - {"unassigned"}) > 1
    }
    if leaked:
        errors.append(f"split leakage: {leaked}")

    denominator = (
        sum(1 for row in rows if row.get("binary_label") == "non_fall" and row.get("usable_for_training"))
        if training_only
        else non_fall_count
    )
    unknown_ratio = unknown_count / denominator if denominator else 0.0
    if not allow_high_unknown and unknown_ratio >= max_unknown_ratio:
        errors.append(
            f"unknown_adl ratio too high: {unknown_ratio:.4f} >= {max_unknown_ratio:.4f}; review ADL subtypes first"
        )

    summary = {
        "labels": str(path),
        "rows": len(rows),
        "usable_for_training": usable_count,
        "non_fall_count": non_fall_count,
        "unknown_ratio_scope": "usable_for_training_non_fall" if training_only else "all_non_fall",
        "unknown_adl_count": unknown_count,
        "unknown_adl_ratio": round(unknown_ratio, 4),
        "subtype_counts": dict(subtype_counts),
        "errors": errors,
    }
    if summary_output:
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
