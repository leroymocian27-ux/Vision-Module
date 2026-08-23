# Event Pipeline Final Handover Pack

Final marker: `EVENT_SEMANTIC_PIPELINE_FINAL_HANDOVER_READY`.

Final freeze marker: `EVENT_SEMANTIC_PIPELINE_FINAL_FREEZE_READY`.

## 1. Final Project Status

The current Vision Service has a stable realtime fall-detection main path and an additive event-level semantic side path.

The optimization work added evidence packaging, six-point keyframe review, event semantics, rule-first trusted review, frontend review display, and DeliveryOutbox dry-run delivery verification. VLM/Ollama capability is reserved as advisory-only work and remains disabled by default.

This package is for demo handover and acceptance closure. It does not approve real main-system POST, real external VLM access, model training, dataset changes, Kafka, Redis, Celery, or replacement of the existing formal alert path.

## 2. Current Realtime Main Path

```text
RTSP / mock / replay
        ->
CaptureWorker
        ->
FrameBuffer
        ->
YOLO person
        ->
ByteTrack
        ->
Fall Hint / Pose / Temporal
        ->
FallFeatureBuilder
        ->
FallFusionService
        ->
ResultPublisherService
        ->
WebRTC / WS / REST
        ->
FallEventReporterService
```

`FallFusionService` remains the fall decision authority. `FallEventReporterService` remains the formal main-system alert path.

## 3. Event Semantic Side Path

```text
FallFusion result
        ->
IncidentManager
        ->
EventOutbox
        ->
EvidencePackage
        ->
EventSemantics
        ->
RuleAnalyzer
        ->
Optional VLM/Ollama advisory
        ->
TrustedEventResult
        ->
Archive / API / Frontend / DeliveryOutbox
```

The event path is additive. It must not block capture, detection, fusion, WebRTC, WS, REST, or legacy alert reporting.

## 4. A/B/C Completion Summary

A-line delivery reliability:

- DeliveryOutbox side path.
- `dry_run` and controlled `post`.
- SQLite and memory backends.
- Retry/failed state handling.
- Idempotency by `incident_id`.
- Public safe summary.
- Mock post and service-level dry-run acceptance.
- A-line handover pack sealed.

B-line frontend showcase:

- Event Semantic Review panel.
- Event summary and intelligent review display.
- Six-point keyframe timeline.
- Timeline Image state handling.
- Delivery status display.
- VLM/Ollama advisory field compatibility.
- Browser visual QA and rehearsal checklist are present in existing B-line docs.

C-line VLM/Ollama advisory:

- VLM adapter contract and fallback behavior.
- `qwen_http` shell retained for tests.
- Local Ollama/Qwen text-only advisory path reserved.
- RuleAnalyzer remains default and authoritative.
- Advisory-only merge policy.
- Evaluation script and P14 report.
- Current recommendation: `KEEP_DISABLED`.

## 5. Freeze Status

```text
A: DELIVERY_OUTBOX_HANDOVER_PACK_READY
B: EVENT_FRONTEND_SHOWCASE_FREEZE_READY
C: VLM_OLLAMA_ADVISORY_FREEZE_READY / KEEP_DISABLED
Overall: EVENT_SEMANTIC_PIPELINE_FINAL_HANDOVER_READY
Final Freeze: EVENT_SEMANTIC_PIPELINE_FINAL_FREEZE_READY
```

Notes:

- A-line status is derived from `docs/event_delivery_final_handover_pack.md`, `docs/event_delivery_final_freeze_report.md`, and delivery guard tests.
- B-line status is derived from `docs/event_frontend_final_freeze_report.md`, `docs/event_frontend_final_acceptance.md`, and `docs/event_frontend_demo_rehearsal_checklist.md`.
- C-line status is derived from `docs/ollama_qwen_advisory_evaluation_report.md`, `docs/ollama_qwen_event_review_integration.md`, `docs/event_vlm_activation_readiness.md`, and `docs/vlm_ollama_advisory_final_freeze_report.md`.

## 6. Default-Off Confirmation

```text
EVENT_PIPELINE_ENABLED=false
EVENT_DELIVERY_ENABLED=false
EVENT_DELIVERY_WORKER_ENABLED=false
EVENT_VLM_ENABLED=false
```

The real main-system endpoint is not configured. Kafka, Redis, and Celery are not connected.

Verified default values from `Settings()` on 2026-07-18:

```text
EVENT_PIPELINE_ENABLED=False
EVENT_DELIVERY_ENABLED=False
EVENT_DELIVERY_WORKER_ENABLED=False
EVENT_VLM_ENABLED=False
EVENT_DELIVERY_TARGET_URL=''
```

## 7. Recommended Demo Mode

- Temporarily enable the event path for the demo session only.
- Use demo seed or an already accepted replay event.
- Keep DeliveryOutbox in `dry_run`.
- Keep VLM/Ollama disabled or show rule-only review fallback.
- Do not POST to the real main system.
- Do not modify local `.env`.

## 8. Final Browser Handover Check

Final browser handover check was executed against:

```text
enabled_url=http://127.0.0.1:8000/demo/?v=final-demo-handover-check
disabled_url=http://127.0.0.1:8011/demo/?v=final-demo-handover-check-disabled
seed_incident=codex-final-handover-b
```

Observed:

- 1920 / 1366 / 1024 / 768 all passed.
- Enabled state loaded 6/6 keyframe images.
- Disabled state showed `事件语义链路未启用`, 6 placeholder cards, and 0 image requests.
- Browser console warn/error count was 0.
- Video, overlay, Raw Status, and Diagnostics nodes were present.
- Public JSON exposed no `target_url`, `lock_token`, `payload_json`, `raw_response`, token/header, or local path.

Artifacts:

- `tmp_event_visual_qa/handover_status.json`
- `tmp_event_visual_qa/handover_latest_event.json`
- `tmp_event_visual_qa/handover_console_check.json`
- `tmp_event_visual_qa/handover_seed_1920.png`
- `tmp_event_visual_qa/handover_seed_1366.png`
- `tmp_event_visual_qa/handover_seed_1024.png`
- `tmp_event_visual_qa/handover_seed_768.png`
- `tmp_event_visual_qa/handover_disabled_1366.png`

## 9. Not Enabled Or Not Connected

- Real main-system endpoint.
- External Qwen endpoint.
- Ollama default enablement.
- Image-input VLM.
- Kafka.
- Redis.
- Celery.
- Formal replacement of the current main-system alert path.
