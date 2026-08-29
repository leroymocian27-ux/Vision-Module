from __future__ import annotations

import argparse
import json
import math
import socket
import time
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Send mock Go2 follow-target UDP telemetry.")
    parser.add_argument("--host", default="127.0.0.1", help="Receiver host or IP.")
    parser.add_argument("--port", type=int, default=8766, help="Receiver UDP port.")
    parser.add_argument("--bearing", type=float, default=0.0, help="Target bearing in camera degrees.")
    parser.add_argument("--distance", type=float, default=2.0, help="Target distance in meters.")
    parser.add_argument("--invalid", action="store_true", help="Send target_valid=false and follow_active=false.")
    parser.add_argument("--hz", type=float, default=20.0, help="Send frequency.")
    parser.add_argument("--duration", type=float, default=0.0, help="Seconds to run. 0 means until Ctrl+C.")
    parser.add_argument("--sweep", type=float, default=0.0, help="Optional bearing sweep amplitude in degrees.")
    args = parser.parse_args()

    interval = 1.0 / max(1.0, float(args.hz))
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    sequence = 0
    started = time.monotonic()
    target = (args.host, int(args.port))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        print(f"sending go2_follow_target.v1 to udp://{args.host}:{args.port} at {args.hz:g}Hz")
        while deadline is None or time.monotonic() < deadline:
            now = time.monotonic()
            bearing = float(args.bearing)
            if args.sweep:
                bearing += math.sin((now - started) * 2.0) * float(args.sweep)
            payload = _payload(
                sequence=sequence,
                bearing=bearing,
                distance=float(args.distance),
                invalid=bool(args.invalid),
            )
            sock.sendto(json.dumps(payload, separators=(",", ":")).encode("utf-8"), target)
            sequence += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    return 0


def _payload(*, sequence: int, bearing: float, distance: float, invalid: bool) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    return {
        "schema_version": "go2_follow_target.v1",
        "sequence": int(sequence),
        "target_valid": not invalid,
        "follow_active": not invalid,
        "bearing_deg": round(float(bearing), 3),
        "distance_m": round(float(distance), 3),
        "relative_x_m": round(math.sin(math.radians(bearing)) * distance, 3),
        "relative_y_m": round(math.cos(math.radians(bearing)) * distance, 3),
        "source_timestamp_ms": now_ms,
        "sent_timestamp_ms": now_ms,
    }


if __name__ == "__main__":
    raise SystemExit(main())
