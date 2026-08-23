from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.events.qwen_keyframe import QwenImageInput, QwenKeyframeAnalyzer
from app.post_fall_v2.qwen_fall_analyzer import PFV2QwenFallAnalyzer
from app.post_fall_v2.schemas import FallEvent, KeyframePackage


JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00" + bytes([8] * 64) + b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08"
    b"\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xbf\xff\xd9"
)


def event() -> FallEvent:
    return FallEvent(
        incident_id="qwen-robustness-artifact",
        camera_id="camera_01",
        state="fall_confirmed",
        started_at="2026-08-14T00:00:00+00:00",
        confirmed_at="2026-08-14T00:00:00+00:00",
        binary_evidence={"max_fall_probability": 0.9},
    )


def package() -> KeyframePackage:
    return KeyframePackage(
        incident_id="qwen-robustness-artifact",
        camera_id="camera_01",
        confirmed_at="2026-08-14T00:00:00+00:00",
        source_width=16,
        source_height=16,
        frames=[],
        fall_probability_summary={},
        status="ready",
    )


def image() -> QwenImageInput:
    return QwenImageInput(offset_ms=0, role="t0", image_bytes=JPEG_BYTES)


def run_case(name: str, raw_response: str) -> dict:
    analyzer = PFV2QwenFallAnalyzer(
        analyzer=QwenKeyframeAnalyzer(
            endpoint_url="http://127.0.0.1:11434/api/chat",
            model_name="qwen3.5:4b",
            timeout_seconds=1,
            transport=lambda *_: {"message": {"content": raw_response}},
        ),
        image_provider=lambda _: ([image()], []),
    )
    detail = analyzer.analyze_fall_event(event(), package())
    return {
        "case": name,
        "raw_response": raw_response,
        "analysis_status": detail.analysis_status,
        "normalized_response": detail.to_record(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Write deterministic PFV2 Qwen parser robustness evidence.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/post_fall_v2/finalization/qwen_robustness_report.json"),
    )
    args = parser.parse_args()
    valid = {
        "schema_version": "pfv2_post_fall_detail.v1",
        "posture": "侧卧在地面。",
        "movement_level": "none_observed",
        "attempt_to_stand": "not_observed",
        "persistent_ground_state": "observed",
        "possible_help_gesture": "unknown",
        "visibility": "good",
        "occlusion": "none",
        "scene_risks": ["通行区域有障碍物。"],
        "summary": "人员持续处于低位。",
        "review_points": ["复核是否存在起身动作。"],
        "confidence": 0.7,
    }
    cases = [
        ("pure_json", json.dumps(valid, ensure_ascii=False)),
        ("markdown_with_explanation", "结果如下：\n```json\n" + json.dumps(valid, ensure_ascii=False) + "\n```\n请人工复核。"),
        (
            "aliases_english_enums_and_percent",
            json.dumps(
                {
                    "posture_description": "Kneeling posture.",
                    "activity_level": "none",
                    "attempting_to_stand": False,
                    "persistent_ground": True,
                    "visibility_level": "poor",
                    "occlusion_level": "partial",
                    "scene_risk": "Floor obstacle.",
                    "review_point": "Check the live view.",
                    "confidence_score": "65%",
                }
            ),
        ),
        (
            "medical_language_is_sanitized",
            json.dumps(
                {
                    **valid,
                    "summary": "疑似昏迷。",
                    "scene_risks": ["疑似骨折。"],
                    "review_points": ["建议医疗诊断。"],
                },
                ensure_ascii=False,
            ),
        ),
        ("invalid_json", "这不是 JSON"),
    ]
    rows = [run_case(name, raw) for name, raw in cases]
    payload = {
        "strategy": [
            "Ollama JSON schema format",
            "first JSON object extraction",
            "deterministic aliases and enum normalization",
            "missing values become unknown or a fixed visual-review prompt",
            "no model retry",
            "medical diagnosis terms are replaced with a visual-only review statement",
        ],
        "case_count": len(rows),
        "completed_count": sum(row["analysis_status"] == "completed" for row in rows),
        "parse_failed_count": sum(row["analysis_status"] == "parse_failed" for row in rows),
        "cases": rows,
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "completed": payload["completed_count"], "parse_failed": payload["parse_failed_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
