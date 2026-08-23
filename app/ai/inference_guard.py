from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


_ULTRALYTICS_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_CURRENT_OWNER: str | None = None


@contextmanager
def ultralytics_inference_lock(
    blocking: bool = True,
    owner: str | None = None,
    timeout: float | None = None,
) -> Iterator[bool]:
    global _CURRENT_OWNER
    if timeout is not None and blocking:
        acquired = _ULTRALYTICS_LOCK.acquire(timeout=max(0.0, timeout))
    else:
        acquired = _ULTRALYTICS_LOCK.acquire(blocking=blocking)
    if acquired:
        with _STATE_LOCK:
            _CURRENT_OWNER = owner or "unknown"
    try:
        yield acquired
    finally:
        if acquired:
            with _STATE_LOCK:
                _ULTRALYTICS_LOCK.release()
                _CURRENT_OWNER = None


def current_ultralytics_inference_owner() -> str | None:
    with _STATE_LOCK:
        return _CURRENT_OWNER
