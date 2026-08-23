from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.events.outbox import SQLiteEventOutbox
from app.events.delivery import DeliveryOutbox
from app.core.config import Settings


class DemoSeedEventPipelineTest(unittest.TestCase):
    def test_seed_script_creates_frontend_readable_event_without_posting(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "event_outbox.sqlite3"
            archive_dir = root / "archive"
            command = [
                sys.executable,
                "scripts/seed_event_pipeline_demo.py",
                "--db",
                str(db_path),
                "--archive-dir",
                str(archive_dir),
                "--camera-id",
                "camera_01",
                "--incident-id",
                "demo-seed-test",
            ]

            completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)

            self.assertIn("dev/demo only: no main-system POST was sent", completed.stdout)
            record = SQLiteEventOutbox(db_path).get_event("demo-seed-test")
            self.assertIsNotNone(record)
            self.assertEqual(record.status, "delivery_pending")
            self.assertIsNotNone(record.evidence_package)
            self.assertIsNotNone(record.event_semantics)
            self.assertIsNotNone(record.trusted_result)
            self.assertTrue((archive_dir / "camera_01" / "demo-seed-test" / "evidence_package.json").exists())
            self.assertTrue((archive_dir / "camera_01" / "demo-seed-test" / "keyframes" / "t0.jpg").exists())
            self.assertTrue((archive_dir / "camera_01" / "demo-seed-test" / "timeline" / "timeline.jpg").exists())

    def test_all_demo_seed_scenarios_create_records(self) -> None:
        scenarios = [
            "fall_candidate_support",
            "fallen_confirmed_high",
            "adl_suppressed_review",
            "missing_keyframes",
            "vlm_timeout_fallback",
            "vlm_invalid_json_fallback",
        ]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "event_outbox.sqlite3"
            archive_dir = root / "archive"
            for scenario in scenarios:
                incident_id = f"demo-{scenario}"
                command = [
                    sys.executable,
                    "scripts/seed_event_pipeline_demo.py",
                    "--db",
                    str(db_path),
                    "--archive-dir",
                    str(archive_dir),
                    "--incident-id",
                    incident_id,
                    "--scenario",
                    scenario,
                ]
                subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
                record = SQLiteEventOutbox(db_path).get_event(incident_id)
                self.assertIsNotNone(record)
                self.assertEqual(record.status, "delivery_pending")
                if scenario == "missing_keyframes":
                    self.assertIn("missing_demo_keyframes", record.trusted_result.degradation_used)
                if scenario == "vlm_timeout_fallback":
                    self.assertIn("vlm_timeout", record.trusted_result.degradation_used)
                if scenario == "vlm_invalid_json_fallback":
                    self.assertIn("vlm_invalid_json", record.trusted_result.degradation_used)

    def test_dry_run_does_not_write_db(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "event_outbox.sqlite3"
            command = [
                sys.executable,
                "scripts/seed_event_pipeline_demo.py",
                "--db",
                str(db_path),
                "--archive-dir",
                str(Path(directory) / "archive"),
                "--dry-run",
            ]

            completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)

            self.assertIn("dry-run", completed.stdout)
            self.assertFalse(db_path.exists())

    def test_seed_script_can_create_delivery_dry_run_record_for_service_acceptance(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "event_outbox.sqlite3"
            delivery_db = root / "event_delivery_outbox.sqlite3"
            command = [
                sys.executable,
                "scripts/seed_event_pipeline_demo.py",
                "--db",
                str(db_path),
                "--delivery-db",
                str(delivery_db),
                "--archive-dir",
                str(root / "archive"),
                "--camera-id",
                "camera_01",
                "--incident-id",
                "demo-delivery-seed",
                "--seed-delivery-dry-run",
            ]

            completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)

            self.assertIn("delivery_status=dry_run_sent", completed.stdout)
            record = DeliveryOutbox(
                Settings(event_delivery_backend="sqlite", event_delivery_sqlite_path=str(delivery_db))
            ).for_incident("demo-delivery-seed")
            self.assertIsNotNone(record)
            self.assertEqual(record.delivery_status, "dry_run_sent")
            self.assertEqual(record.delivery_mode, "dry_run")
            self.assertTrue(record.dry_run)

    def test_clear_demo_keeps_non_demo_records(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "event_outbox.sqlite3"
            archive_dir = root / "archive"
            base_command = [
                sys.executable,
                "scripts/seed_event_pipeline_demo.py",
                "--db",
                str(db_path),
                "--archive-dir",
                str(archive_dir),
                "--incident-id",
                "demo-clear-me",
            ]
            subprocess.run(base_command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
            outbox = SQLiteEventOutbox(db_path)
            non_demo = outbox.add_event(record := outbox.get_event("demo-clear-me").event.model_copy(update={"incident_id": "real-incident"}))
            self.assertEqual(non_demo.incident_id, "real-incident")

            clear_command = base_command + ["--clear-demo", "--incident-id", "demo-after-clear"]
            subprocess.run(clear_command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)

            reopened = SQLiteEventOutbox(db_path)
            self.assertIsNone(reopened.get_event("demo-clear-me"))
            self.assertIsNotNone(reopened.get_event("demo-after-clear"))
            self.assertIsNotNone(reopened.get_event("real-incident"))


if __name__ == "__main__":
    unittest.main()
