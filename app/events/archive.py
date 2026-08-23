from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Callable

import cv2

from app.events.ring_frame_buffer import KeyframeSelection
from app.events.qwen_keyframe import QwenImageInput
from app.events.schemas import EvidencePackage, EventSemantics, QwenKeyframeAdvisory, TrustedEventResult
from app.events.timeline_image import build_timeline_image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArchiveResult:
    archive_path: str
    summary: dict[str, object]
    evidence: EvidencePackage


class EventArchive:
    """Best-effort, bounded incident archive stored outside the realtime path."""

    def __init__(
        self,
        root_dir: str | Path,
        *,
        enabled: bool = False,
        save_keyframes: bool = True,
        save_json: bool = True,
        max_events_per_camera: int = 200,
        retention_days: int = 30,
        now: Callable[[], datetime] | None = None,
        remove_tree: Callable[[Path], None] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.enabled = enabled
        self.save_keyframes = save_keyframes
        self.save_json = save_json
        self.max_events_per_camera = max(1, int(max_events_per_camera))
        self.retention_days = max(0, int(retention_days))
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._remove_tree = remove_tree or _remove_tree

    def archive(
        self,
        evidence: EvidencePackage,
        selections: list[KeyframeSelection],
        semantics: EventSemantics | None,
        trusted_result: TrustedEventResult | None,
    ) -> ArchiveResult | None:
        if not self.enabled:
            return None
        camera = _safe_segment(evidence.camera_id)
        incident = _safe_segment(evidence.incident_id)
        directory = self._incident_directory(camera, incident)
        if directory is None:
            logger.warning("event_archive_rejected_unsafe_directory camera_id=%s incident_id=%s", camera, incident)
            return None
        directory.mkdir(parents=True, exist_ok=True)
        by_offset = {item.offset_ms: item for item in selections}
        keyframes = []
        saved_count = 0
        for keyframe in evidence.keyframes:
            selection = by_offset.get(keyframe.offset_ms)
            filename = _keyframe_filename(keyframe.offset_ms)
            if self.save_keyframes and selection is not None and selection.frame is not None:
                target = directory / "keyframes" / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                if cv2.imwrite(str(target), selection.frame.frame):
                    keyframe = keyframe.model_copy(update={"image_path": f"keyframes/{filename}"})
                    saved_count += 1
                else:
                    keyframe = keyframe.model_copy(update={"missing_reason": "image_encode_failed"})
            keyframes.append(keyframe)
        archived_evidence = evidence.model_copy(update={"keyframes": keyframes})
        if self.save_json:
            _write_json(directory / "evidence_package.json", archived_evidence.model_dump(mode="json"))
            if semantics is not None:
                _write_json(directory / "event_semantics.json", semantics.model_dump(mode="json"))
            if trusted_result is not None:
                _write_json(directory / "trusted_event_result.json", trusted_result.model_dump(mode="json"))
        timeline_image_path = None
        if self.save_keyframes:
            try:
                build_timeline_image(
                    archived_evidence.keyframes,
                    directory,
                    directory / "timeline" / "timeline.jpg",
                )
                timeline_image_path = "timeline/timeline.jpg"
            except Exception:
                timeline_image_path = None
        self._cleanup_camera(camera)
        return ArchiveResult(
            archive_path=f"{camera}/{incident}",
            summary={
                "archive_id": f"{camera}/{incident}",
                "keyframes_saved": saved_count,
                "keyframes_missing": sum(1 for item in archived_evidence.keyframes if item.missing_reason),
                "json_saved": self.save_json,
                "timeline_image_path": timeline_image_path,
            },
            evidence=archived_evidence,
        )

    def _cleanup_camera(self, camera: str) -> None:
        camera_dir = self._camera_directory(camera)
        if camera_dir is None or not camera_dir.exists():
            return
        try:
            directories = self._incident_directories(camera_dir)
        except OSError as exc:
            logger.warning("event_archive_cleanup_list_failed camera_id=%s error=%s", camera, exc)
            return
        if self.retention_days:
            cutoff = self._now() - timedelta(days=self.retention_days)
            for directory in directories:
                try:
                    modified_at = datetime.fromtimestamp(directory.stat().st_mtime, timezone.utc)
                except OSError as exc:
                    logger.warning("event_archive_cleanup_stat_failed camera_id=%s incident_id=%s error=%s", camera, directory.name, exc)
                    continue
                if modified_at < cutoff:
                    self._remove_incident_directory(camera, directory, "retention_expired")
        try:
            remaining = self._incident_directories(camera_dir)
        except OSError as exc:
            logger.warning("event_archive_cleanup_list_failed camera_id=%s error=%s", camera, exc)
            return
        for directory in remaining[self.max_events_per_camera:]:
            self._remove_incident_directory(camera, directory, "max_events_exceeded")

    def _camera_directory(self, camera: str) -> Path | None:
        candidate = (self.root_dir / camera).resolve()
        return candidate if _is_relative_to(candidate, self.root_dir) else None

    def _incident_directory(self, camera: str, incident: str) -> Path | None:
        camera_dir = self._camera_directory(camera)
        if camera_dir is None:
            return None
        candidate = (camera_dir / incident).resolve()
        return candidate if _is_relative_to(candidate, camera_dir) and _is_relative_to(candidate, self.root_dir) else None

    def _incident_directories(self, camera_dir: Path) -> list[Path]:
        return sorted(
            (item for item in camera_dir.iterdir() if item.is_dir() and not item.is_symlink() and _is_relative_to(item.resolve(), camera_dir)),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )

    def _remove_incident_directory(self, camera: str, directory: Path, reason: str) -> None:
        camera_dir = self._camera_directory(camera)
        if camera_dir is None or directory.is_symlink() or not _is_relative_to(directory.resolve(), camera_dir):
            logger.warning("event_archive_cleanup_skipped_unsafe camera_id=%s incident_id=%s reason=%s", camera, directory.name, reason)
            return
        try:
            self._remove_tree(directory)
            logger.info("event_archive_cleanup_deleted camera_id=%s incident_id=%s reason=%s", camera, directory.name, reason)
        except Exception as exc:
            # Archive governance is advisory and must never interrupt the event worker.
            logger.warning("event_archive_cleanup_failed camera_id=%s incident_id=%s reason=%s error=%s", camera, directory.name, reason, exc)

    def read_qwen_keyframe_images(
        self,
        archive_path: str,
        evidence: EvidencePackage,
        *,
        max_images: int,
        max_image_bytes: int,
    ) -> tuple[list[QwenImageInput], list[str]]:
        """Read only archive-owned relative keyframes for local model input.

        Paths stay inside this method and are never returned to the model, API,
        logs, or advisory file.
        """
        directory = self._directory_from_archive_path(archive_path)
        if directory is None:
            return [], ["archive_path_invalid"]
        images: list[QwenImageInput] = []
        missing: list[str] = []
        for keyframe in evidence.keyframes:
            if len(images) >= max(1, int(max_images)):
                break
            if keyframe.missing_reason:
                missing.append(keyframe.missing_reason)
                continue
            relative = _safe_keyframe_relative(keyframe.image_path)
            if relative is None:
                missing.append("keyframe_not_archived")
                continue
            candidate = (directory / relative).resolve()
            if not _is_relative_to(candidate, directory) or not _is_relative_to(candidate, self.root_dir):
                missing.append("keyframe_path_rejected")
                continue
            try:
                size = candidate.stat().st_size
                if size <= 0 or size > max(1024, int(max_image_bytes)):
                    missing.append("keyframe_size_rejected")
                    continue
                image_bytes = candidate.read_bytes()
            except OSError:
                missing.append("keyframe_read_failed")
                continue
            images.append(QwenImageInput(offset_ms=keyframe.offset_ms, role=keyframe.role, image_bytes=image_bytes))
        return images, list(dict.fromkeys(missing))

    def write_qwen_advisory(self, archive_path: str, advisory: QwenKeyframeAdvisory) -> bool:
        """Persist the structured local-model result without exposing its directory."""
        if not self.enabled or not self.save_json:
            return False
        directory = self._directory_from_archive_path(archive_path)
        if directory is None:
            logger.warning("qwen_advisory_archive_rejected")
            return False
        try:
            directory.mkdir(parents=True, exist_ok=True)
            _write_json(directory / "qwen_advisory.json", advisory.model_dump(mode="json"))
            return True
        except OSError as exc:
            logger.warning("qwen_advisory_archive_write_failed error=%s", exc)
            return False

    def _directory_from_archive_path(self, archive_path: str) -> Path | None:
        normalized = str(archive_path or "").replace("\\", "/")
        parts = normalized.split("/")
        if len(parts) != 2 or any(not part or part != _safe_segment(part) for part in parts):
            return None
        camera_dir = self._camera_directory(parts[0])
        if camera_dir is None:
            return None
        candidate = (camera_dir / parts[1]).resolve()
        return candidate if _is_relative_to(candidate, camera_dir) and _is_relative_to(candidate, self.root_dir) else None


def _safe_segment(value: str) -> str:
    return "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)[:120] or "unknown"


def _keyframe_filename(offset_ms: int) -> str:
    if offset_ms == 0:
        return "t0.jpg"
    sign = "plus" if offset_ms > 0 else "minus"
    return f"t_{sign}_{abs(offset_ms) // 1000}s.jpg"


def _safe_keyframe_relative(value: str | None) -> Path | None:
    if not value:
        return None
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized:
        return None
    parts = normalized.split("/")
    if len(parts) != 2 or parts[0] != "keyframes" or any(part in {"", ".", ".."} for part in parts):
        return None
    path = Path(*parts)
    return path if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} else None


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
