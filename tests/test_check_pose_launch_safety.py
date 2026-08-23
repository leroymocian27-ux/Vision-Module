from __future__ import annotations

from pathlib import Path

from scripts.check_pose_launch_safety import build_launch_safety_report


def test_launch_safety_passes_guarded_start_and_background_launcher(tmp_path: Path) -> None:
    guarded = tmp_path / "start_current_camera.py"
    guarded.write_text(
        """
def _should_run_pose_deployment_guard(args): return True
def main():
    summary = {"deployment_allowed": True}
""",
        encoding="utf-8",
    )
    background = tmp_path / "launch_current_camera_background.py"
    background.write_text(
        'subprocess.Popen(["python", "scripts/start_current_camera.py", "--no-wait"])\n',
        encoding="utf-8",
    )

    report = build_launch_safety_report([guarded, background])

    assert report["summary"]["launch_safety_passed"] is True
    assert report["summary"]["blockers"] == []


def test_launch_safety_allows_direct_pose_alert_uvicorn_when_app_lifespan_has_guard(tmp_path: Path) -> None:
    script = tmp_path / "app_guarded_launcher.py"
    script.write_text(
        """
env = {
    "ENABLE_POSE": "true",
    "MAIN_SYSTEM_ALERT_ENABLED": "true",
    "POSE_RESULT_TTL_MS": "800",
    "POSE_MAX_FRAME_AGE_MS": "800",
}
subprocess.Popen(["python", "-m", "uvicorn", "app.main:app"], env=env)
""",
        encoding="utf-8",
    )

    report = build_launch_safety_report([script])

    assert report["summary"]["launch_safety_passed"] is True
    warnings = report["summary"]["warnings"][0]["warnings"]
    assert "direct_pose_alert_launch_relies_on_app_lifespan_guard" in warnings
    assert report["checks"][0]["metrics"]["app_main_pose_deployment_guard"] is True


def test_launch_safety_blocks_direct_pose_alert_uvicorn_when_app_guard_is_disabled(tmp_path: Path) -> None:
    script = tmp_path / "unsafe_launcher.py"
    script.write_text(
        """
env = {
    "ENABLE_POSE": "true",
    "MAIN_SYSTEM_ALERT_ENABLED": "true",
    "POSE_DEPLOYMENT_GUARD_ENABLED": "false",
    "POSE_RESULT_TTL_MS": "800",
    "POSE_MAX_FRAME_AGE_MS": "800",
}
subprocess.Popen(["python", "-m", "uvicorn", "app.main:app"], env=env)
""",
        encoding="utf-8",
    )

    report = build_launch_safety_report([script])

    blockers = report["summary"]["blockers"][0]["blockers"]
    assert report["summary"]["launch_safety_passed"] is False
    assert "direct_pose_alert_launch_disables_app_deployment_guard" in blockers


def test_launch_safety_blocks_brittle_pose_ttl_defaults(tmp_path: Path) -> None:
    script = tmp_path / "start_phase5_test.py"
    script.write_text(
        """
env = {
    "ENABLE_POSE": "true",
    "POSE_RESULT_TTL_MS": "500",
    "POSE_MAX_FRAME_AGE_MS": "500",
}
subprocess.Popen(["python", "-m", "uvicorn", "app.main:app"], env=env)
""",
        encoding="utf-8",
    )

    report = build_launch_safety_report([script])

    blockers = report["summary"]["blockers"][0]["blockers"]
    assert "brittle_pose_ttl_or_frame_age_default" in blockers


def test_launch_safety_warns_for_debug_pose_launcher(tmp_path: Path) -> None:
    script = tmp_path / "debug_pose_launcher.py"
    script.write_text(
        """
env = {
    "ENABLE_POSE": "true",
    "POSE_WORKER_FPS": "2",
}
subprocess.Popen(["python", "-m", "uvicorn", "app.main:app"], env=env)
""",
        encoding="utf-8",
    )

    report = build_launch_safety_report([script])

    assert report["summary"]["launch_safety_passed"] is True
    warnings = report["summary"]["warnings"][0]["warnings"]
    assert "pose_worker_fps_below_recommended_3" in warnings
    assert "debug_pose_launch_not_production_evidence" in warnings


def test_launch_safety_detects_direct_vision_launch_even_when_identity_service_is_present(tmp_path: Path) -> None:
    script = tmp_path / "start_phase5_test.py"
    script.write_text(
        """
IDENTITY_DIR = ROOT / "identity_service"
subprocess.Popen(["python", "-m", "uvicorn", "app.main:app"], cwd=IDENTITY_DIR)
env = {
    "ENABLE_POSE": "true",
    "POSE_WORKER_FPS": "3",
}
subprocess.Popen(["python", "-m", "uvicorn", "app.main:app"], cwd=ROOT, env=env)
""",
        encoding="utf-8",
    )

    report = build_launch_safety_report([script])
    check = report["checks"][0]

    assert report["summary"]["launch_safety_passed"] is True
    assert check["metrics"]["direct_vision_uvicorn"] is True
    assert "direct_pose_launch_without_main_alert_not_production_evidence" in check["warnings"]
