from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the LAN alert probe target without restarting the probe process.")
    parser.add_argument("--target-ip", required=True)
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--base-path", default="/api/v1/video-bridge/fall-events")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--token", default="")
    parser.add_argument("--config-file", default="data/alert_probe_target.json")
    args = parser.parse_args()

    path = Path(args.config_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "target_ip": args.target_ip,
        "port": args.port,
        "base_path": args.base_path,
        "interval": args.interval,
        "token": args.token,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path.resolve())
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
