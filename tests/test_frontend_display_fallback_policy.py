from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "frontend_demo" / "app.js").read_text(encoding="utf-8")


def test_low_webrtc_fps_is_not_treated_as_visibly_healthy() -> None:
    assert "const WEBRTC_MIN_ACCEPTABLE_FPS = 8;" in APP_JS
    assert "function isWebRtcFpsHealthy()" in APP_JS
    assert "lastMeasuredFps" in APP_JS
    assert "return hasProgress && paintLooksLive && isWebRtcFpsHealthy();" in APP_JS
    assert "fps >= WEBRTC_MIN_ACCEPTABLE_FPS" in APP_JS


def test_display_mjpeg_fallback_stream_stays_visible_and_retries_after_error() -> None:
    assert "const DISPLAY_MJPEG_DEFAULT_FPS = 12;" in APP_JS
    assert "function displayMjpegTargetFps" in APP_JS
    assert "effective_config?.display_mjpeg_fps" in APP_JS
    assert "const FRAME_FALLBACK_STREAM_ERROR_RETRY_MS = 1500;" in APP_JS
    assert "now - state.frameFallback.lastErrorAt < FRAME_FALLBACK_STREAM_ERROR_RETRY_MS" in APP_JS
    assert 'state.frameFallback.lastUrl?.includes("/stream/display.mjpg")' in APP_JS
    assert "fps=${encodeURIComponent(fps)}" in APP_JS
    assert "&fps=15" not in APP_JS
    assert "state.frameFallback.lastUrl = null;" in APP_JS
    assert "(image.complete || state.frameFallback.lastUrl?.includes(\"/stream/display.mjpg\"))" in APP_JS


def test_frontend_hides_stale_display_frame_instead_of_showing_old_image_as_live() -> None:
    assert "const backendCanShowLiveFrame = !status || isBackendFrameFresh(status);" in APP_JS
    assert "backendCanShowLiveFrame && (!videoHealthy || !webrtcConnected)" in APP_JS
    assert "const backendCanServeFrame = !status || isBackendFrameFresh(status) || backendHasDisplayFrame(status);" not in APP_JS


def test_frontend_prefers_dedicated_mjpeg_display_fps_metric() -> None:
    dashboard_js = (ROOT / "frontend_demo" / "dashboard-adapter.js").read_text(encoding="utf-8")

    assert "display_mjpeg_served_fps ?? displayStatus?.display_served_fps" in dashboard_js
    assert "`mjpeg ${formatFps(displayStatus.display_mjpeg_served_fps, \"FPS\")}`" in dashboard_js
    assert "display_mjpeg_served_fps ?? getDisplayStreamStatus(data)?.display_served_fps" in APP_JS


def test_frontend_does_not_auto_start_webrtc_for_mjpeg_sources() -> None:
    assert "function shouldPreferMjpegDisplay" in APP_JS
    assert 'String(protocol || "").toLowerCase() === "mjpeg"' in APP_JS
    assert "if (shouldPreferMjpegDisplay(status))" in APP_JS
    assert "syncFrameFallbackLoop(status);" in APP_JS
