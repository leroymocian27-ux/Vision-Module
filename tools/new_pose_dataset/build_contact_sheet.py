from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


THUMBNAIL_SIZE = (160, 90)
LABEL_HEIGHT = 36
PADDING = 8


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def shorten_session_id(session_id: str) -> str:
    parts = session_id.split("_")
    return "_".join(parts[-2:]) if len(parts) >= 2 else session_id


def choose_batch_preview_rows(rows: list[dict[str, Any]], per_session: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["session_id"]].append(row)
    selected: list[dict[str, Any]] = []
    for session_id in sorted(grouped):
        session_rows = sorted(grouped[session_id], key=lambda item: item["frame_index"])
        if len(session_rows) <= per_session:
            selected.extend(session_rows)
            continue
        step = max(1, len(session_rows) // per_session)
        preview = session_rows[::step][:per_session]
        selected.extend(preview)
    return selected


def build_sheet(rows: list[dict[str, Any]], output_path: Path, title: str, columns: int) -> None:
    if not rows:
        raise ValueError("cannot build contact sheet with no rows")
    font = ImageFont.load_default()
    rows_count = math.ceil(len(rows) / columns)
    cell_width = THUMBNAIL_SIZE[0] + PADDING * 2
    cell_height = THUMBNAIL_SIZE[1] + LABEL_HEIGHT + PADDING * 2
    title_height = 28
    canvas = Image.new(
        "RGB",
        (columns * cell_width, title_height + rows_count * cell_height),
        color=(245, 245, 245),
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((PADDING, 6), title, fill=(20, 20, 20), font=font)

    root = repo_root()
    for index, row in enumerate(rows):
        grid_x = index % columns
        grid_y = index // columns
        x = grid_x * cell_width + PADDING
        y = title_height + grid_y * cell_height + PADDING

        image_path = (root / row["image_path"]).resolve()
        image = Image.open(image_path).convert("RGB")
        image.thumbnail(THUMBNAIL_SIZE)
        paste_x = x + (THUMBNAIL_SIZE[0] - image.width) // 2
        paste_y = y + (THUMBNAIL_SIZE[1] - image.height) // 2
        canvas.paste(image, (paste_x, paste_y))
        label = (
            f"{shorten_session_id(row['session_id'])}\n"
            f"{row['action_label']} t={row['timestamp_sec']:.2f}s\n"
            f"idx={row['frame_index']}"
        )
        draw.multiline_text(
            (x, y + THUMBNAIL_SIZE[1] + 4),
            label,
            fill=(20, 20, 20),
            font=font,
            spacing=2,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=90)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build contact sheets from extracted frame manifests.")
    parser.add_argument("--manifest", required=True, help="Session or global frame manifest jsonl path.")
    parser.add_argument("--batch-per-session", type=int, default=4, help="Frames per session for the global batch sheet.")
    parser.add_argument("--session-columns", type=int, default=5, help="Columns for each session contact sheet.")
    parser.add_argument("--batch-columns", type=int, default=4, help="Columns for the global batch contact sheet.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    manifest_path = (Path(args.manifest) if Path(args.manifest).is_absolute() else repo_root() / args.manifest).resolve()
    rows = read_jsonl(manifest_path)
    if not rows:
        raise ValueError(f"empty manifest: {manifest_path}")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["session_id"]].append(row)

    global_root = manifest_path.parent
    for session_id, session_rows in sorted(grouped.items()):
        session_output = global_root / session_id / "contact_sheet.jpg"
        build_sheet(
            sorted(session_rows, key=lambda item: item["frame_index"]),
            session_output,
            title=f"{session_id} ({session_rows[0]['action_label']})",
            columns=args.session_columns,
        )

    batch_rows = choose_batch_preview_rows(rows, args.batch_per_session)
    batch_output = global_root / "batch_a_contact_sheet.jpg"
    build_sheet(
        batch_rows,
        batch_output,
        title=f"Batch A Contact Sheet ({len(batch_rows)} preview frames)",
        columns=args.batch_columns,
    )

    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "session_contact_sheets": len(grouped),
                "batch_contact_sheet": str(batch_output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
