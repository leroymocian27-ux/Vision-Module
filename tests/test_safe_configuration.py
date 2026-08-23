from __future__ import annotations

from dataclasses import replace

from app.core.config import Settings, safe_configuration_snapshot
from app.schemas.status import ConfigurationStatus


def test_safe_configuration_snapshot_exposes_only_allowlisted_flags() -> None:
    settings = replace(
        Settings(),
        event_pipeline_enabled=True,
        event_delivery_enabled=True,
        event_delivery_mode="dry_run",
        event_vlm_enabled=False,
        robot_assist_enabled=True,
        robot_assist_mode="mock",
    )

    snapshot = safe_configuration_snapshot(settings)

    assert snapshot["effective_config"]["event_pipeline_enabled"] is True
    assert snapshot["effective_config"]["robot_assist_mode"] == "mock"
    assert snapshot["feature_flags"]["event_vlm_enabled"] is False
    assert "main_system_alert_token" not in snapshot["effective_config"]
    assert "event_delivery_target_url" not in snapshot["effective_config"]
    assert "default_rtsp_url" not in snapshot["effective_config"]
    assert ConfigurationStatus(**snapshot).model_dump() == snapshot


def test_post_mode_reports_missing_approval_and_authentication_without_sending() -> None:
    settings = replace(
        Settings(),
        event_delivery_enabled=True,
        event_delivery_mode="post",
        event_delivery_target_url="",
        main_system_alert_token="",
    )

    errors = settings.startup_safety_errors()

    assert "EVENT_DELIVERY_MODE=post requires EVENT_DELIVERY_POST_APPROVED=true" in errors
    assert "EVENT_DELIVERY_MODE=post requires EVENT_DELIVERY_TARGET_URL" in errors
    assert "EVENT_DELIVERY_MODE=post requires configured main-system token header and token" in errors


def test_go2_and_qwen_dangerous_combinations_are_rejected_before_startup() -> None:
    settings = replace(
        Settings(),
        go2_control_enabled=True,
        go2_control_approved=False,
        robot_assist_enabled=False,
        go2_low_level_control_enabled=True,
        qwen_media_input_enabled=True,
        qwen_media_privacy_approved=False,
    )

    errors = settings.startup_safety_errors()

    assert "GO2_LOW_LEVEL_CONTROL_ENABLED must remain false" in errors
    assert "GO2_CONTROL_ENABLED requires GO2_CONTROL_APPROVED=true" in errors
    assert "GO2_CONTROL_ENABLED requires ROBOT_ASSIST_ENABLED=true" in errors
    assert "QWEN_MEDIA_INPUT_ENABLED requires QWEN_MEDIA_PRIVACY_APPROVED=true" in errors


def test_safe_defaults_do_not_require_an_approval_or_external_service() -> None:
    settings = replace(
        Settings(),
        event_pipeline_enabled=False,
        event_delivery_enabled=False,
        event_vlm_enabled=False,
        robot_assist_enabled=False,
        go2_read_only_enabled=False,
        go2_control_enabled=False,
        go2_low_level_control_enabled=False,
        qwen_media_input_enabled=False,
    )

    assert settings.startup_safety_errors() == []
