from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from scripts import start_current_camera
from scripts.start_current_camera import _should_run_pose_deployment_guard, _write_pose_deployment_guard


def test_start_current_camera_keeps_pose_runtime_defaults_less_brittle() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "start_current_camera.py").read_text(
        encoding="utf-8"
    )

    assert '"POSE_WORKER_FPS": _env_or("POSE_WORKER_FPS", "3")' in source
    assert '"POSE_MAX_FRAME_AGE_MS": _env_or("POSE_MAX_FRAME_AGE_MS", "800")' in source
    assert '"POSE_RESULT_TTL_MS": _env_or("POSE_RESULT_TTL_MS", "800")' in source
    assert '_env_or("YOLO11_POSE_MODEL_PATH", "yolo11n-pose.pt")' in source
    assert '_env_or("YOLO11_POSE_MODEL_PATH", "models/pose_yolo_batch001_003_yolo11s_best.pt")' not in source
    assert '"POSE_MAX_FRAME_AGE_MS": "500"' not in source
    assert '"POSE_RESULT_TTL_MS": "500"' not in source


def test_env_example_uses_current_safe_post_fall_v2_baseline_and_guard_defaults() -> None:
    source = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")

    assert "ENABLE_POSE=false" in source
    assert "POSE_PROVIDER=disabled_placeholder" in source
    assert "POST_FALL_V2_ENABLED=true" in source
    assert "POST_FALL_V2_BINARY_MODEL_PATH=models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx" in source
    assert "POST_FALL_V2_BINARY_MODEL_SHA256=e9871cdb4687055fb5d934dd994c2ad883adac0c2acab375c240f8e005ee04cc" in source
    assert "YOLO11_POSE_MODEL_PATH=yolo11n-pose.pt" in source
    assert "POSE_DEPLOYMENT_GUARD_ENABLED=true" in source
    assert "POSE_EVIDENCE_PACKAGE=evaluations/pose_evidence_package_check_20260705.json" in source
    assert "POSE_PROVIDER=yolo11_legacy" not in source
    assert "POSE_PROVIDER=yolo\n" not in source
    assert "POSE_RESULT_TTL_MS=500" not in source
    assert "POSE_MAX_FRAME_AGE_MS=500" not in source


def test_service_start_scripts_do_not_reintroduce_brittle_pose_ttl_defaults() -> None:
    scripts = [
        Path(__file__).resolve().parents[1] / "scripts" / "start_current_camera.py",
        Path(__file__).resolve().parents[1] / "scripts" / "start_phase5_test.py",
    ]

    for script in scripts:
        source = script.read_text(encoding="utf-8")
        assert '"POSE_MAX_FRAME_AGE_MS": "500"' not in source, script
        assert '"POSE_RESULT_TTL_MS": "500"' not in source, script
        assert '"POSE_WORKER_FPS": "1"' not in source, script
        assert '"POSE_FPS": "1"' not in source, script


def test_start_current_camera_does_not_force_temporal_mock_fallback() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "start_current_camera.py").read_text(
        encoding="utf-8"
    )

    assert '"TEMPORAL_FALLBACK_TO_MOCK": _env_or("TEMPORAL_FALLBACK_TO_MOCK", "false")' in source
    assert '"TEMPORAL_FALLBACK_TO_MOCK": "true"' not in source


def test_env_example_uses_current_temporal_runtime_defaults() -> None:
    env_example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")

    assert "ENABLE_TEMPORAL=true" in env_example
    assert "TEMPORAL_MODEL_PROVIDER=onnx_lstm" in env_example
    assert "TEMPORAL_FALLBACK_TO_MOCK=false" in env_example


def test_pose_deployment_guard_runs_for_pose_plus_main_alerts() -> None:
    assert _should_run_pose_deployment_guard(
        Namespace(pose_enabled=True, enable_main_system_alerts=True, skip_pose_deployment_guard=False)
    )
    assert not _should_run_pose_deployment_guard(
        Namespace(pose_enabled=True, enable_main_system_alerts=True, skip_pose_deployment_guard=True)
    )
    assert not _should_run_pose_deployment_guard(
        Namespace(pose_enabled=True, enable_main_system_alerts=False, skip_pose_deployment_guard=False)
    )
    assert not _should_run_pose_deployment_guard(
        Namespace(pose_enabled=False, enable_main_system_alerts=True, skip_pose_deployment_guard=False)
    )


def test_write_pose_deployment_guard_uses_startup_env(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps({"summary": {"handoff_ready": False, "blockers": [{"gate": "preflight", "blockers": ["x"]}]}}),
        encoding="utf-8",
    )
    output = tmp_path / "guard.json"
    env = {
        "ENABLE_POSE": "true",
        "POSE_PROVIDER": "yolo11_legacy",
        "YOLO11_POSE_DEVICE": "cuda:0",
        "POSE_WORKER_FPS": "3",
        "POSE_FPS": "3",
        "POSE_RESULT_TTL_MS": "800",
        "POSE_MAX_FRAME_AGE_MS": "800",
        "POSE_MAX_TRACKING_FRAME_DELTA": "2",
        "POSE_INFERENCE_LOCK_WAIT_MS": "160",
    }

    report = _write_pose_deployment_guard(env=env, evidence_package=evidence, output=output)
    written = json.loads(output.read_text(encoding="utf-8"))

    assert report["summary"]["deployment_allowed"] is False
    assert written["summary"]["deployment_allowed"] is False
    assert written["checks"]["pose_runtime_config"]["metrics"]["active_pose_device"] == "cuda:0"
    assert written["checks"]["evidence_package"]["blockers"] == ["pose_enabled_without_handoff_ready_evidence"]


def test_main_blocks_service_start_when_pose_deployment_guard_fails(tmp_path: Path, monkeypatch) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps({"summary": {"handoff_ready": False, "blockers": [{"gate": "preflight", "blockers": ["x"]}]}}),
        encoding="utf-8",
    )
    guard_output = tmp_path / "guard.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "start_current_camera.py",
            "--rtsp-url",
            "rtsp://admin:***@127.0.0.1:10554/tcp/av0_0",
            "--python",
            sys.executable,
            "--enable-pose",
            "--enable-main-system-alerts",
            "--pose-provider",
            "yolo11_legacy",
            "--pose-evidence-package",
            str(evidence),
            "--pose-deployment-guard-output",
            str(guard_output),
        ],
    )

    with patch("scripts.start_current_camera.subprocess.Popen") as popen:
        result = start_current_camera.main()

    assert result == 3
    service_start_calls = [
        call
        for call in popen.call_args_list
        if len(call.args) >= 1 and "-m" in call.args[0] and "uvicorn" in call.args[0]
    ]
    assert service_start_calls == []
    written = json.loads(guard_output.read_text(encoding="utf-8"))
    assert written["summary"]["deployment_allowed"] is False
    assert written["checks"]["evidence_package"]["blockers"] == ["pose_enabled_without_handoff_ready_evidence"]


def test_main_skip_pose_deployment_guard_allows_debug_start(tmp_path: Path, monkeypatch) -> None:
    evidence = tmp_path / "missing_evidence.json"
    guard_output = tmp_path / "guard.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "start_current_camera.py",
            "--rtsp-url",
            "rtsp://admin:***@127.0.0.1:10554/tcp/av0_0",
            "--python",
            sys.executable,
            "--enable-pose",
            "--enable-main-system-alerts",
            "--skip-pose-deployment-guard",
            "--pose-evidence-package",
            str(evidence),
            "--pose-deployment-guard-output",
            str(guard_output),
            "--no-wait",
        ],
    )
    fake_process = type("FakeProcess", (), {"pid": 12345})()

    with patch("scripts.start_current_camera.subprocess.Popen", return_value=fake_process) as popen:
        result = start_current_camera.main()

    assert result == 0
    service_start_calls = [
        call
        for call in popen.call_args_list
        if len(call.args) >= 1 and "-m" in call.args[0] and "uvicorn" in call.args[0]
    ]
    assert len(service_start_calls) == 1
    assert not guard_output.exists()
