from app.camera.frame_freshness import normalize_camera_state


def test_fresh_connected_maps_to_streaming():
    assert normalize_camera_state(
        running=True,
        connected=True,
        internal_state="connected",
        frame_status="fresh",
    ) == "streaming"


def test_delayed_and_stale_are_public_states():
    assert normalize_camera_state(running=True, connected=True, internal_state="connected", frame_status="delayed") == "delayed"
    assert normalize_camera_state(running=True, connected=True, internal_state="connected", frame_status="stale") == "stale"


def test_errors_map_to_specific_public_states():
    assert normalize_camera_state(
        running=True,
        connected=False,
        internal_state="reconnecting",
        frame_status="no_frame",
        last_error="401 unauthorized",
    ) == "authentication_failed"
    assert normalize_camera_state(
        running=True,
        connected=False,
        internal_state="reconnecting",
        frame_status="no_frame",
        last_error="decode failed",
    ) == "decode_error"


def test_stopped_is_not_disconnected():
    assert normalize_camera_state(
        running=False,
        connected=False,
        internal_state="disconnected",
        frame_status="stale",
    ) == "stopped"
