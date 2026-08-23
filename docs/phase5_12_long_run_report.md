# Phase 5.12 Long-Run Stability Report

## Scope

This report validates the full Phase 5 runtime after:

- Phase 5.10: identity binding moved out of the TrackingWorker hot path.
- Phase 5.11: RTSP/OpenCV capture read latency instrumentation and safer reconnect observability.

This phase did not add features, change fall rules, modify frontend behavior, connect alarms, save snapshots, POST to a backend, or introduce GRU/LSTM.

## Test Configuration

- Real RTSP: `rtsp://admin:***@192.168.8.254:554/tcp/av0_1`
- `ENABLE_TRACKING=true`
- `ENABLE_IDENTITY_BINDING=true`
- `IDENTITY_BINDING_ASYNC=true`
- `ENABLE_POSE=true`
- `ENABLE_BEHAVIOR=true`
- `ENABLE_TEMPORAL=true`
- `TRACKING_WORKER_FPS=12`
- `POSE_WORKER_FPS=2`
- `RESULT_PUBLISH_FPS=10`
- `CAPTURE_READ_WARN_MS=500`
- `CAPTURE_READ_STALE_MS=3000`
- `CAPTURE_FORCE_REOPEN_AFTER_SLOW_READS=3`
- `CAPTURE_READ_WATCHDOG_RELEASE_ENABLED=false`
- `OPENCV_CAPTURE_BUFFERSIZE=1`
- `OPENCV_FFMPEG_CAPTURE_OPTIONS=`

The read watchdog release is intentionally disabled. A previous pre-run revealed that releasing an active `cv2.VideoCapture` from a watchdog side thread can trigger an FFmpeg assertion on Windows:

```text
Assertion fctx->async_lock failed at libavcodec/pthread_frame.c:173
```

Therefore Phase 5.12 keeps read latency observation and reconnect-after-return behavior, but does not perform unsafe cross-thread capture release.

## Artifacts

- Raw long-run data: `logs/runtime_debug/phase5_12_long_run.json`
- Sampler script: `scripts/debug_phase5_12_long_run.py`

## Runtime Duration

- Requested duration: `900s`
- Samples collected: `670`
- Status request failures: `0`

The sampler interval stretched beyond 1 second because each sample also collected process and GPU telemetry.

## Summary Metrics

| Metric | Result |
| --- | ---: |
| Connected ratio | `92.99%` |
| Max `frame_age_ms` | `23641ms` |
| Average `frame_age_ms` | `621.85ms` |
| Samples with `frame_age_ms > 3000ms` | `32` |
| Average `capture_fps` | `28.54` |
| Minimum `capture_fps` | `3.78` |
| Max sampled `read_latency_ms` | `7610ms` |
| Reconnect delta | `9` |
| Read timeout delta | `96` |
| Average `detection_worker_fps` | `3.80` |
| Average `tracking_worker_fps` | `10.70` |
| Minimum `tracking_worker_fps` | `8.79` |
| Average `result_publish_fps` | `9.17` |
| Minimum `result_publish_fps` | `7.85` |
| Average `pose_fps` | `0.06` |
| Pipeline error count | `0` |
| Temporal error count | `0` |
| Average GPU utilization | `7.65%` |
| Max GPU memory used | `2546 MiB` |
| Vision process working set delta | `+103.51 MB` |
| Identity process working set delta | `+115.77 MB` |

## Observations

### 1. Service Process Stability

The service did not crash during the 15-minute run. `/status` remained reachable for all samples.

### 2. Tracking and Publishing Remain Healthy

The Phase 5.10 identity async fix held up:

- `tracking_worker_fps` averaged `10.70`.
- `result_publish_fps` averaged `9.17`.
- Identity pending requests stayed bounded, with max `pending_requests=1`.

This confirms identity no longer drags TrackingWorker down.

### 3. RTSP Capture Still Has Long Stalls

The capture layer still showed sustained RTSP/OpenCV stalls:

- Max `frame_age_ms`: `23641ms`.
- Max read latency: `7610ms`.
- `frame_age_ms > 3000ms` in `32` samples.
- Reconnect count increased by `9`.

Representative stall:

```text
stream_state=connecting
frame_age_ms=23641
read_latency_ms=7610
reconnect_reason=slow_read
last_error=slow read triggered reconnect: 7610.00ms
```

This is still an RTSP/OpenCV capture-layer issue, not an AI pipeline issue.

### 4. Auto-Reconnect Recovers, But Not Fast Enough

The system recovered after slow reads and read failures. However, reconnect/open recovery sometimes took long enough for `frame_age_ms` to climb above 10 seconds. This fails the desired long-run criterion that `frame_age_ms` should not sustain above 3000ms.

### 5. Unsafe Watchdog Release Was Rejected

Attempting to force-release `VideoCapture` from a watchdog thread can crash FFmpeg/OpenCV on this Windows stack. The safer current implementation avoids that crash, but cannot interrupt every blocking read immediately.

## Pass/Fail Against Phase 5.12 Criteria

| Criterion | Result |
| --- | --- |
| Service does not crash | Pass |
| Stream mostly connected | Partial pass, `92.99%` connected |
| `frame_age_ms` not sustained over 3000ms | Fail |
| Slow read/reconnect can recover | Partial pass |
| Tracking worker avg near 10 FPS | Pass |
| Result publish avg near 9 FPS | Pass |
| Identity does not slow tracking | Pass |
| `pipeline.last_error` not persistently abnormal | Pass |
| `temporal.last_error` null or recovered | Pass |
| No obvious process memory leak | Partial pass, mild growth observed |

## Conclusion

Phase 5 upper pipeline stability is strong enough to keep:

- TrackingWorker stable.
- ResultPublisher stable.
- Identity binding isolated from tracking.
- Temporal rule preview isolated from runtime stability.

However, Phase 5.12 long-run capture stability is not sealed yet. The remaining blocker is RTSP/OpenCV capture behavior under long-running real-camera conditions.

## Recommendation

Do not declare full runtime sealed yet.

Recommended next stage:

```text
Phase 5.13: Capture Isolation Hardening
```

Candidate approaches:

- Move RTSP capture into a separate process so a blocking/unstable OpenCV/FFmpeg read cannot stall or crash the main vision service.
- Evaluate an FFmpeg subprocess reader with low-latency flags and latest-frame pipe semantics.
- Keep `FrameBuffer(maxsize=1)` in the main service.
- Preserve the current AI pipeline unchanged.

Do not proceed to GRU/LSTM or production alarm integration until capture isolation is stable under a longer run.
