# Event Semantic Pipeline Design

## Current chain

The realtime chain remains authoritative and unchanged:

```text
capture -> detection/tracking/pose/temporal -> FallFusionService -> ResultPublisherService
       -> WebRTC / WebSocket / REST / FallEventReporterService
```

The additive event chain is disabled by default:

```text
ResultPublisher observer -> IncidentManager -> EventOutbox -> worker
-> EvidencePackage -> EventSemantics -> RuleAnalyzer -> TrustedEventResult
-> optional archive -> optional DeliveryOutbox
```

`FallEventReporterService` has not been replaced. Kafka is not needed for the current single-node deployment. VLM remains disabled and is not required for any event decision.

## VLM/Ollama Review Freeze

Engineer C has frozen the VLM/Ollama advisory review layer under
`VLM_OLLAMA_ADVISORY_FREEZE_READY`.

The default event semantic review remains rule-based through `RuleAnalyzer`.
Ollama/Qwen is implemented only as a default-disabled, text-only,
advisory-only reservation. It may enrich explanations and reviewer advice after
rules have produced a result, but it must not change fall confirmation, risk
level, fall state, delivery state, or realtime outputs.

Current recommendation is `KEEP_DISABLED`. The local text-only smoke timed out
for both `qwen-vision-cn:latest` and `qwen3.5:9b` at the 15 second budget, so
the project should not enter timeline image or image-input VLM phases.

## Data and APIs

`FallEventRecord` is created from a confirmed or candidate fused decision. The worker adds `EvidencePackage`, `EventSemantics`, and `TrustedEventResult` to its `EventOutboxRecord`. The read-only event APIs are:

- `GET /events/status`
- `GET /events/outbox?status=&camera_id=&limit=`
- `GET /events/latest?camera_id=`
- `GET /events/{incident_id}`
- `GET /events/{incident_id}/keyframes/{keyframe_id}` and `GET /events/{incident_id}/keyframes/by-offset/{offset_ms}`

API responses omit absolute archive paths, raw image bytes, and internal lock tokens. Archived keyframe names are relative identifiers only, and archived images are fetched through bounded `/events/{incident_id}/keyframes/{keyframe_id}` URLs such as `t0` or `t_minus_3s`. When a delivery record exists, `/events/latest` and `/events/{incident_id}` include a read-only delivery summary with status, mode, dry-run marker, retry count, next retry time, last error, delivered time, and backend.

## Configuration

All flags default to false: `EVENT_PIPELINE_ENABLED`, `EVENT_RING_BUFFER_ENABLED`, `EVENT_WORKER_ENABLED`, `EVENT_SEMANTIC_ENABLED`, `EVENT_ARCHIVE_ENABLED`, and `EVENT_DELIVERY_ENABLED`.

`EVENT_OUTBOX_BACKEND=memory|sqlite` selects the event queue backend. SQLite uses `EVENT_OUTBOX_SQLITE_PATH`. Archives are controlled by `EVENT_ARCHIVE_*`. Delivery has `dry_run` and `post` modes through `EVENT_DELIVERY_*`; dry-run creates a delivery record without HTTP traffic. `EVENT_DELIVERY_BACKEND=memory|sqlite` controls the optional delivery outbox store and defaults to memory. `post` mode requires an explicit `EVENT_DELIVERY_TARGET_URL` or `EVENT_DELIVERY_ENDPOINT`; an empty target records retry/failed and does not fall back to the legacy alert reporter URL.

## Degradation

Capture observer errors are swallowed. Missing timeline frames are represented in evidence and `degradation_used`. Archive failures are logged without failing the worker. VLM is not invoked while disabled. Delivery failures become retry/failed records without changing the legacy reporter path.

## Delivery Final E2E

DeliveryOutbox has entered A-line Final E2E acceptance. The current accepted scope verifies dry-run + SQLite, mock main-system post, retry/failed behavior, and safe delivery summaries in `/events/latest` and `/events/{incident_id}`. This does not change the authoritative realtime chain and does not replace `FallEventReporterService`.

A-line is now ready for A/B/C Final E2E integrated acceptance. DeliveryOutbox remains a side path and still does not replace the formal alert chain.

After A/B/C delivery guard acceptance, DeliveryOutbox is frozen as the reliable-delivery side-path stable version. The freeze does not enable delivery by default and does not change `FallEventReporterService`.

DeliveryOutbox handover pack is now sealed under `DELIVERY_OUTBOX_HANDOVER_PACK_READY`. The operational handover documents are `docs/event_delivery_final_handover_pack.md`, `docs/event_delivery_real_endpoint_activation_runbook.md`, `docs/event_delivery_demo_talking_points.md`, and `docs/event_delivery_change_guard.md`.

## Final Demo Handover

Overall demo handover is sealed in `docs/event_pipeline_final_handover_pack.md`, `docs/final_demo_runbook.md`, `docs/final_e2e_acceptance_checklist.md`, and `docs/final_change_freeze_guard.md`.

Final marker:

```text
FINAL_DEMO_HANDOVER_READY
```

## Frontend Display Freeze

B-line frontend display is frozen as the event evidence review demo layer. The freeze covers public event summaries, safe relative keyframe URLs, Timeline Image states, Delivery read-only status, VLM/Qwen/Ollama advisory-only fields, and disabled/no-event/missing-keyframe fallbacks. Public summaries do not expose local paths, `target_url`, `payload_json`, `lock_token`, raw responses, auth headers, or tokens. This display layer remains additive and does not change WebRTC, WebSocket, REST realtime status, overlay drawing, or the formal `FallEventReporterService` alert path.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_event_*.py tests\test_sqlite_event_outbox.py tests\test_fused_result_fallback.py -q
```

## TODO

- Real VLM adapter remains intentionally disabled.
- DeliveryOutbox is feature-flagged and supports memory or SQLite storage; durable SQLite delivery remains disabled unless explicitly configured.
- Add authentication or signed URLs before exposing archived keyframes outside the trusted demo network.
