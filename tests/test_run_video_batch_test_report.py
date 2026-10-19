from __future__ import annotations

from pathlib import Path

from scripts.run_video_batch_test import build_final_result


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_build_final_result_prefers_active_binary_provider() -> None:
    result = build_final_result(
        video_path=Path(r"C:\Users\YANG\Desktop\视频\demo.mp4"),
        metadata={"duration_sec": 1.0, "fps": 30.0, "width": 1280, "height": 720, "frame_count": 30},
        binary_summary={
            "provider": "CUDAExecutionProvider",
            "sample_fps": 3.0,
            "sampled_frames": 10,
            "processed_frames": 10,
            "fall_frames": 6,
            "non_fall_frames": 4,
            "unknown_frames": 0,
            "max_fall_probability": 0.9,
            "mean_fall_probability": 0.5,
            "max_consecutive_fall": 3,
        },
        fall_event_result={"event_created": True, "event_count": 1, "primary_event_id": "evt-1", "event": {"safety_decision": {"outcome": "alert", "reason": "qwen_high_risk_confirmed_fall"}},},
        qwen_result={"qwen_requested": True, "qwen_started": True, "qwen_completed": True, "qwen_failed": False, "model": "qwen", "endpoint": "http://127.0.0.1:11434/api/chat", "verdict": "confirmed_fall", "confidence": 0.99, "analysis_status": "completed", "summary": "confirmed"},
        archive_status={},
        preflight={
            "binary_model": {
                "path": str(
                    PROJECT_ROOT
                    / "models"
                    / "post_fall_v2"
                    / "efficientnet_b0"
                    / "fall_candidate_efficientnet_b0.onnx"
                ),
                "requested_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
                "active_providers": ["CPUExecutionProvider"],
                "available_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
                "loaded": True,
            }
        },
        failure=None,
    )

    assert result["binary"]["provider"] == "CPUExecutionProvider"
    assert result["binary"]["requested_providers"] == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert result["binary"]["active_providers"] == ["CPUExecutionProvider"]
    assert result["alarm"]["should_alarm"] is True
