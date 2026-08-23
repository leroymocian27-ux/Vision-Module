from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from typing import Any

import requests


def _get_json(url: str, *, timeout: float = 3.0) -> Any | None:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return payload
    except Exception:
        return None


def _snapshot_reachable(url: str | None) -> bool:
    if not url:
        return False
    try:
        response = requests.get(url, timeout=3)
        return response.status_code < 400 and "image" in response.headers.get("content-type", "").lower()
    except Exception:
        return False


def _alarm_items(payload: Any | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("value"), list):
        return [item for item in payload["value"] if isinstance(item, dict)]
    if isinstance(payload.get("items"), list):
        return [item for item in payload["items"] if isinstance(item, dict)]
    if isinstance(payload.get("alarms"), list):
        return [item for item in payload["alarms"] if isinstance(item, dict)]
    if isinstance(payload.get("data"), list):
        return [item for item in payload["data"] if isinstance(item, dict)]
    return []


def _latest_alarms(main_base: str) -> list[dict[str, Any]]:
    payload = _get_json(f"{main_base.rstrip('/')}/alarms?active_only=true&limit=50")
    return _alarm_items(payload)


def _latest_alarm_count(main_base: str) -> int:
    payload = _get_json(f"{main_base.rstrip('/')}/alarms?active_only=true&limit=50")
    if not payload:
        return 0
    if isinstance(payload, list):
        return len(_alarm_items(payload))
    if isinstance(payload, dict) and isinstance(payload.get("Count"), int):
        return int(payload["Count"])
    return len(_alarm_items(payload))


def _alarm_ids(alarms: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("id")) for item in alarms if item.get("id")}


def _fall_alarm_created_after(main_base: str, before_ids: set[str], incident_id: str | None) -> tuple[bool, str | None]:
    for alarm in _latest_alarms(main_base):
        alarm_id = str(alarm.get("id") or "")
        metadata = alarm.get("metadata") if isinstance(alarm.get("metadata"), dict) else {}
        event = metadata.get("event") if isinstance(metadata.get("event"), dict) else {}
        alarm_type = str(alarm.get("alarm_type") or alarm.get("type") or "").lower()
        event_incident = str(event.get("incident_id") or metadata.get("incident_id") or "")
        is_fall = alarm_type in {"fall_detected", "fall_injury_risk", "video_fall"} or event.get("event_type") == "fall_confirmed"
        if is_fall and alarm_id and alarm_id not in before_ids:
            return True, alarm_id
        if incident_id and is_fall and event_incident == incident_id:
            return True, alarm_id or None
    return False, None


def monitor(args: argparse.Namespace) -> dict[str, Any]:
    vision = args.vision_base.rstrip("/")
    main = args.main_base.rstrip("/")
    before_alarms = _latest_alarms(main)
    before_alarm_ids = _alarm_ids(before_alarms)
    started_alarm_count = len(before_alarms)
    started_at = time.monotonic()
    samples = 0
    counters: Counter[str] = Counter()
    frame_first: int | None = None
    frame_last: int | None = None
    last_status: dict[str, Any] = {}
    last_latest: dict[str, Any] = {}
    last_reporter: dict[str, Any] = {}

    while time.monotonic() - started_at < args.seconds:
        status = _get_json(f"{vision}/status?camera_id={args.camera_id}") or {}
        latest = _get_json(f"{vision}/integration/results/{args.camera_id}/latest") or {}
        samples += 1
        last_status = status
        last_latest = latest

        camera = (status.get("cameras") or [{}])[0]
        frame_seq = int(camera.get("frame_seq") or latest.get("frame_seq") or 0)
        if frame_first is None:
            frame_first = frame_seq
        frame_last = frame_seq
        if camera.get("connected") and str(camera.get("stream_state")) == "connected":
            counters["camera_connected"] += 1
        if (camera.get("capture_fps") or 0) >= args.min_capture_fps:
            counters["capture_fps_ok"] += 1

        detection = (status.get("detection") or [{}])[0]
        if (detection.get("latest_raw_person_count") or 0) > 0:
            counters["person_detected"] += 1
        if (detection.get("latest_fall_model_count") or 0) > 0:
            counters["fall_model_detected"] += 1

        objects = latest.get("objects") or []
        if objects:
            counters["published_objects"] += 1
        if any(item.get("track_id") is not None for item in objects if isinstance(item, dict)):
            counters["track_stable"] += 1
        if any(item.get("pose") for item in objects if isinstance(item, dict)):
            counters["pose_valid"] += 1
        if any(((item.get("fall_decision") or {}).get("fall_state") in {"fallen_confirmed", "confirmed_fall"}) for item in objects if isinstance(item, dict)):
            counters["temporal_confirmed_seen"] += 1

        reporter = status.get("fall_event_reporter") or {}
        last_reporter = reporter
        post_status = str(reporter.get("last_post_status") or "")
        if post_status:
            counters["reporter_post_seen"] += 1
        if post_status.startswith("http_20"):
            counters["reporter_post_success"] += 1
        if _snapshot_reachable(reporter.get("last_snapshot_url")):
            counters["snapshot_url_reachable"] += 1
        time.sleep(args.interval)

    final_alarm_count = _latest_alarm_count(main)
    frame_growing = frame_first is not None and frame_last is not None and frame_last > frame_first
    last_incident_id = str(last_reporter.get("last_incident_id") or "") if isinstance(last_reporter, dict) else ""
    main_alarm_created, main_alarm_id = _fall_alarm_created_after(main, before_alarm_ids, last_incident_id or None)
    if not main_alarm_created:
        main_alarm_created = final_alarm_count > started_alarm_count
        main_alarm_id = None
    ratios = {key: round(value / max(samples, 1), 4) for key, value in counters.items()}
    failure = "PASSED"
    if not ratios.get("camera_connected"):
        failure = "CAPTURE_FAILED"
    elif not frame_growing:
        failure = "FRAME_NOT_GROWING"
    elif not (ratios.get("person_detected", 0) or ratios.get("fall_model_detected", 0)):
        failure = "PERSON_NOT_DETECTED"
    elif not ratios.get("published_objects", 0):
        failure = "TRACK_NOT_STABLE"
    elif not ratios.get("temporal_confirmed_seen", 0):
        failure = "TEMPORAL_NOT_CONFIRMED"
    elif not ratios.get("reporter_post_seen", 0):
        failure = "REPORTER_NOT_POSTED"
    elif not ratios.get("reporter_post_success", 0):
        failure = "MAIN_FILTER_REJECTED"
    elif not ratios.get("snapshot_url_reachable", 0):
        failure = "SNAPSHOT_NOT_REACHABLE"
    elif not main_alarm_created:
        failure = "MAIN_ALARM_NOT_BROADCAST"

    return {
        "samples": samples,
        "duration_seconds": args.seconds,
        "frame_seq_first": frame_first,
        "frame_seq_last": frame_last,
        "frame_seq_growing": frame_growing,
        "ratios": ratios,
        "main_alarm_count_before": started_alarm_count,
        "main_alarm_count_after": final_alarm_count,
        "main_alarm_created": main_alarm_created,
        "main_alarm_id": main_alarm_id,
        "last_reporter": last_reporter,
        "last_detection": (last_status.get("detection") or [{}])[0],
        "last_pose": last_status.get("pose") or {},
        "last_latest_objects_count": len(last_latest.get("objects") or []),
        "failure_stage": failure,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor real fall-alert linkage across vision_service and health-main.")
    parser.add_argument("--vision-base", default=os.getenv("VISION_BASE_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--main-base", default=os.getenv("MAIN_SYSTEM_BASE_URL", "http://127.0.0.1:8000/api/v1"))
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--min-capture-fps", type=float, default=8.0)
    args = parser.parse_args()
    print(json.dumps(monitor(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
