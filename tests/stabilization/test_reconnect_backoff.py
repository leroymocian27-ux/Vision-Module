from app.camera.reconnect_policy import ReconnectPolicy


def test_reconnect_backoff_uses_bounded_schedule():
    policy = ReconnectPolicy(schedule_sec=(1, 2, 5, 10, 30))

    assert [policy.next_delay() for _ in range(7)] == [1, 2, 5, 10, 30, 30, 30]


def test_reconnect_backoff_reset_restarts_schedule():
    policy = ReconnectPolicy(schedule_sec=(1, 2, 5))
    assert policy.next_delay() == 1
    assert policy.next_delay() == 2
    policy.reset()
    assert policy.next_delay() == 1
