from __future__ import annotations

import unittest

from app.events.incident_manager import IncidentManager


class IncidentManagerTest(unittest.TestCase):
    def test_reuses_incident_and_upgrades_candidate(self) -> None:
        now = [100.0]
        manager = IncidentManager(cooldown_window_seconds=30, monotonic_clock=lambda: now[0])
        candidate = manager.resolve(
            camera_id="camera_01",
            track_id=3,
            fall_state="fallen_candidate",
            risk_level="high",
            timestamp="2026-07-17T09:30:00+00:00",
        )
        now[0] += 2
        confirmed = manager.resolve(
            camera_id="camera_01",
            track_id=3,
            fall_state="fallen_confirmed",
            risk_level="critical",
            timestamp="2026-07-17T09:30:02+00:00",
        )

        self.assertTrue(candidate.created)
        self.assertFalse(confirmed.created)
        self.assertTrue(confirmed.upgraded)
        self.assertEqual(candidate.record.incident_id, confirmed.record.incident_id)
        self.assertEqual(confirmed.record.event_type, "fallen_confirmed")
        self.assertEqual(confirmed.record.risk_level, "critical")

    def test_creates_new_incident_after_window_expires(self) -> None:
        now = [100.0]
        manager = IncidentManager(cooldown_window_seconds=30, monotonic_clock=lambda: now[0])
        first = manager.resolve(
            camera_id="camera_01",
            track_id=3,
            fall_state="fallen_candidate",
            timestamp="2026-07-17T09:30:00+00:00",
        )
        now[0] += 31
        second = manager.resolve(
            camera_id="camera_01",
            track_id=3,
            fall_state="fallen_candidate",
            timestamp="2026-07-17T09:31:00+00:00",
        )

        self.assertNotEqual(first.record.incident_id, second.record.incident_id)
        self.assertTrue(second.created)
