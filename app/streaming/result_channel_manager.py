from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

from fastapi import WebSocket

from app.core.logger import get_logger
from app.schemas.vision_result import VisionResult

logger = get_logger(__name__)


@dataclass(eq=False)
class ResultSubscriber:
    websocket: WebSocket
    camera_id: str | None


class ResultChannelManager:
    def __init__(self) -> None:
        self._subscribers: set[ResultSubscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    async def subscribe(self, websocket: WebSocket, camera_id: str | None) -> ResultSubscriber:
        await websocket.accept()
        subscriber = ResultSubscriber(websocket=websocket, camera_id=camera_id)
        with self._lock:
            self._subscribers.add(subscriber)
        logger.info("ws_result_subscribed camera_id=%s", camera_id)
        return subscriber

    def unsubscribe(self, subscriber: ResultSubscriber) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)
        logger.info("ws_result_unsubscribed camera_id=%s", subscriber.camera_id)

    def publish(self, result: VisionResult) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(result), self._loop)

    async def _broadcast(self, result: VisionResult) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        stale: list[ResultSubscriber] = []
        payload = result.model_dump()
        for subscriber in subscribers:
            if subscriber.camera_id and subscriber.camera_id != result.camera_id:
                continue
            try:
                await subscriber.websocket.send_json(payload)
            except Exception:
                stale.append(subscriber)
        for subscriber in stale:
            self.unsubscribe(subscriber)
