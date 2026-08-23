# Vision Service Async Pipeline Runbook

Date: 2026-07-08

## Goal

`async_v1` decouples Fall Hint inference from the person detection loop. The frontend video path still reads the latest captured frame from `FrameBuffer`; AI results are published asynchronously and overlaid by the frontend.

## Phase 1: Fall Hint Async V1

Production fallback:

```env
PIPELINE_MODE=legacy
FALL_DETECTOR_ENABLED=true
FALL_HINT_IN_DETECTION_SERVICE=true
FALL_HINT_WORKER_ENABLED=false
```

Gray validation:

```env
PIPELINE_MODE=async_v1
FALL_DETECTOR_ENABLED=true
FALL_HINT_IN_DETECTION_SERVICE=false
FALL_HINT_WORKER_ENABLED=true
FALL_HINT_WORKER_FPS=3
FALL_HINT_MAX_FRAME_AGE_MS=800
FALL_HINT_RESULT_TTL_MS=1500
FALL_HINT_INFERENCE_LOCK_WAIT_MS=80
FALL_HINT_SKIP_IF_INFERENCE_BUSY=true
```

Disable Fall Hint for triage:

```env
PIPELINE_MODE=fall_disabled
FALL_DETECTOR_ENABLED=false
```

## Phase 2: Unified Decision Shadow

```env
UNIFIED_DECISION_ENABLED=true
UNIFIED_DECISION_SHADOW=true
UNIFIED_DECISION_PRIMARY_ENABLED=false
```

The output appears at `fusion_debug.unified_shadow_decision`. Reporter and main-system payloads still use the existing `fall_decision` and `alarm_preview` fields.

## Phase 3: Unified Decision Primary Gray Switch

```env
UNIFIED_DECISION_ENABLED=true
UNIFIED_DECISION_SHADOW=true
UNIFIED_DECISION_PRIMARY_ENABLED=true
```

Primary mode writes the unified decision back to `fall_decision` and `alarm_preview` without changing field names or the Reporter interface. If detection or tracking is stale, unified primary downgrades to candidate and does not report confirmed fall.

## Phase 4-5: Temporal and Fusion Workers

Optional worker split:

```env
TEMPORAL_WORKER_ENABLED=true
TEMPORAL_WORKER_FPS=3
TEMPORAL_RESULT_TTL_MS=1500
TEMPORAL_MAX_FRAME_DELTA=12
FUSION_WORKER_ENABLED=true
FUSION_WORKER_FPS=10
FUSED_RESULT_TTL_MS=1000
```

When enabled, Temporal writes `latest_temporal`, Fusion writes `latest_fused_result`, and Publisher reads the fused cache. When disabled, the legacy inline path remains active.

## Phase 6: Alert Outbox

```env
ALERT_OUTBOX_ENABLED=true
ALERT_OUTBOX_PATH=data/alert_outbox.sqlite3
ALERT_OUTBOX_RETRY_LIMIT=10
```

The outbox records confirmed-fall payloads before HTTP delivery and updates delivery state after dry-run, success, or failure.

## Verification

Check `/status` after startup:

- `detection[].pipeline_mode`
- `detection[].fall_hint_writer_source`
- `pipeline.fall_hint_worker_fps`
- `pipeline.latest_fall_hint_age_ms`
- `pipeline.latest_temporal_age_ms`
- `pipeline.latest_fused_age_ms`
- `pipeline.evidence_freshness`
- `workers.fall_hint_worker`
- `workers.temporal_worker`
- `workers.fusion_worker`
- `fall_event_reporter.outbox`

Expected behavior:

- `/stream/latest-frame.jpg` keeps returning the latest frame even when AI is slow.
- Fall Hint lock busy increments `skipped_lock_busy_count` and does not block Person YOLO.
- Stale Fall Hint is marked in `evidence_freshness` and does not block publishing.
- Switching back to `legacy` restores the original Fall Hint writer path.
- Turning worker switches off restores inline Temporal/Fusion behavior.
