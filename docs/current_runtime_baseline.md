# Current Runtime Baseline

Baseline captured on 2026-07-17 before introducing the event semantic pipeline.

## Scope

This document records the real capabilities of the current Vision Service. It does not claim VLM review, event semantics, ring-buffer evidence packages, or a distributed message queue as implemented features.

## Runtime Chain

```text
RTSP or mock source
-> CaptureWorker and FrameBuffer
-> YOLO person detection
-> ByteTrack tracking
-> YOLO fall hint
-> optional pose and temporal workers
-> FallFeatureBuilder and FallFusionService
-> ResultPublisherService
-> WebRTC, WebSocket, REST, and FallEventReporterService
```

The configured pipeline mode is `legacy`. Fall fusion remains the realtime decision authority. Current output states include `normal`, `unstable`, `falling`, `fallen_candidate`, `fallen_confirmed`, and `cooldown`.

## Captured Configuration

| Area | Captured value |
| --- | --- |
| Video source | `mock://colorbars` |
| Detection | enabled, `yolov8n.pt` |
| Fall hint | enabled, candidate v3 C model |
| Tracking | enabled |
| Pose | enabled, `yolo11_legacy` |
| Temporal | enabled, ONNX LSTM v5 |
| Fusion worker | enabled |
| Main-system alerts | disabled |
| Alert delivery mode | dry-run when enabled |
| Alert SQLite outbox | disabled |

The mock stream was used only for this baseline capture. It produced fresh frames and healthy workers but no person or fall event, so the baseline does not claim a confirmed-fall runtime result.

## Live Interface Check

The local service was started on port `8010` and returned:

| Endpoint | Result |
| --- | --- |
| `GET /healthz` | `200 {"status":"ok"}` |
| `GET /status` | `200`, service and capture pipeline running |
| `GET /integration/results/camera_01/latest` | `200`, current realtime result returned |
| `/demo/` | mounted by the application for the operator console |

## Existing Reliability Building Blocks

- `FallEventReporterService` provides confirmed-fall reporting, snapshot persistence, in-memory incident reuse, and an asynchronous HTTP queue.
- `AlertOutboxService` provides a SQLite-backed delivery retry record when enabled.
- `RealtimeResultStore` retains the latest pipeline slots and a bounded detection history.
- `FrameBuffer` retains the latest frame for streaming, not a timestamp-addressable event evidence window.

These are foundations to reuse. They are not yet the proposed `EventOutbox`, `EvidencePackage`, `EventSemantics`, `TrustedEventResult`, or `DeliveryOutbox` layers.

## Models

The machine-readable model baseline is [model_locator.json](../models/model_locator.json). All active configured assets were present and independently loadable during the prior asset validation.

## Minimal Regression Results

Executed with the repository virtual environment on 2026-07-17:

| Test group | Result |
| --- | --- |
| `test_fall_fusion.py` | 10 passed |
| `test_temporal_service.py` | 3 passed |
| `test_integration_connection_status.py` | 4 passed |
| `test_alerting_manual_send.py` | 5 passed |
| `test_fall_alert_polling_api.py` | 7 passed with `FUSION_WORKER_ENABLED=false` test override |

## Known Baseline Risks

1. Resolved on 2026-07-17: `ResultPublisherService` now prefers a fresh fused-result slot and safely falls back to the snapshot path when that slot is empty or stale. The result source is exposed through detector debug metadata. See [fusion_result_fallback_fix.md](fusion_result_fallback_fix.md).
2. The current runtime profile is demonstration-oriented: it uses a mock source, does not have a discovered real camera or main-system endpoint, and main-system alert posting is disabled.
3. The existing alert outbox is a delivery concern. The planned event pipeline must add a separate internal event-processing outbox rather than overload delivery state.

## Freeze Rules

- Do not change the realtime FallFusion decision contract while adding the event pipeline.
- Keep `EVENT_PIPELINE_*` capabilities disabled by default when introduced.
- Add event APIs and frontend detail views without changing existing realtime result payload fields.
- Resolve the fused-result fallback/test-isolation defect before declaring the event pipeline production-ready.
