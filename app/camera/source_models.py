from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def mask_source_url(source_url: str | None) -> str | None:
    if not source_url:
        return source_url
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", source_url)


def is_mock_source(source_url: str | None) -> bool:
    return bool(source_url and source_url.startswith("mock://"))


def is_rtsp_source(source_url: str | None) -> bool:
    if not source_url:
        return False
    lowered = source_url.lower()
    return lowered.startswith("rtsp://") or lowered.startswith("rtsps://")


def is_local_file_source(source_url: str | None) -> bool:
    if not source_url or is_mock_source(source_url):
        return False
    lowered = source_url.lower()
    if lowered.startswith(("rtsp://", "rtsps://", "http://", "https://")):
        return False
    path = Path(source_url)
    if path.exists():
        return True
    if re.match(r"^[a-zA-Z]:[\\/]", source_url):
        return True
    if source_url.startswith("\\\\"):
        return True
    return False


@dataclass(frozen=True)
class CameraSourceConfig:
    camera_id: str
    source_url: str
