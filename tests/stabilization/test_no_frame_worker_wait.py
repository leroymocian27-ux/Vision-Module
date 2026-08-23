import inspect

from app.services.detection_service import DetectionService


def test_detection_worker_waits_when_no_frame_or_duplicate_frame():
    source = inspect.getsource(DetectionService._run_loop)

    assert "stop_event.wait(interval)" in source
    assert "stop_event.wait(0.03)" in source
    assert "packet is None or packet.seq == last_seq" in source
