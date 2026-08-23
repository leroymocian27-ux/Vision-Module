from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


POSE_COUNTER_FIELDS = [
    "worker_tick_count",
    "inference_attempt_count",
    "inference_success_count",
    "pose_target_object_count",
    "pose_attached_object_count",
    "skipped_due_to_busy",
]

BLOCKING_STALE_REASONS = (
    "pose_frame_stale",
    "pose_frame_stale_detection_lag",
    "pose_frame_stale_capture_stale",
    "pose_frame_stale_capture_disconnected",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe live /status pose diagnostics for runtime A/B profiles.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--profile-name", default="manual")
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--output", default="evaluations/pose_runtime_status_probe_20260705.json")
    args = parser.parse_args()

    samples = collect_samples(
        base_url=args.base_url,
        camera_id=args.camera_id,
        duration_seconds=args.duration_seconds,
        interval_seconds=args.interval_seconds,
    )
    report = summarize_samples(
        samples,
        profile_name=args.profile_name,
        camera_id=args.camera_id,
        base_url=args.base_url,
        duration_seconds=args.duration_seconds,
        interval_seconds=args.interval_seconds,
    )
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


def collect_samples(
    *,
    base_url: str,
    camera_id: str,
    duration_seconds: float,
    interval_seconds: float,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + max(0.0, duration_seconds)
    interval = max(0.1, interval_seconds)
    while True:
        started = time.monotonic()
        sample = {
            "sampled_at": datetime.now(timezone.utc).isoformat(),
            "ok": False,
            "error": None,
            "status": None,
        }
        try:
            sample["status"] = fetch_status(base_url=base_url, camera_id=camera_id)
            sample["ok"] = True
        except Exception as exc:
            sample["error"] = str(exc)
        samples.append(sample)
        if time.monotonic() >= deadline:
            break
        sleep_for = interval - (time.monotonic() - started)
        if sleep_for > 0:
            time.sleep(sleep_for)
    return samples


def fetch_status(*, base_url: str, camera_id: str) -> dict[str, Any]:
    attempts = status_url_candidates(base_url=base_url, camera_id=camera_id)
    last_error: RuntimeError | None = None
    for url in attempts:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"HTTP {exc.code} from {url}: {body}")
            if exc.code != 404:
                raise last_error from exc
        except Exception as exc:
            raise RuntimeError(f"{exc} (url={url})") from exc
    assert last_error is not None
    raise last_error


def status_url_candidates(*, base_url: str, camera_id: str) -> list[str]:
    query = urllib.parse.urlencode({"camera_id": camera_id})
    base = base_url.rstrip("/")
    candidates = [f"{base}/status?{query}"]
    if base.lower().endswith("/api/v1"):
        root_base = base[:-7].rstrip("/")
        if root_base:
            candidates.append(f"{root_base}/status?{query}")
    return _dedupe_urls(candidates)


def summarize_samples(
    samples: list[dict[str, Any]],
    *,
    profile_name: str,
    camera_id: str,
    base_url: str,
    duration_seconds: float | None = None,
    interval_seconds: float | None = None,
) -> dict[str, Any]:
    ok_samples = [sample for sample in samples if sample.get("ok") and isinstance(sample.get("status"), dict)]
    errors = Counter(str(sample.get("error")) for sample in samples if sample.get("error"))
    first_pose = _pose(ok_samples[0]) if ok_samples else {}
    last_pose = _pose(ok_samples[-1]) if ok_samples else {}
    deltas = {
        field: _number(last_pose.get(field)) - _number(first_pose.get(field))
        for field in POSE_COUNTER_FIELDS
    }
    first_skip = first_pose.get("skip_reasons") if isinstance(first_pose.get("skip_reasons"), dict) else {}
    last_skip = last_pose.get("skip_reasons") if isinstance(last_pose.get("skip_reasons"), dict) else {}
    skip_reason_delta = {
        reason: int(_number(last_skip.get(reason)) - _number(first_skip.get(reason)))
        for reason in sorted(set(first_skip) | set(last_skip))
        if _number(last_skip.get(reason)) - _number(first_skip.get(reason)) != 0
    }
    target_delta = deltas["pose_target_object_count"]
    attached_delta = deltas["pose_attached_object_count"]
    attempt_delta = deltas["inference_attempt_count"]
    success_delta = deltas["inference_success_count"]
    runtime_pose_valid_rate = _bounded_ratio(attached_delta, target_delta)
    runtime_inference_success_rate = _bounded_ratio(success_delta, attempt_delta)
    latest_result_pose_available_ratio = _ratio(
        bool((_latest(sample).get("pose_available") if isinstance(_latest(sample), dict) else False))
        for sample in ok_samples
    )

    summary = {
        "profile_name": profile_name,
        "camera_id": camera_id,
        "requested_duration_seconds": duration_seconds,
        "requested_interval_seconds": interval_seconds,
        "samples": len(samples),
        "ok_samples": len(ok_samples),
        "error_count": len(samples) - len(ok_samples),
        "pose_provider": last_pose.get("pose_provider"),
        "pose_model_path": last_pose.get("pose_model_path"),
        "last_pose_fps": last_pose.get("pose_fps"),
        "last_pose_quality_level": last_pose.get("pose_quality_level"),
        "runtime_deltas": deltas,
        "skip_reason_delta": skip_reason_delta,
        "runtime_pose_valid_rate": runtime_pose_valid_rate,
        "runtime_inference_success_rate": runtime_inference_success_rate,
        "latest_result_pose_available_ratio": latest_result_pose_available_ratio,
        "counter_consistency_warnings": _counter_consistency_warnings(
            target_delta=target_delta,
            attached_delta=attached_delta,
            attempt_delta=attempt_delta,
            success_delta=success_delta,
        ),
        "gate": _gate(runtime_pose_valid_rate, deltas, skip_reason_delta),
        "errors": dict(errors),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "profile_name": profile_name,
        "camera_id": camera_id,
        "probe_config": {
            "duration_seconds": duration_seconds,
            "interval_seconds": interval_seconds,
        },
        "summary": summary,
        "samples": samples,
    }


def _pose(sample: dict[str, Any]) -> dict[str, Any]:
    status = sample.get("status") if isinstance(sample.get("status"), dict) else {}
    pose = status.get("pose") if isinstance(status.get("pose"), dict) else {}
    return pose


def _latest(sample: dict[str, Any]) -> dict[str, Any]:
    status = sample.get("status") if isinstance(sample.get("status"), dict) else {}
    latest = status.get("latest_result") if isinstance(status.get("latest_result"), dict) else {}
    return latest


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _ratio(values) -> float:
    items = list(values)
    if not items:
        return 0.0
    return round(sum(1 for item in items if item) / len(items), 4)


def _bounded_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(min(1.0, max(0.0, numerator / denominator)), 4)


def _counter_consistency_warnings(
    *,
    target_delta: float,
    attached_delta: float,
    attempt_delta: float,
    success_delta: float,
) -> list[str]:
    warnings = []
    if attached_delta > target_delta:
        warnings.append("pose_attached_delta_exceeds_target_delta")
    if success_delta > attempt_delta:
        warnings.append("inference_success_delta_exceeds_attempt_delta")
    return warnings


def _gate(pose_valid_rate: float, deltas: dict[str, float], skip_reason_delta: dict[str, int]) -> dict[str, Any]:
    busy_delta = deltas.get("skipped_due_to_busy", 0.0)
    target_delta = deltas.get("pose_target_object_count", 0.0)
    blockers = []
    if pose_valid_rate < 0.70:
        blockers.append("pose_valid_rate_below_0.70")
    if busy_delta > max(2.0, target_delta * 0.10):
        blockers.append("busy_skip_too_high")
    for reason in (*BLOCKING_STALE_REASONS, "frame_tracking_desync", "pose_track_mismatch"):
        if skip_reason_delta.get(reason, 0) > 0:
            blockers.append(reason)
    return {
        "passed": not blockers,
        "blockers": blockers,
        "recommendation": _recommendation(blockers),
    }


def _recommendation(blockers: list[str]) -> str:
    if not blockers:
        return "runtime profile is acceptable for the next provider/model comparison gate"
    if "busy_skip_too_high" in blockers:
        return "raise scheduling capacity or reduce contention before retraining"
    if any(reason in blockers for reason in BLOCKING_STALE_REASONS):
        return "classify stale as source/capture/detection lag before provider replacement"
    if "frame_tracking_desync" in blockers:
        return "test B/C TTL and frame-age profiles before provider replacement"
    if "pose_track_mismatch" in blockers:
        return "compare full-frame and crop providers; do not use mismatched pose as evidence"
    return "fix pose runtime validity before retraining"


def _dedupe_urls(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
