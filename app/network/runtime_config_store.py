from __future__ import annotations

import copy
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DEVICE_CONFIG: dict[str, Any] = {
    "network": {
        "subnet": "",
        "local_ip": "",
        "interface_name": "",
    },
    "main_system": {
        "ip": "",
        "port": None,
        "base_url": "",
        "websocket_url": "",
        "last_success_at": "",
        "status": "unknown",
    },
    "camera": {
        "ip": "",
        "rtsp_port": 10554,
        "http_port": None,
        "rtsp_url": "",
        "stream_profile": "",
        "last_success_at": "",
        "status": "unknown",
    },
    "discovery": {
        "candidate_host_start": 248,
        "candidate_host_end": 255,
        "connect_timeout_ms": 500,
        "scan_timeout_ms": 5000,
        "last_scan_at": "",
        "status": "unknown",
        "last_error": None,
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class RuntimeDeviceConfigStore:
    """Small JSON store with atomic writes and corrupt-file recovery."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            return self._load_unlocked()

    def save(self, config: dict[str, Any]) -> None:
        with self._lock:
            self._save_unlocked(config)

    def update(self, config: dict[str, Any]) -> dict[str, Any]:
        merged = self._merge_defaults(config)
        self.save(merged)
        return merged

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            config = self._default()
            self._save_unlocked(config)
            return config
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._backup_corrupt_unlocked()
            config = self._default()
            config["discovery"]["status"] = "recovered_default"
            config["discovery"]["last_error"] = "runtime_device_config_corrupt"
            self._save_unlocked(config)
            return config
        if not isinstance(raw, dict):
            self._backup_corrupt_unlocked()
            config = self._default()
            config["discovery"]["status"] = "recovered_default"
            config["discovery"]["last_error"] = "runtime_device_config_invalid"
            self._save_unlocked(config)
            return config
        return self._merge_defaults(raw)

    def _save_unlocked(self, config: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f"{self.path.name}.tmp")
        payload = json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, self.path)

    def _backup_corrupt_unlocked(self) -> None:
        if not self.path.exists():
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup = self.path.with_name(f"{self.path.name}.corrupt-{timestamp}")
        try:
            os.replace(self.path, backup)
        except OSError:
            pass

    @staticmethod
    def _default() -> dict[str, Any]:
        return copy.deepcopy(DEFAULT_DEVICE_CONFIG)

    @classmethod
    def _merge_defaults(cls, raw: dict[str, Any]) -> dict[str, Any]:
        config = cls._default()
        for section, values in raw.items():
            if isinstance(values, dict) and isinstance(config.get(section), dict):
                config[section].update(values)
            else:
                config[section] = values
        return config
