from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evaluations" / "pose_promotion_gate_20260705.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Combine pose evidence/deployment/launch gates into one promotion decision.")
    parser.add_argument("--evidence-package", default="evaluations/pose_evidence_package_check_20260705.json")
    parser.add_argument("--deployment-guard", default="evaluations/pose_deployment_guard_20260705.json")
    parser.add_argument("--launch-safety", default="evaluations/pose_launch_safety_check_20260705.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    report = build_promotion_gate_report(
        evidence_package_path=Path(args.evidence_package),
        deployment_guard_path=Path(args.deployment_guard),
        launch_safety_path=Path(args.launch_safety),
    )
    output = resolve_path(Path(args.output))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["promotion_allowed"] else 1


def build_promotion_gate_report(
    *,
    evidence_package_path: Path,
    deployment_guard_path: Path,
    launch_safety_path: Path,
) -> dict[str, Any]:
    checks = {
        "evidence_package": check_evidence_package(evidence_package_path),
        "deployment_guard": check_deployment_guard(deployment_guard_path),
        "launch_safety": check_launch_safety(launch_safety_path),
    }
    blockers = [
        {"gate": name, "blockers": check["blockers"]}
        for name, check in checks.items()
        if check["blockers"]
    ]
    warnings = [
        {"gate": name, "warnings": check["warnings"]}
        for name, check in checks.items()
        if check["warnings"]
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "promotion_allowed": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "next_action": next_action(blockers, warnings),
        },
        "checks": checks,
    }


def check_evidence_package(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return check_result(path, ["evidence_package_missing"], [], {})
    summary = as_dict(payload.get("summary"))
    blockers = []
    warnings = []
    if summary.get("handoff_ready") is not True:
        blockers.append("evidence_package_handoff_ready_false")
    for item in list_of_dicts(summary.get("blockers")):
        for blocker in item.get("blockers") or []:
            blockers.append(prefix_once(item.get("gate"), blocker))
    for item in list_of_dicts(summary.get("warnings")):
        for warning in item.get("warnings") or []:
            warnings.append(prefix_once(item.get("gate"), warning))
    return check_result(
        path,
        dedupe(blockers),
        dedupe(warnings),
        {
            "handoff_ready": summary.get("handoff_ready"),
            "next_action": summary.get("next_action"),
        },
    )


def check_deployment_guard(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return check_result(path, ["deployment_guard_missing"], [], {})
    summary = as_dict(payload.get("summary"))
    blockers = []
    warnings = []
    if summary.get("deployment_allowed") is not True:
        blockers.append("deployment_guard_deployment_allowed_false")
    for item in list_of_dicts(summary.get("blockers")):
        for blocker in item.get("blockers") or []:
            blockers.append(prefix_once(item.get("gate"), blocker))
    for item in list_of_dicts(summary.get("warnings")):
        for warning in item.get("warnings") or []:
            warnings.append(prefix_once(item.get("gate"), warning))
    return check_result(
        path,
        dedupe(blockers),
        dedupe(warnings),
        {
            "deployment_allowed": summary.get("deployment_allowed"),
            "next_action": summary.get("next_action"),
        },
    )


def check_launch_safety(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return check_result(path, ["launch_safety_missing"], [], {})
    summary = as_dict(payload.get("summary"))
    blockers = []
    warnings = []
    if summary.get("launch_safety_passed") is not True:
        blockers.append("launch_safety_passed_false")
    for item in list_of_dicts(summary.get("blockers")):
        for blocker in item.get("blockers") or []:
            blockers.append(prefix_once(item.get("script"), blocker))
    for item in list_of_dicts(summary.get("warnings")):
        for warning in item.get("warnings") or []:
            warnings.append(prefix_once(item.get("script"), warning))
    return check_result(
        path,
        dedupe(blockers),
        dedupe(warnings),
        {
            "launch_safety_passed": summary.get("launch_safety_passed"),
            "next_action": summary.get("next_action"),
        },
    )


def check_result(path: Path, blockers: list[str], warnings: list[str], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "passed": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "metrics": metrics,
    }


def next_action(blockers: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> str:
    if not blockers:
        if warnings:
            return "promotion gate passed with warnings; debug launch outputs remain non-production evidence"
        return "pose promotion gate passed; proceed only with controlled production rollout"
    gates = [item.get("gate") for item in blockers]
    if "evidence_package" in gates:
        return "generate production-ready evidence first; do not promote pose until handoff_ready=true"
    if "deployment_guard" in gates:
        return "fix deployment guard before starting pose-enabled production service"
    if "launch_safety" in gates:
        return "fix launch safety blockers before using any pose-enabled startup path"
    return "fix pose promotion blockers before production rollout"


def read_json(path: Path) -> tuple[dict[str, Any], bool]:
    resolved = resolve_path(path)
    if not resolved.exists():
        return {}, True
    return json.loads(resolved.read_text(encoding="utf-8")), False


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def prefix_once(prefix: Any, value: Any) -> str:
    prefix_text = str(prefix or "unknown")
    value_text = str(value)
    return value_text if value_text.startswith(f"{prefix_text}:") else f"{prefix_text}:{value_text}"


if __name__ == "__main__":
    raise SystemExit(main())
