from __future__ import annotations

from scripts.probe_video_link import diagnose_video_link, display_stream_url, probe_tcp_url, summarize


def test_probe_observed_seq_fps_uses_elapsed_time_not_sample_count() -> None:
    summary = summarize(
        [
            {"frame_seq": 100, "elapsed_sec": 0.0},
            {"frame_seq": 116, "elapsed_sec": 2.0},
            {"frame_seq": 132, "elapsed_sec": 4.0},
        ]
    )

    assert summary["frame_seq_delta"] == 32
    assert summary["observed_seq_fps"] == 8.0


def test_probe_diagnosis_marks_direct_source_timeout_as_blocking() -> None:
    diagnosis = diagnose_video_link(
        {
            "valid_samples": 3,
            "stream_states": {"unreachable": 3},
            "mjpeg_receive_fps": {"avg": 0.0},
            "mjpeg_publish_fps": {"avg": 0.0},
            "display_served_fps": {"avg": 0.0},
            "source_direct": {
                "frames": 0,
                "fps": 0.0,
                "errors_tail": ["URLError: <urlopen error timed out>"],
            },
            "last_sample": {"binary_queue_depth": 0, "binary_provider": "CUDAExecutionProvider"},
        }
    )

    assert diagnosis["severity"] == "blocking"
    assert diagnosis["bottleneck"] == "upstream_source_unreachable_or_not_emitting_frames"


def test_probe_diagnosis_distinguishes_reachable_tcp_from_closed_mjpeg_stream() -> None:
    diagnosis = diagnose_video_link(
        {
            "valid_samples": 3,
            "stream_states": {"unreachable": 3},
            "mjpeg_receive_fps": {"avg": 0.0},
            "mjpeg_publish_fps": {"avg": 0.0},
            "display_served_fps": {"avg": 0.0},
            "source_tcp": {"reachable": True, "host": "192.168.8.254", "port": 8093},
            "last_sample": {"binary_queue_depth": 0, "binary_provider": "CUDAExecutionProvider"},
        }
    )

    assert diagnosis["severity"] == "blocking"
    assert diagnosis["bottleneck"] == "upstream_http_mjpeg_stream_closes_without_frames"


def test_probe_diagnosis_marks_multiple_local_source_clients_as_blocking() -> None:
    diagnosis = diagnose_video_link(
        {
            "valid_samples": 3,
            "stream_states": {"unreachable": 3},
            "mjpeg_receive_fps": {"avg": 0.0},
            "mjpeg_publish_fps": {"avg": 0.0},
            "display_served_fps": {"avg": 0.0},
            "source_tcp": {"reachable": True, "host": "192.168.8.254", "port": 8093},
            "source_connections": {
                "active_count": 2,
                "total_count": 3,
                "connections": [
                    {"status": "ESTABLISHED", "pid": 100, "process_name": "python"},
                    {"status": "ESTABLISHED", "pid": 101, "process_name": "vlc"},
                ],
            },
            "last_sample": {"binary_queue_depth": 0, "binary_provider": "CUDAExecutionProvider"},
        }
    )

    assert diagnosis["severity"] == "blocking"
    assert diagnosis["bottleneck"] == "local_multiple_clients_pull_go2_source"


def test_probe_diagnosis_marks_missing_camera_runtime_as_stream_not_started() -> None:
    diagnosis = diagnose_video_link(
        {
            "valid_samples": 3,
            "camera_missing_samples": 3,
            "stream_states": {"unknown": 3},
            "mjpeg_receive_fps": {"avg": None},
            "mjpeg_publish_fps": {"avg": None},
            "last_sample": {
                "latest_reason": "camera_disabled",
                "latest_camera_stream_state": "disabled",
                "binary_queue_depth": 0,
            },
        }
    )

    assert diagnosis["severity"] == "blocking"
    assert diagnosis["bottleneck"] == "camera_stream_not_started"


def test_probe_diagnosis_marks_display_drop_after_good_publish() -> None:
    diagnosis = diagnose_video_link(
        {
            "valid_samples": 5,
            "stream_states": {"connected": 5},
            "mjpeg_receive_fps": {"avg": 14.0},
            "mjpeg_publish_fps": {"avg": 14.0},
            "display_served_fps": {"avg": 1.8},
            "display_encode_ms": {"avg": 8.0},
            "display_stream_probe": {"frames": 9, "fps": 1.8},
            "last_sample": {"binary_queue_depth": 0, "binary_provider": "CUDAExecutionProvider"},
        }
    )

    assert diagnosis["severity"] == "high"
    assert diagnosis["bottleneck"] == "display_stream_or_browser_delivery_bottleneck"


def test_probe_diagnosis_does_not_treat_mock_as_low_mjpeg_fps() -> None:
    diagnosis = diagnose_video_link(
        {
            "valid_samples": 5,
            "stream_states": {"streaming": 5},
            "mjpeg_receive_fps": {"avg": 0.0},
            "mjpeg_publish_fps": {"avg": 0.0},
            "display_served_fps": {"avg": 10.9},
            "display_target_fps": {"avg": 12.0},
            "display_stream_probe": {"frames": 55, "fps": 10.9},
            "last_sample": {
                "capture_fps": 15.7,
                "source_protocol": "mock",
                "binary_queue_depth": 0,
                "binary_provider": "CUDAExecutionProvider",
            },
        }
    )

    assert diagnosis["severity"] == "ok_or_needs_longer_probe"
    assert diagnosis["bottleneck"] == "no_clear_local_bottleneck_detected"


def test_probe_diagnosis_marks_display_drop_for_non_mjpeg_capture_source() -> None:
    diagnosis = diagnose_video_link(
        {
            "valid_samples": 5,
            "stream_states": {"streaming": 5},
            "mjpeg_receive_fps": {"avg": 0.0},
            "mjpeg_publish_fps": {"avg": 0.0},
            "display_served_fps": {"avg": 1.8},
            "display_target_fps": {"avg": 12.0},
            "display_encode_ms": {"avg": 7.0},
            "display_stream_probe": {"frames": 9, "fps": 1.8},
            "last_sample": {
                "capture_fps": 15.0,
                "source_protocol": "mock",
                "binary_queue_depth": 0,
                "binary_provider": "CUDAExecutionProvider",
            },
        }
    )

    assert diagnosis["severity"] == "high"
    assert diagnosis["bottleneck"] == "display_stream_or_browser_delivery_bottleneck"


def test_display_stream_probe_url_uses_server_default_without_forced_fps() -> None:
    assert display_stream_url("http://127.0.0.1:8000", "go2_front_camera") == (
        "http://127.0.0.1:8000/stream/display.mjpg?camera_id=go2_front_camera"
    )


def test_display_stream_probe_url_accepts_explicit_fps() -> None:
    assert display_stream_url("http://127.0.0.1:8000", "go2_front_camera", 12.0).endswith(
        "?camera_id=go2_front_camera&fps=12"
    )


def test_tcp_probe_rejects_url_without_host() -> None:
    result = probe_tcp_url("not-a-url")

    assert result["reachable"] is False
    assert result["error"] == "missing host"
