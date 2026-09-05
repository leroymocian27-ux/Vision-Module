from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "frontend_demo" / "app.js").read_text(encoding="utf-8")


def _function_source(name: str, next_name: str) -> str:
    start = APP_JS.index(f"function {name}(")
    end = APP_JS.index(f"function {next_name}(", start)
    return APP_JS[start:end]


def test_f5_starts_video_only_and_does_not_disrupt_full_session() -> None:
    source = APP_JS[APP_JS.index("async function startVideoOnly("):APP_JS.index("async function startBothModels(")]

    assert '["STARTING", "RUNNING", "STOPPING"].includes(sessionState)' in source
    assert 'postModelToggle("binary", false' in source
    assert 'postModelToggle("qwen", false' in source
    assert "startStreamRequest({ updateUi: false })" in source
    assert source.index('postModelToggle("binary", false') < source.index("startStreamRequest({ updateUi: false })")


def test_f6_starts_binary_before_qwen_and_requires_video() -> None:
    source = APP_JS[APP_JS.index("async function startBothModels("):APP_JS.index("async function startTimedTest(")]

    assert "state.lastControlStatus?.stream_connected" in source
    assert 'postModelToggle("binary", true' in source
    assert 'postModelToggle("qwen", true' in source
    assert source.index('postModelToggle("binary", true') < source.index('postModelToggle("qwen", true')


def test_f7_resets_demo_or_current_real_judgment_without_stopping_models() -> None:
    source = _function_source("resetCurrentJudgment", "renderQwenDescription")
    snapshot_source = _function_source("currentJudgmentSnapshot", "acknowledgeJudgmentIncidentIds")

    assert "state.demoFall.active" in source
    assert "resetDemoFall(" in source
    assert "acknowledgeJudgmentIncidentIds" in source
    assert "forceIdleAlarmIndicator()" in source
    assert 'setViewerAlertState("idle")' in source
    assert "postModelToggle(" not in source
    assert "stopDetectionSession(" not in source
    assert "presentation?.is_real_fall === true" in snapshot_source


def test_new_and_existing_function_keys_are_registered() -> None:
    staged = _function_source("handleStagedControlHotkey", "handleDemoHotkey")
    session = _function_source("handleSessionHotkey", "handleStagedControlHotkey")
    demo = _function_source("handleDemoHotkey", "startEventReviewPolling")

    assert '["F5", "F6", "F7"].includes(event.key)' in staged
    assert 'event.key === "F5" ? startVideoOnly() : startBothModels()' in staged
    assert 'event.key === "F7"' in staged
    assert 'event.key !== "F8"' in session
    assert 'event.key !== "F9" && event.key !== "F10"' in demo
    assert 'window.addEventListener("keydown", handleStagedControlHotkey)' in APP_JS
    assert 'window.addEventListener("keydown", handleSessionHotkey)' in APP_JS
    assert 'window.addEventListener("keydown", handleDemoHotkey)' in APP_JS
