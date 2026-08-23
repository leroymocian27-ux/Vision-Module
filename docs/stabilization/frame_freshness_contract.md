# Frame Freshness Contract

Date: 2026-07-20

## Metadata

Every latest-frame observation should expose:

```text
camera_id
source
source_generation
frame_id
captured_at
received_at
frame_age_ms
width
height
frame_status
is_stale
```

## Frame Status

| State | Meaning |
| --- | --- |
| `no_frame` | No valid frame has ever arrived for this source generation. |
| `fresh` | `frame_age_ms <= FRAME_DELAYED_THRESHOLD_MS`. |
| `delayed` | `FRAME_DELAYED_THRESHOLD_MS < frame_age_ms <= FRAME_STALE_THRESHOLD_MS`. |
| `stale` | `frame_age_ms > FRAME_STALE_THRESHOLD_MS`. |
| `capture_stopped` | Source was stopped. |
| `camera_disconnected` | Capture is disconnected or reconnecting. |

`FRAME_STALE_THRESHOLD_MS` reuses `STREAM_STALE_THRESHOLD_MS` in the current implementation. `FRAME_DELAYED_THRESHOLD_MS` defaults to 1000 ms.

## Safety Rule

`no_frame`, `stale`, `capture_stopped`, and `camera_disconnected` must not be interpreted as normal safe no-fall evidence. If a latest result is exposed while the camera is unavailable, it must include compatible fields such as:

```json
{
  "fall_state": "unavailable",
  "reason": "no_frame",
  "safe_to_interpret_as_no_fall": false
}
```
