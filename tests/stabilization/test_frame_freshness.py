from app.camera.frame_freshness import FreshnessThresholds, frame_freshness


def test_frame_freshness_statuses():
    thresholds = FreshnessThresholds(delayed_ms=1000, stale_ms=3000)

    assert frame_freshness(None, thresholds).frame_status == "no_frame"
    assert frame_freshness(500, thresholds).frame_status == "fresh"
    assert frame_freshness(1500, thresholds).frame_status == "delayed"
    stale = frame_freshness(3500, thresholds)

    assert stale.frame_status == "stale"
    assert stale.is_stale is True
    assert stale.safe_to_interpret_as_no_fall is False
