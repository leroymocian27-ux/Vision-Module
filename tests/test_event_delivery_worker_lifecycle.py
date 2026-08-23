from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import event_api
from app.core.config import Settings
from app.core.runtime import Runtime
import app.events.delivery as delivery_module
from app.events.delivery import DeliveryOutbox
from app.events.delivery_worker import DeliveryWorker
from app.events.pipeline import EventPipelineService


class EventDeliveryWorkerLifecycleTest(unittest.TestCase):
    def test_default_and_single_switch_configs_do_not_start_worker(self) -> None:
        for settings in (
            Settings(),
            replace(Settings(), event_delivery_enabled=True, event_delivery_worker_enabled=False),
            replace(Settings(), event_delivery_enabled=False, event_delivery_worker_enabled=True),
        ):
            with self.subTest(settings=settings):
                outbox = DeliveryOutbox(settings)
                worker = DeliveryWorker(settings, outbox)
                worker.start()
                self.assertFalse(worker.enabled)
                self.assertFalse(worker.status()["running"])

    def test_worker_starts_and_stops_when_both_switches_enabled(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True, event_delivery_worker_enabled=True)
        worker = DeliveryWorker(settings, DeliveryOutbox(settings))

        worker.start()
        try:
            self.assertTrue(worker.enabled)
            self.assertTrue(worker.status()["running"])
        finally:
            worker.stop()

        self.assertFalse(worker.status()["running"])

    def test_runtime_shutdown_stops_delivery_worker_before_event_pipeline(self) -> None:
        calls: list[str] = []
        settings = Settings()
        runtime = Runtime(
            settings=settings,
            source_manager=_StopAll("source_manager", calls),
            realtime_store=object(),
            result_store=object(),
            result_channels=object(),
            tracking_service=object(),
            identity_service=object(),
            identity_binding_service=object(),
            identity_binding_worker_service=_StopAll("identity_binding_worker", calls),
            pose_service=object(),
            behavior_service=object(),
            temporal_service=object(),
            fall_event_reporter=_Stop("fall_event_reporter", calls),
            alert_simulator_service=_Stop("alert_simulator", calls),
            detection_service=_StopAll("detection", calls),
            tracking_worker_service=_StopAll("tracking_worker", calls),
            pose_worker_service=_StopAll("pose_worker", calls),
            result_publisher_service=_StopAll("result_publisher", calls),
            stream_service=object(),
            peer_manager=_AsyncClose("peer_manager", calls),
            status_service=object(),
            event_pipeline=_Stop("event_pipeline", calls),
            event_delivery_worker=_Stop("event_delivery_worker", calls),
        )

        asyncio.run(runtime.shutdown())

        self.assertLess(calls.index("event_delivery_worker"), calls.index("event_pipeline"))

    def test_status_api_reports_worker_running(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True, event_delivery_worker_enabled=True)
        pipeline = EventPipelineService(settings)
        worker = SimpleNamespace(status=lambda: {"running": True})
        app = FastAPI()
        app.state.runtime = SimpleNamespace(settings=settings, event_pipeline=pipeline, event_delivery_worker=worker)
        app.include_router(event_api.router)

        with TestClient(app) as client:
            response = client.get("/events/delivery/status")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["worker_running"])

    def test_dry_run_worker_does_not_post(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True, event_delivery_worker_enabled=True, event_delivery_mode="dry_run")
        outbox = DeliveryOutbox(settings)
        worker = DeliveryWorker(settings, outbox)
        calls: list[dict] = []

        def fake_post(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            raise AssertionError("dry-run worker must not POST")

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            self.assertIsNone(worker.process_once("worker-a"))
        finally:
            delivery_module.requests.post = previous_post

        self.assertEqual(calls, [])


class _Stop:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    def stop(self) -> None:
        self.calls.append(self.name)


class _StopAll:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    def stop_all(self) -> None:
        self.calls.append(self.name)


class _AsyncClose:
    def __init__(self, name: str, calls: list[str]) -> None:
        self.name = name
        self.calls = calls

    async def close_all(self) -> None:
        self.calls.append(self.name)


if __name__ == "__main__":
    unittest.main()
