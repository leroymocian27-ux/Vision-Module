# Module Lifecycle Contract

Date: 2026-07-20
Scope: S4 AI pipeline modules

## Canonical Status

Stable-demo RC modules use the following canonical lifecycle values:

```text
disabled
loading
warming_up
ready
degraded
error
stopped
```

## Required Status Fields

Where the module can observe them, status payloads should expose:

```text
enabled
provider
status
last_success_at
last_latency_ms
average_fps
error_count
last_error
```

Backward-compatible fields such as `running`, `loaded`, `state`, `fps`, `detection_fps`, `pose_fps`, or `result_age_ms` may remain during the RC cycle. S5 is responsible for converging `/status`, WebSocket, latest integration result, and demo display onto one public vocabulary.

## Legacy Mapping

Existing worker fields are interpreted as follows during S4:

| Legacy value | Canonical status |
| --- | --- |
| `enabled=false` | `disabled` |
| `running=false` and enabled | `stopped` |
| `loaded=false` and running | `loading` |
| `healthy` | `ready` |
| `stale` | `degraded` |
| `last_error` present after a handled exception | `degraded` |
| fatal module construction failure | `error` |
| temporal `window_ready=false` | `warming_up` |

## Module Notes

- `DetectionService` writes `DetectionSnapshot` with `frame_seq`, `frame_width`, `frame_height`, `timestamp`, `monotonic_at`, frame image, detector metadata, and detected objects.
- `TrackingService` preserves the frame-level contract through `ObjectSnapshot` written by the tracking worker and keeps fallback track IDs when ByteTrack cannot produce a track.
- `PoseService` disabled mode returns placeholders instead of loading a pose estimator; this keeps the person detection and downstream result path alive.
- `TemporalService` exposes warmup through `temporal.window_ready=false` until the required window is present, and `reset_camera()` clears track/person/spatial windows for source or track changes.
- `TemporalWorkerService` and `FusionWorkerService` catch per-tick exceptions, update error counters, and keep the FastAPI process alive.
- `ResultPublisherService` drops stale base frames, merges only fresh/aligned auxiliary evidence, and marks core evidence freshness in detector/fusion debug when enabled.
- `RealtimeResultStore.latest_with_freshness()` is the shared primitive for result age, missing/stale state, and frame alignment checks.

## Acceptance

```text
S4_MODULE_LIFECYCLE_CONTRACT: PASS
S5_PUBLIC_STATUS_UNIFICATION: NOT_RUN
```
