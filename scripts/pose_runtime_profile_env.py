from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


RUNTIME_ENV_PROFILES: dict[str, dict[str, str]] = {
    "B": {
        "DETECTION_INTERVAL_MS": "200",
        "FALL_DETECTOR_INTERVAL_MS": "200",
        "POSE_WORKER_FPS": "3",
        "POSE_SKIP_WHEN_INFERENCE_BUSY": "true",
        "POSE_INFERENCE_LOCK_WAIT_MS": "160",
        "POSE_RESULT_TTL_MS": "800",
        "POSE_PUBLISH_MAX_FRAME_DELTA": "8",
        "POSE_MAX_FRAME_AGE_MS": "800",
        "POSE_MAX_TRACKING_FRAME_DELTA": "2",
    },
    "Bcpu": {
        "DETECTION_INTERVAL_MS": "200",
        "FALL_DETECTOR_INTERVAL_MS": "800",
        "POSE_WORKER_FPS": "3",
        "POSE_SKIP_WHEN_INFERENCE_BUSY": "true",
        "POSE_INFERENCE_LOCK_WAIT_MS": "160",
        "POSE_RESULT_TTL_MS": "1000",
        "POSE_PUBLISH_MAX_FRAME_DELTA": "8",
        "POSE_MAX_FRAME_AGE_MS": "1000",
        "POSE_MAX_TRACKING_FRAME_DELTA": "2",
    },
    "C": {
        "DETECTION_INTERVAL_MS": "200",
        "FALL_DETECTOR_INTERVAL_MS": "800",
        "POSE_WORKER_FPS": "3",
        "POSE_SKIP_WHEN_INFERENCE_BUSY": "true",
        "POSE_INFERENCE_LOCK_WAIT_MS": "160",
        "POSE_RESULT_TTL_MS": "1000",
        "POSE_PUBLISH_MAX_FRAME_DELTA": "8",
        "POSE_MAX_FRAME_AGE_MS": "1000",
        "POSE_MAX_TRACKING_FRAME_DELTA": "3",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Print pose runtime profile environment overrides.")
    parser.add_argument("--profile", choices=sorted(RUNTIME_ENV_PROFILES), default="Bcpu")
    parser.add_argument("--format", choices=("powershell", "json", "env"), default="powershell")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    payload = build_profile_payload(args.profile)
    rendered = render_payload(payload, args.format)
    if args.output:
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + ("\n" if not rendered.endswith("\n") else ""), encoding="utf-8")
    print(rendered)
    return 0


def build_profile_payload(profile: str) -> dict[str, Any]:
    env = dict(RUNTIME_ENV_PROFILES[profile])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "production_profile": profile == "B",
        "env": env,
        "notes": profile_notes(profile),
    }


def profile_notes(profile: str) -> list[str]:
    if profile == "B":
        return [
            "Production candidate profile; requires CUDA/live 120s runtime probe before promotion.",
            "Do not assume this passes on CPU if person/fall/pose share one Ultralytics lock.",
        ]
    if profile == "Bcpu":
        return [
            "CPU/dev-live conservative profile for local chain validation.",
            "This is not production evidence and should still produce production_ready=false.",
        ]
    return [
        "Lag pressure profile with wider tracking delta.",
        "Use only for controlled A/B; check pose_track_mismatch and ADL false positives before promotion.",
    ]


def render_payload(payload: dict[str, Any], output_format: str) -> str:
    env = payload["env"]
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if output_format == "env":
        return "\n".join(f"{key}={value}" for key, value in env.items())
    lines = [f"# pose runtime profile: {payload['profile']}"]
    lines.extend(f"$env:{key}='{value}'" for key, value in env.items())
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
