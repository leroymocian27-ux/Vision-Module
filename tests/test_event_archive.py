from __future__ import annotations

import json
import os
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from app.events.archive import EventArchive
from app.events.ring_frame_buffer import KeyframeSelection, RingFrame
from app.events.schemas import EvidenceKeyframe, EvidencePackage, FallEventRecord


class EventArchiveTest(unittest.TestCase):
    def _evidence(self) -> EvidencePackage:
        return EvidencePackage(
            incident_id="incident-archive", camera_id="camera_01", trigger_timestamp="2026-07-17T09:30:00+00:00",
            keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0), EvidenceKeyframe(role="post_check", offset_ms=5000, missing_reason="no_frame_near_target")],
        )

    def test_archives_keyframe_and_readable_json(self) -> None:
        with TemporaryDirectory() as directory:
            archive = EventArchive(directory, enabled=True)
            image = np.zeros((8, 8, 3), dtype=np.uint8)
            result = archive.archive(self._evidence(), [KeyframeSelection("trigger", 0, RingFrame("camera_01", 1, "2026-07-17T09:30:00+00:00", image))], None, None)
            self.assertIsNotNone(result)
            root = Path(directory) / result.archive_path
            self.assertTrue((root / "keyframes" / "t0.jpg").exists())
            self.assertEqual(result.summary["timeline_image_path"], "timeline/timeline.jpg")
            self.assertTrue((root / "timeline" / "timeline.jpg").exists())
            payload = json.loads((root / "evidence_package.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["keyframes"][0]["image_path"], "keyframes/t0.jpg")
            self.assertFalse(Path(payload["keyframes"][0]["image_path"]).is_absolute())
            self.assertEqual(payload["keyframes"][1]["missing_reason"], "no_frame_near_target")

    def test_disabled_archive_writes_nothing(self) -> None:
        with TemporaryDirectory() as directory:
            archive = EventArchive(directory, enabled=False)
            self.assertIsNone(archive.archive(self._evidence(), [], None, None))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cleanup_keeps_current_event_when_limit_is_one(self) -> None:
        with TemporaryDirectory() as directory:
            archive = EventArchive(directory, enabled=True, max_events_per_camera=1)
            image = np.zeros((8, 8, 3), dtype=np.uint8)
            first = archive.archive(
                self._evidence().model_copy(update={"incident_id": "incident-old"}),
                [KeyframeSelection("trigger", 0, RingFrame("camera_01", 1, "2026-07-17T09:30:00+00:00", image))],
                None,
                None,
            )
            time.sleep(0.02)
            second = archive.archive(
                self._evidence().model_copy(update={"incident_id": "incident-current"}),
                [KeyframeSelection("trigger", 0, RingFrame("camera_01", 2, "2026-07-17T09:31:00+00:00", image))],
                None,
                None,
            )

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertFalse((Path(directory) / first.archive_path).exists())
            self.assertTrue((Path(directory) / second.archive_path / "evidence_package.json").exists())

    def test_retention_cleanup_is_scoped_to_incident_directories(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = EventArchive(
                root,
                enabled=True,
                max_events_per_camera=10,
                retention_days=1,
                now=lambda: datetime(2026, 7, 18, tzinfo=timezone.utc),
            )
            image = np.zeros((8, 8, 3), dtype=np.uint8)
            old = archive.archive(
                self._evidence().model_copy(update={"incident_id": "incident-expired"}),
                [KeyframeSelection("trigger", 0, RingFrame("camera_01", 1, "2026-07-17T09:30:00+00:00", image))],
                None,
                None,
            )
            old_dir = root / old.archive_path
            old_time = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
            os.utime(old_dir, (old_time, old_time))
            sentinel = root / "outside_archive_sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            camera_sentinel = root / "camera_01" / "do_not_delete.txt"
            camera_sentinel.write_text("keep", encoding="utf-8")

            archive.archive(
                self._evidence().model_copy(update={"incident_id": "incident-current"}),
                [KeyframeSelection("trigger", 0, RingFrame("camera_01", 2, "2026-07-17T09:31:00+00:00", image))],
                None,
                None,
            )

            self.assertFalse(old_dir.exists())
            self.assertTrue(sentinel.exists())
            self.assertTrue(camera_sentinel.exists())

    def test_cleanup_failure_is_logged_and_does_not_fail_archive(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            image = np.zeros((8, 8, 3), dtype=np.uint8)

            def fail_remove(path: Path) -> None:
                raise OSError(f"cannot remove {path.name}")

            archive = EventArchive(root, enabled=True, max_events_per_camera=1, remove_tree=fail_remove)
            archive.archive(
                self._evidence().model_copy(update={"incident_id": "incident-old"}),
                [KeyframeSelection("trigger", 0, RingFrame("camera_01", 1, "2026-07-17T09:30:00+00:00", image))],
                None,
                None,
            )
            time.sleep(0.02)
            with self.assertLogs("app.events.archive", level="WARNING") as logs:
                current = archive.archive(
                    self._evidence().model_copy(update={"incident_id": "incident-current"}),
                    [KeyframeSelection("trigger", 0, RingFrame("camera_01", 2, "2026-07-17T09:31:00+00:00", image))],
                    None,
                    None,
                )

            self.assertIsNotNone(current)
            self.assertTrue(any("event_archive_cleanup_failed" in line for line in logs.output))
            self.assertTrue((root / "camera_01" / "incident-old").exists())
