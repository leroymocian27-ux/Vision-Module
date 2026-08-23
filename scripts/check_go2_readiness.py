from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def evaluate(*, go2_root: Path, approved_read_only: bool = False) -> dict[str, Any]:
    sdk_markers = ["unitree_sdk2py", "unitree_sdk2", "example", "README.md"]
    existing_markers = [name for name in sdk_markers if (go2_root / name).exists()]
    blockers: list[str] = []
    if not approved_read_only:
        blockers.append("MISSING_APPROVE_GO2_READ_ONLY")
    if not go2_root.is_dir():
        blockers.append("GO2_DEVELOPMENT_ROOT_NOT_FOUND")
    elif not existing_markers:
        blockers.append("GO2_SDK_MARKERS_NOT_FOUND")
    return {
        "gate_name": "GO2_READ_ONLY_READY",
        "gate_status": "PASS" if not blockers else "BLOCKED",
        "approved_read_only": approved_read_only,
        "go2_root_exists": go2_root.is_dir(),
        "sdk_markers": existing_markers,
        "network_probe_executed": False,
        "dds_probe_executed": False,
        "motion_commands_sent": 0,
        "blockers": blockers,
        "next_allowed_action": "read-only network and DDS diagnostics" if not blockers else "obtain approval and device facts",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only, offline Go2 readiness preflight.")
    parser.add_argument("--go2-root", default=r"E:\笨笨狗\go2_dev")
    parser.add_argument("--approved-read-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate(go2_root=Path(args.go2_root), approved_read_only=args.approved_read_only)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['gate_name']}: {result['gate_status']}")
        for blocker in result["blockers"]:
            print(f"- {blocker}")
    return 0 if result["gate_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
