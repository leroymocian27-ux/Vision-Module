from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


SUPPORTED_MODEL_LOG_KINDS = {"binary", "qwen"}


@dataclass(frozen=True)
class ModelLogEvent:
    seq: int
    emitted_at: str
    kind: str
    level: str
    message: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "emitted_at": self.emitted_at,
            "kind": self.kind,
            "level": self.level,
            "message": self.message,
            "fields": self.fields,
        }


class ModelLogBus:
    def __init__(self, *, max_events_per_kind: int = 500) -> None:
        self._max_events = max(10, int(max_events_per_kind))
        self._events: dict[str, deque[ModelLogEvent]] = defaultdict(lambda: deque(maxlen=self._max_events))
        self._next_seq = 1
        self._lock = threading.Lock()

    def publish(self, kind: str, message: str, *, level: str = "info", **fields: Any) -> ModelLogEvent:
        normalized = _normalize_kind(kind)
        with self._lock:
            event = ModelLogEvent(
                seq=self._next_seq,
                emitted_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                kind=normalized,
                level=str(level or "info").lower(),
                message=str(message),
                fields={key: value for key, value in fields.items() if value is not None},
            )
            self._next_seq += 1
            self._events[normalized].append(event)
            return event

    def snapshot(self, kind: str, *, limit: int = 100) -> list[dict[str, Any]]:
        normalized = _normalize_kind(kind)
        count = max(0, int(limit))
        with self._lock:
            events = list(self._events[normalized])
        if count:
            events = events[-count:]
        return [event.to_record() for event in events]

    def since(self, kind: str, after_seq: int) -> list[dict[str, Any]]:
        normalized = _normalize_kind(kind)
        with self._lock:
            events = [event for event in self._events[normalized] if event.seq > after_seq]
        return [event.to_record() for event in events]


def _normalize_kind(kind: str) -> str:
    normalized = str(kind or "").strip().lower()
    if normalized not in SUPPORTED_MODEL_LOG_KINDS:
        raise ValueError(f"unsupported model log kind: {kind}")
    return normalized


model_log_bus = ModelLogBus()
