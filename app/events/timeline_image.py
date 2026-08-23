from __future__ import annotations

from pathlib import Path, PurePosixPath

import cv2
import numpy as np

from app.events.schemas import EvidenceKeyframe


def build_timeline_image(
    keyframes: list[EvidenceKeyframe],
    archive_dir: str | Path,
    output_path: str | Path,
    *,
    cell_width: int = 240,
    cell_height: int = 160,
) -> Path:
    """Build a 2x3 timeline image for VLM/demo review from archived keyframes."""

    archive_root = Path(archive_dir).resolve()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    offsets = [-3000, -1000, 0, 1000, 3000, 5000]
    cells = [
        _cell_for_offset(keyframes, offset, archive_root, cell_width, cell_height)
        for offset in offsets
    ]
    top = np.hstack(cells[:3])
    bottom = np.hstack(cells[3:])
    canvas = np.vstack([top, bottom])
    if not cv2.imwrite(str(output), canvas):
        raise RuntimeError(f"failed to write timeline image: {output}")
    return output


def _cell_for_offset(
    keyframes: list[EvidenceKeyframe],
    offset_ms: int,
    archive_root: Path,
    width: int,
    height: int,
) -> np.ndarray:
    keyframe = next((item for item in keyframes if item.offset_ms == offset_ms), None)
    image = _load_keyframe_image(keyframe, archive_root)
    if image is None:
        image = np.full((height, width, 3), 214, dtype=np.uint8)
        reason = keyframe.missing_reason if keyframe and keyframe.missing_reason else "missing"
        _put_text(image, reason[:28], 12, height // 2, (80, 80, 80), 0.55)
    else:
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    _put_text(image, _label(offset_ms), 10, 24, (255, 255, 255), 0.7)
    _put_text(image, f"offset={offset_ms}ms", 10, 44, (255, 255, 255), 0.42)
    if keyframe is not None:
        meta = f"seq={keyframe.frame_seq or '-'} state={keyframe.fall_state or '-'}"
        bbox = _bbox_summary(keyframe.bbox)
        if bbox:
            meta = f"{meta} bbox={bbox}"
        _put_text(image, meta[:44], 10, height - 12, (255, 255, 255), 0.45)
    return image


def _load_keyframe_image(keyframe: EvidenceKeyframe | None, archive_root: Path) -> np.ndarray | None:
    if keyframe is None or keyframe.missing_reason or not keyframe.image_path:
        return None
    relative = _safe_relative(keyframe.image_path)
    if relative is None:
        return None
    candidate = (archive_root / relative).resolve()
    try:
        candidate.relative_to(archive_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    image = cv2.imread(str(candidate), cv2.IMREAD_COLOR)
    return image if image is not None and image.size else None


def _safe_relative(value: str) -> Path | None:
    if not value or value.startswith(("/", "\\")):
        return None
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    if any(":" in part for part in path.parts):
        return None
    return Path(*path.parts)


def _label(offset_ms: int) -> str:
    if offset_ms == 0:
        return "T0"
    seconds = abs(offset_ms) // 1000
    return f"T-{seconds}s" if offset_ms < 0 else f"T+{seconds}s"


def _bbox_summary(bbox: list[float] | None) -> str | None:
    if not bbox or len(bbox) < 4:
        return None
    return ",".join(str(int(float(value))) for value in bbox[:4])


def _put_text(image: np.ndarray, text: str, x: int, y: int, color: tuple[int, int, int], scale: float) -> None:
    cv2.putText(image, text, (x + 1, y + 1), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)
