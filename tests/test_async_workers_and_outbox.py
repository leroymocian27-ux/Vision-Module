from __future__ import annotations

import time
import unittest
from dataclasses import replace
from tempfile import TemporaryDirectory
from pathlib import Path

from app.core.config import Settings
from app.detection.realtime_result_store import DetectionSnapshot, ObjectSnapshot, RealtimeResultStore
from app.schemas.vision_result import DetectedObject, VisionResult
from app.services.alert_outbox_service import AlertOutboxService
from app.services.fusion_worker_service import FusionWorkerService
from app.services.temporal_worker_service import TemporalWorkerService


class _TemporalStub:
    def enrich(self, camera_id: str, objects: list[DetectedObject]) -> list[DetectedObject]:
        return [
            item.model_copy(
                update={
                    "temporal": {"source": "stub", "camera_id": camera_id},
                    "fall_decision": {"fall_state": "normal", "source": "stub"},
                    "alarm_preview": {"confirmed": False, "source": "stub"},
                }
            )
            for item in objects
        ]


class _ResultBuilderStub:
    def __init__(self) -> None:
        self.calls = 0

    def build_result_snapshot(self, camera_id: str) -> VisionResult:
        self.calls += 1
        return VisionResult(
            camera_id=camera_id,
            timestamp="2026-07-08T00:00:00Z",
            frame_seq=self.calls,
            frame_width=640,
            frame_height=360,
            objects=[],
            detector={"name": "stub"},
        )


class AsyncWorkersAndOutboxTest(unittest.TestCase):
    def test_temporal_worker_tick_writes_temporal_snapshot(self) -> None:
        settings = replace(
            Settings(),
            enable_temporal=True,
            temporal_worker_enabled=True,
            temporal_model_provider="mock",
        )
        store = RealtimeResultStore()
        worker = TemporalWorkerService(settings, store, _TemporalStub())  # type: ignore[arg-type]
        now = time.monotonic()
        store.update_tracking(
            ObjectSnapshot(
                camera_id="camera_01",
                frame_seq=4,
                frame_width=640,
                frame_height=360,
                timestamp="2026-07-08T00:00:00Z",
                monotonic_at=now,
                objects=[
                    DetectedObject(
                        label="person",
                        confidence=0.9,
                        bbox=[10.0, 20.0, 110.0, 220.0],
                        track_id=1,
                    )
                ],
            )
        )

        worker._tick("camera_01")  # type: ignore[attr-defined]

        snapshot = store.latest_temporal("camera_01")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.frame_seq, 4)
        self.assertEqual(snapshot.objects[0].temporal["source"], "stub")
        self.assertIsNotNone(worker.status("camera_01").result_age_ms)

    def test_fusion_worker_tick_writes_fused_result(self) -> None:
        settings = replace(Settings(), fusion_worker_enabled=True)
        store = RealtimeResultStore()
        builder = _ResultBuilderStub()
        worker = FusionWorkerService(settings, store, builder)  # type: ignore[arg-type]

        worker._tick("camera_01")  # type: ignore[attr-defined]

        result = store.latest_fused("camera_01")
        self.assertIsNotNone(result)
        self.assertEqual(result.camera_id, "camera_01")
        self.assertIn("_monotonic_at", result.detector)
        self.assertIsNotNone(worker.status("camera_01").result_age_ms)

    def test_alert_outbox_records_pending_and_result(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = replace(
                Settings(),
                alert_outbox_enabled=True,
                alert_outbox_path=str(Path(temp_dir) / "outbox.sqlite3"),
            )
            outbox = AlertOutboxService(settings)
            payload = {
                "incident_id": "incident-1",
                "camera_id": "camera_01",
                "track_id": 7,
                "event_type": "fall_confirmed",
            }

            outbox.record_pending(payload)
            pending_status = outbox.status()
            self.assertEqual(pending_status.pending_count, 1)

            outbox.record_result(payload, "request_error", "timeout")
            failed_status = outbox.status()
            self.assertEqual(failed_status.retry_wait_count, 1)
            self.assertEqual(failed_status.last_status, "retry_wait")

    def test_alert_outbox_records_result_without_existing_pending_row(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = replace(
                Settings(),
                alert_outbox_enabled=True,
                alert_outbox_path=str(Path(temp_dir) / "outbox.sqlite3"),
                main_system_retry_backoff_seconds="0",
            )
            outbox = AlertOutboxService(settings)
            payload = {"event_id": "manual-1", "camera_id": "camera_01", "track_id": "manual"}

            outbox.record_result(payload, "request_error", "timeout")

            status = outbox.status()
            self.assertEqual(status.retry_wait_count, 1)
            pending_payloads = outbox.pending_payloads()
            self.assertEqual(len(pending_payloads), 1)
            self.assertEqual(pending_payloads[0]["event_id"], "manual-1")

    def test_alert_outbox_manual_retry_can_include_failed_records(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = replace(
                Settings(),
                alert_outbox_enabled=True,
                alert_outbox_path=str(Path(temp_dir) / "outbox.sqlite3"),
                alert_outbox_retry_limit=1,
            )
            outbox = AlertOutboxService(settings)
            payload = {"event_id": "event-1", "camera_id": "camera_01"}

            outbox.record_pending(payload)
            outbox.record_result(payload, "request_error", "timeout")

            self.assertEqual(outbox.status().failed_count, 1)
            self.assertEqual(outbox.pending_payloads(), [])
            retry_payloads = outbox.pending_payloads(include_failed=True)
            self.assertEqual(len(retry_payloads), 1)
            self.assertEqual(retry_payloads[0]["event_id"], "event-1")


if __name__ == "__main__":
    unittest.main()
