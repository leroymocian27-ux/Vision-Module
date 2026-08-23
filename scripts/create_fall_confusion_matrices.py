from __future__ import annotations

import argparse
import csv
import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("reports") / "fall_confusion_matrix"


@dataclass(frozen=True)
class Confusion:
    true_negative: int
    false_positive: int
    false_negative: int
    true_positive: int

    @property
    def total(self) -> int:
        return self.true_negative + self.false_positive + self.false_negative + self.true_positive

    @property
    def accuracy(self) -> float:
        return safe_div(self.true_positive + self.true_negative, self.total)

    @property
    def precision(self) -> float:
        return safe_div(self.true_positive, self.true_positive + self.false_positive)

    @property
    def recall(self) -> float:
        return safe_div(self.true_positive, self.true_positive + self.false_negative)

    @property
    def f1(self) -> float:
        precision = self.precision
        recall = self.recall
        return safe_div(2 * precision * recall, precision + recall)

    def as_dict(self) -> dict[str, int]:
        return {
            "true_negative": self.true_negative,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "true_positive": self.true_positive,
        }


@dataclass(frozen=True)
class Panel:
    title: str
    confusion: Confusion
    source: str
    note: str | None = None
    color: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create fall/non-fall confusion matrix reports from system evaluation JSON files."
    )
    parser.add_argument(
        "--panel",
        action="append",
        default=[],
        metavar="TITLE=PATH",
        help="Panel title and JSON path. Repeat for side-by-side comparison.",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Single JSON path. Used with --title when --panel is not supplied.",
    )
    parser.add_argument("--title", default="Fall Detection", help="Single-panel title.")
    parser.add_argument("--note", default=None, help="Single-panel note.")
    parser.add_argument(
        "--config",
        default=None,
        help="Optional JSON config with a panels list. Each panel supports title, path, note, color.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for SVG/CSV/JSON/Markdown.")
    parser.add_argument("--basename", default="fall_confusion_matrices", help="Output file basename.")
    args = parser.parse_args()

    panels = load_panels(args)
    if not panels:
        raise SystemExit("provide --config, --panel TITLE=PATH, or --input PATH")

    output_dir = resolve_path(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = safe_stem(args.basename)
    report = build_report(panels)

    json_path = output_dir / f"{basename}.json"
    csv_path = output_dir / f"{basename}.csv"
    md_path = output_dir / f"{basename}.md"
    svg_path = output_dir / f"{basename}.svg"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(csv_path, panels)
    write_markdown(md_path, panels)
    svg_path.write_text(render_svg(panels), encoding="utf-8")

    print(
        json.dumps(
            {
                "panel_count": len(panels),
                "json": str(json_path.resolve()),
                "csv": str(csv_path.resolve()),
                "markdown": str(md_path.resolve()),
                "svg": str(svg_path.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def load_panels(args: argparse.Namespace) -> list[Panel]:
    if args.config:
        return load_panels_from_config(Path(args.config))
    if args.panel:
        return [load_panel_spec(item) for item in args.panel]
    if args.input:
        payload = load_json(Path(args.input))
        return [
            Panel(
                title=args.title,
                confusion=extract_confusion(payload),
                source=str(Path(args.input)),
                note=args.note,
            )
        ]
    return []


def load_panels_from_config(path: Path) -> list[Panel]:
    payload = load_json(path)
    rows = payload.get("panels")
    if not isinstance(rows, list):
        raise SystemExit("config JSON must contain a panels list")
    panels: list[Panel] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise SystemExit(f"panel #{index} must be an object")
        title = str(row.get("title") or f"Panel {index}")
        raw_path = row.get("path") or row.get("metrics_json") or row.get("input")
        if not raw_path:
            raise SystemExit(f"panel #{index} missing path")
        input_path = Path(str(raw_path))
        payload = load_json(input_path)
        panels.append(
            Panel(
                title=title,
                confusion=extract_confusion(payload),
                source=str(input_path),
                note=str(row.get("note")) if row.get("note") is not None else None,
                color=str(row.get("color")) if row.get("color") is not None else None,
            )
        )
    return panels


def load_panel_spec(spec: str) -> Panel:
    if "=" not in spec:
        raise SystemExit(f"--panel must use TITLE=PATH: {spec}")
    title, raw_path = spec.split("=", 1)
    input_path = Path(raw_path.strip())
    payload = load_json(input_path)
    return Panel(title=title.strip() or input_path.stem, confusion=extract_confusion(payload), source=str(input_path))


def extract_confusion(payload: dict[str, Any]) -> Confusion:
    for metrics in metric_candidates(payload):
        raw = metrics.get("confusion") if isinstance(metrics.get("confusion"), dict) else None
        if raw:
            confusion = confusion_from_mapping(raw)
            if confusion.total > 0:
                return confusion
    videos = payload.get("videos")
    if isinstance(videos, list):
        confusion = confusion_from_offline_videos(videos)
        if confusion.total > 0:
            return confusion
    raise SystemExit("could not find confusion data in JSON")


def metric_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = [
        payload.get("event_metrics"),
        payload.get("v6_event_metrics"),
        payload.get("metrics"),
        payload.get("summary"),
        payload,
    ]
    return [item for item in candidates if isinstance(item, dict)]


def confusion_from_mapping(raw: dict[str, Any]) -> Confusion:
    return Confusion(
        true_negative=int_number(raw, "true_negative", "tn"),
        false_positive=int_number(raw, "false_positive", "fp"),
        false_negative=int_number(raw, "false_negative", "fn"),
        true_positive=int_number(raw, "true_positive", "tp"),
    )


def confusion_from_offline_videos(videos: list[Any]) -> Confusion:
    tp = fp = fn = tn = 0
    for item in videos:
        if not isinstance(item, dict):
            continue
        expected = expected_alarm(item)
        predicted = predicted_alarm(item)
        if expected and predicted:
            tp += 1
        elif expected and not predicted:
            fn += 1
        elif not expected and predicted:
            fp += 1
        else:
            tn += 1
    return Confusion(true_negative=tn, false_positive=fp, false_negative=fn, true_positive=tp)


def expected_alarm(item: dict[str, Any]) -> bool:
    value = item.get("expected_alarm")
    if isinstance(value, bool):
        return value
    label = str(item.get("manifest_label") or item.get("label") or "").strip().lower()
    return label in {"fall", "fallen", "falling", "positive", "1", "true"}


def predicted_alarm(item: dict[str, Any]) -> bool:
    return int_number(item, "alarm_confirmed_frames") > 0 or int_number(item, "confirmed_frames") > 0


def build_report(panels: list[Panel]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "fall_confusion_matrix_report.v1",
        "panels": [
            {
                "title": panel.title,
                "source": panel.source,
                "note": panel.note,
                "confusion": panel.confusion.as_dict(),
                "metrics": metrics_dict(panel.confusion),
            }
            for panel in panels
        ],
    }


def write_csv(path: Path, panels: list[Panel]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "title",
                "source",
                "true_negative",
                "false_positive",
                "false_negative",
                "true_positive",
                "accuracy",
                "precision",
                "recall",
                "f1",
            ],
        )
        writer.writeheader()
        for panel in panels:
            writer.writerow(
                {
                    "title": panel.title,
                    "source": panel.source,
                    **panel.confusion.as_dict(),
                    **metrics_dict(panel.confusion),
                }
            )


def write_markdown(path: Path, panels: list[Panel]) -> None:
    lines = [
        "# Fall Confusion Matrices",
        "",
        "| Model | TN | FP | FN | TP | Accuracy | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for panel in panels:
        metrics = metrics_dict(panel.confusion)
        lines.append(
            "| {title} | {tn} | {fp} | {fn} | {tp} | {accuracy} | {precision} | {recall} | {f1} |".format(
                title=panel.title,
                tn=panel.confusion.true_negative,
                fp=panel.confusion.false_positive,
                fn=panel.confusion.false_negative,
                tp=panel.confusion.true_positive,
                accuracy=percent(metrics["accuracy"]),
                precision=percent(metrics["precision"]),
                recall=percent(metrics["recall"]),
                f1=percent(metrics["f1"]),
            )
        )
    lines.append("")
    lines.append("## Sources")
    lines.append("")
    for panel in panels:
        lines.append(f"- {panel.title}: `{panel.source}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_svg(panels: list[Panel]) -> str:
    panel_w = 330
    panel_h = 395
    gap = 24
    width = max(1, len(panels)) * panel_w + max(0, len(panels) - 1) * gap + 32
    height = panel_h + 28
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    palette = ["#0b4fa8", "#007c7a", "#11823b", "#7a4dbb", "#b25a16"]
    for index, panel in enumerate(panels):
        x = 16 + index * (panel_w + gap)
        color = panel.color or palette[index % len(palette)]
        parts.append(render_panel(panel, x=x, y=14, width=panel_w, height=panel_h, color=color))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render_panel(panel: Panel, *, x: int, y: int, width: int, height: int, color: str) -> str:
    c = panel.confusion
    values = [c.true_negative, c.false_positive, c.false_negative, c.true_positive]
    max_value = max(values) if values else 1
    cells = [
        ("TN", c.true_negative, 0, 0),
        ("FP", c.false_positive, 1, 0),
        ("FN", c.false_negative, 0, 1),
        ("TP", c.true_positive, 1, 1),
    ]
    cell = 86
    grid_x = x + 88
    grid_y = y + 72
    metrics = metrics_dict(c)
    parts = [
        f'<g transform="translate({x},{y})">',
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="6" fill="#ffffff" stroke="{color}" stroke-width="1.2"/>',
        f'<rect x="14" y="0" width="{width - 28}" height="38" rx="5" fill="{color}"/>',
        svg_text(panel.title, width / 2, 25, size=18, fill="#ffffff", weight="700", anchor="middle"),
        svg_text("Actual", 24, 156, size=14, fill="#1f2937", weight="700", anchor="middle", rotate=-90),
        svg_text("Predicted", 174, 260, size=14, fill="#1f2937", weight="700", anchor="middle"),
        svg_text("Non-fall", 118, 249, size=12, fill="#1f2937", anchor="middle"),
        svg_text("Fall", 204, 249, size=12, fill="#1f2937", anchor="middle"),
        svg_text("Non-fall", 58, 126, size=12, fill="#1f2937", anchor="middle"),
        svg_text("Fall", 58, 212, size=12, fill="#1f2937", anchor="middle"),
    ]
    for label, value, col, row in cells:
        strength = 0.12 + 0.78 * safe_div(value, max_value)
        fill = mix_with_white(color, strength)
        cx = grid_x + col * cell
        cy = grid_y + row * cell
        text_fill = "#ffffff" if strength > 0.55 else "#111827"
        parts.extend(
            [
                f'<rect x="{cx}" y="{cy}" width="{cell}" height="{cell}" fill="{fill}" stroke="#ffffff" stroke-width="2"/>',
                svg_text(str(value), cx + cell / 2, cy + 35, size=20, fill=text_fill, weight="700", anchor="middle"),
                svg_text(f"({label})", cx + cell / 2, cy + 58, size=14, fill=text_fill, weight="700", anchor="middle"),
            ]
        )
    parts.extend(
        [
            f'<rect x="18" y="282" width="{width - 36}" height="78" rx="6" fill="#ffffff" stroke="{color}" stroke-width="1"/>',
            svg_text(f"Accuracy: {percent(metrics['accuracy'])}", 44, 312, size=12, fill="#111827"),
            svg_text(f"Recall: {percent(metrics['recall'])}", 190, 312, size=12, fill="#111827"),
            svg_text(f"Precision: {percent(metrics['precision'])}", 44, 344, size=12, fill="#111827"),
            svg_text(f"F1-score: {percent(metrics['f1'])}", 190, 344, size=12, fill="#111827"),
        ]
    )
    if panel.note:
        parts.extend(
            [
                f'<rect x="18" y="368" width="{width - 36}" height="20" rx="4" fill="#ffffff" stroke="{color}" stroke-width="1" stroke-dasharray="5 4"/>',
                svg_text(panel.note, width / 2, 383, size=11, fill="#1f2937", anchor="middle"),
            ]
        )
    parts.append("</g>")
    return "\n".join(parts)


def svg_text(
    value: str,
    x: float,
    y: float,
    *,
    size: int,
    fill: str,
    weight: str = "400",
    anchor: str = "start",
    rotate: int | None = None,
) -> str:
    transform = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
    return (
        f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}" fill="{fill}"{transform}>'
        f"{html.escape(value)}</text>"
    )


def mix_with_white(color: str, strength: float) -> str:
    color = color.strip().lstrip("#")
    if len(color) != 6:
        color = "0b4fa8"
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    strength = max(0.0, min(1.0, strength))
    out = [
        round(255 * (1 - strength) + channel * strength)
        for channel in (r, g, b)
    ]
    return "#" + "".join(f"{value:02x}" for value in out)


def metrics_dict(confusion: Confusion) -> dict[str, float]:
    return {
        "accuracy": round(confusion.accuracy, 6),
        "precision": round(confusion.precision, 6),
        "recall": round(confusion.recall, 6),
        "f1": round(confusion.f1, 6),
    }


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def int_number(payload: dict[str, Any], *names: str) -> int:
    for name in names:
        try:
            value = payload.get(name)
            if value is not None and value != "":
                return int(float(value))
        except (TypeError, ValueError):
            continue
    return 0


def safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def load_json(path: Path) -> dict[str, Any]:
    resolved = resolve_path(path)
    if not resolved.exists():
        raise SystemExit(f"missing JSON file: {path}")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON root must be an object: {path}")
    return payload


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def safe_stem(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value)
    return cleaned.strip("._") or "fall_confusion_matrices"


if __name__ == "__main__":
    raise SystemExit(main())
