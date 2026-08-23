from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

import requests
import websockets


FAILURE_ORDER = [
    "CAPTURE_FAILED",
    "PERSON_NOT_DETECTED",
    "TRACK_NOT_STABLE",
    "POSE_STALE",
    "TEMPORAL_NOT_CONFIRMED",
    "REPORTER_NOT_POSTED",
    "MAIN_SYSTEM_NOT_RECEIVED",
    "SNAPSHOT_NOT_REACHABLE",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end fall alert acceptance monitor.")
    parser.add_argument("--vision-base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--main-base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--wait-seconds", type=float, default=60)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    result = asyncio.run(_run(args))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return 0 if result["ok"] else 1


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    before_alarm_ids = _alarm_ids(args.main_base_url)
    observations: dict[str, Any] = {
        "started_at": started_at,
        "camera_connected": False,
        "frame_seq_growing": False,
        "person_detected": False,
        "track_stable": False,
        "pose_available": False,
        "temporal_window_ready": False,
        "confirmed_seen": False,
        "snapshot_url": None,
        "snapshot_url_reachable": False,
        "main_system_alarm_created": False,
        "main_system_alarm_id": None,
        "fall_state_timeline": [],
        "failure_stage": None,
    }

    status = _get_status(args.vision_base_url, args.camera_id)
    _merge_status_observations(observations, status)
    first_frame_seq = _frame_seq(status)
    track_counts: dict[str, int] = {}
    confirmed_incidents: set[str] = set()

    ws_url = _ws_url(args.vision_base_url, args.camera_id)
    deadline = time.monotonic() + args.wait_seconds
    try:
        async with websockets.connect(ws_url, ping_interval=None) as ws:
            while time.monotonic() < deadline:
                timeout = max(0.2, min(1.0, deadline - time.monotonic()))
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    await ws.send("ping")
                    status = _get_status(args.vision_base_url, args.camera_id)
                    _merge_status_observations(observations, status)
                    continue
                payload = json.loads(message)
                _observe_result(observations, payload, track_counts, confirmed_incidents)
                status = _get_status(args.vision_base_url, args.camera_id)
                _merge_status_observations(observations, status)
                observations["frame_seq_growing"] = observations["frame_seq_growing"] or (
                    first_frame_seq is not None and _frame_seq(status) is not None and _frame_seq(status) > first_frame_seq
                )
                _observe_reporter(observations, status)
                _observe_main_alarms(observations, args.main_base_url, before_alarm_ids, confirmed_incidents)
                if observations["main_system_alarm_created"] and observations["snapshot_url_reachable"]:
                    break
    except Exception as exc:
        observations["websocket_error"] = str(exc)

    status = _get_status(args.vision_base_url, args.camera_id)
    _merge_status_observations(observations, status)
    _observe_reporter(observations, status)
    _observe_main_alarms(observations, args.main_base_url, before_alarm_ids, confirmed_incidents)
    snapshot_url = observations.get("snapshot_url")
    if snapshot_url:
        observations["snapshot_url_reachable"] = _snapshot_reachable(str(snapshot_url))

    observations["ok"] = bool(
        observations["camera_connected"]
        and observations["frame_seq_growing"]
        and observations["person_detected"]
        and observations["track_stable"]
        and observations["temporal_window_ready"]
        and observations["confirmed_seen"]
        and observations["main_system_alarm_created"]
        and observations["snapshot_url_reachable"]
    )
    if not observations["ok"]:
        observations["failure_stage"] = _failure_stage(observations)
    observations["finished_at"] = datetime.now(timezone.utc).isoformat()
    return observations


def _get_status(base_url: str, camera_id: str) -> dict[str, Any]:
    try:
        response = requests.get(f"{base_url.rstrip('/')}/status", params={"camera_id": camera_id}, timeout=2.5)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc)}


def _merge_status_observations(observations: dict[str, Any], status: dict[str, Any]) -> None:
    cameras = status.get("cameras") if isinstance(status, dict) else None
    camera = cameras[0] if isinstance(cameras, list) and cameras else {}
    observations["camera_connected"] = observations["camera_connected"] or bool(camera.get("connected"))
    latest = status.get("latest_result") if isinstance(status, dict) else {}
    observations["person_detected"] = observations["person_detected"] or int(latest.get("latest_objects_count") or 0) > 0
    observations["track_stable"] = observations["track_stable"] or latest.get("track_id") is not None
    observations["pose_available"] = observations["pose_available"] or bool(latest.get("pose_available"))
    observations["temporal_window_ready"] = observations["temporal_window_ready"] or int(latest.get("temporal_window_size") or 0) >= 32
    state = latest.get("fall_state")
    if state:
        _append_state(observations, state, latest.get("risk_level"), latest.get("temporal_shadow_fall_probability"))
        observations["confirmed_seen"] = observations["confirmed_seen"] or state in {"fallen_confirmed", "confirmed_fall"}


def _observe_result(
    observations: dict[str, Any],
    payload: dict[str, Any],
    track_counts: dict[str, int],
    confirmed_incidents: set[str],
) -> None:
    objects = payload.get("objects") if isinstance(payload.get("objects"), list) else []
    people = [item for item in objects if isinstance(item, dict) and item.get("label") == "person"]
    observations["person_detected"] = observations["person_detected"] or bool(people)
    for person in people:
        track_id = person.get("track_id")
        if track_id is not None:
            key = str(track_id)
            track_counts[key] = track_counts.get(key, 0) + 1
            observations["track_stable"] = observations["track_stable"] or track_counts[key] >= 5
        observations["pose_available"] = observations["pose_available"] or isinstance(person.get("pose"), dict)
        temporal = person.get("temporal") if isinstance(person.get("temporal"), dict) else {}
        observations["temporal_window_ready"] = observations["temporal_window_ready"] or bool(temporal.get("window_ready"))
        decision = person.get("fall_decision") if isinstance(person.get("fall_decision"), dict) else {}
        alarm = person.get("alarm_preview") if isinstance(person.get("alarm_preview"), dict) else {}
        state = decision.get("fall_state")
        if state:
            _append_state(observations, state, alarm.get("risk_level") or decision.get("risk_level"), temporal.get("fall_probability"))
        if state in {"fallen_confirmed", "confirmed_fall"} or alarm.get("confirmed") is True:
            observations["confirmed_seen"] = True
            incident = f"{payload.get('camera_id')}:{track_id}:{payload.get('frame_seq')}"
            confirmed_incidents.add(incident)


def _observe_reporter(observations: dict[str, Any], status: dict[str, Any]) -> None:
    reporter = status.get("fall_event_reporter") if isinstance(status, dict) else {}
    if not isinstance(reporter, dict):
        return
    post_status = str(reporter.get("last_post_status") or "")
    if post_status.startswith("http_2"):
        observations["reporter_posted"] = True
    snapshot_url = reporter.get("last_snapshot_url")
    if isinstance(snapshot_url, str) and snapshot_url:
        observations["snapshot_url"] = snapshot_url
        observations["snapshot_url_reachable"] = observations["snapshot_url_reachable"] or _snapshot_reachable(snapshot_url)


def _observe_main_alarms(
    observations: dict[str, Any],
    main_base_url: str,
    before_alarm_ids: set[str],
    confirmed_incidents: set[str],
) -> None:
    del confirmed_incidents
    try:
        response = requests.get(f"{main_base_url.rstrip('/')}/alarms", params={"limit": 10}, timeout=2.5)
        response.raise_for_status()
        alarms = _alarm_items(response.json())
    except Exception as exc:
        observations["main_system_error"] = str(exc)
        return
    for alarm in alarms:
        alarm_id = str(alarm.get("id") or "")
        if alarm_id and alarm_id not in before_alarm_ids and alarm.get("alarm_type") in {"fall_detected", "fall_injury_risk"}:
            observations["main_system_alarm_created"] = True
            observations["main_system_alarm_id"] = alarm_id
            event = ((alarm.get("metadata") or {}).get("event") or {})
            snapshot_url = event.get("snapshot_url") or event.get("snapshot_path") or (alarm.get("metadata") or {}).get("snapshot_url")
            if isinstance(snapshot_url, str) and snapshot_url:
                observations["snapshot_url"] = snapshot_url
                observations["snapshot_url_reachable"] = observations["snapshot_url_reachable"] or _snapshot_reachable(snapshot_url)
            return


def _alarm_ids(main_base_url: str) -> set[str]:
    try:
        response = requests.get(f"{main_base_url.rstrip('/')}/alarms", params={"limit": 50}, timeout=2.5)
        response.raise_for_status()
        return {str(item.get("id")) for item in _alarm_items(response.json()) if item.get("id")}
    except Exception:
        return set()


def _alarm_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        value = payload.get("value")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _snapshot_reachable(url: str) -> bool:
    try:
        response = requests.get(url, timeout=2.5)
        return response.status_code < 400 and "image" in response.headers.get("content-type", "").lower()
    except Exception:
        return False


def _frame_seq(status: dict[str, Any]) -> int | None:
    cameras = status.get("cameras") if isinstance(status, dict) else None
    camera = cameras[0] if isinstance(cameras, list) and cameras else {}
    value = camera.get("frame_seq")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _append_state(observations: dict[str, Any], state: str, risk: Any, probability: Any) -> None:
    timeline = observations["fall_state_timeline"]
    item = {"state": state, "risk": risk, "probability": probability, "at": datetime.now(timezone.utc).isoformat()}
    if not timeline or timeline[-1].get("state") != state:
        timeline.append(item)
        observations["fall_state_timeline"] = timeline[-20:]


def _failure_stage(observations: dict[str, Any]) -> str:
    checks = {
        "CAPTURE_FAILED": observations["camera_connected"] and observations["frame_seq_growing"],
        "PERSON_NOT_DETECTED": observations["person_detected"],
        "TRACK_NOT_STABLE": observations["track_stable"],
        "POSE_STALE": observations["pose_available"],
        "TEMPORAL_NOT_CONFIRMED": observations["temporal_window_ready"] and observations["confirmed_seen"],
        "REPORTER_NOT_POSTED": observations.get("reporter_posted") is True,
        "MAIN_SYSTEM_NOT_RECEIVED": observations["main_system_alarm_created"],
        "SNAPSHOT_NOT_REACHABLE": observations["snapshot_url_reachable"],
    }
    for stage in FAILURE_ORDER:
        if not checks[stage]:
            return stage
    return "UNKNOWN"


def _ws_url(base_url: str, camera_id: str) -> str:
    if base_url.startswith("https://"):
        prefix = "wss://"
        rest = base_url[len("https://") :]
    elif base_url.startswith("http://"):
        prefix = "ws://"
        rest = base_url[len("http://") :]
    else:
        prefix = "ws://"
        rest = base_url
    return f"{prefix}{rest.rstrip('/')}/ws/results?camera_id={camera_id}"


if __name__ == "__main__":
    raise SystemExit(main())
