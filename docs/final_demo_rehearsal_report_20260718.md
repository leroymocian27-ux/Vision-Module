# Final Demo Rehearsal Report 2026-07-18

## 1. Rehearsal Conclusion

PASS.

The formal demo rehearsal can proceed to onsite presentation. Core demo checks passed: service startup, `/demo/`, mock video/WebRTC, overlay, event semantic review, six keyframes, Delivery dry-run display, VLM disabled/rule review display, API safety, and regression tests.

## 2. Rehearsal Environment

- Service port: `8135`.
- Service parent pid: `34688`.
- Uvicorn server pid observed: `17912`.
- Environment style: temporary session/subprocess environment variables only.
- `.env` modified: no.
- `.env` SHA256 before and after: `1039A9A43956BE749E5FF75A6DF06503AB6BB2A892A6E61B67759A09B990EED4`.
- Temporary service stopped: yes.
- Port cleanup: no listener remained on `8135`; only short-lived `TIME_WAIT` connections were observed after stop.
- Demo data location: `tmp_final_demo_rehearsal/`.

## 3. Enabled Configuration

```text
EVENT_PIPELINE_ENABLED=true
EVENT_RING_BUFFER_ENABLED=true
EVENT_WORKER_ENABLED=true
EVENT_SEMANTIC_ENABLED=true
EVENT_OUTBOX_BACKEND=sqlite
EVENT_ARCHIVE_ENABLED=true
EVENT_KEYFRAME_SERVING_ENABLED=true
EVENT_DELIVERY_ENABLED=true
EVENT_DELIVERY_WORKER_ENABLED=true
EVENT_DELIVERY_MODE=dry_run
EVENT_DELIVERY_BACKEND=sqlite
EVENT_VLM_ENABLED=false
EVENT_VLM_PROVIDER=dummy
EVENT_DELIVERY_TARGET_URL=
EVENT_DELIVERY_ENDPOINT=
```

Kafka, Redis, and Celery were not connected.

## 4. Demo Event

- Input method: demo seed.
- Seed command scenario: `fallen_confirmed_high`.
- Seeded incident id: `final-demo-rehearsal-20260718`.
- Detail API incident id: `final-demo-rehearsal-20260718`.
- `/events/latest` incident during rehearsal: `codex-final-rehearsal-b`, an existing demo event in the same temporary SQLite store.
- Delivery status: `dry_run_sent`.
- Delivery mode: `dry_run`.
- Dry run: `true`.
- Review result: `demo_seed_rule_only`.
- VLM/Ollama status: disabled; page displayed rule-review fallback.
- Keyframes: six relative `/events/...` keyframe URLs.

Recommendation for the live demo: run the seed with a clean demo store or use the Recent Events list to click the intended seeded incident.

## 5. API Acceptance Results

| API | Result |
| --- | --- |
| `GET /healthz` | `200`, `{"status":"ok"}` |
| `GET /status` | `200`, accessible |
| `GET /events/status` | `200`, event pipeline enabled |
| `GET /events/latest?camera_id=camera_01` | `200`, returned an event with delivery dry-run |
| `GET /events/final-demo-rehearsal-20260718` | `200`, returned the seeded event |
| `GET /events/final-demo-rehearsal-20260718/keyframes/t0` | `200`, `image/jpeg` |
| `GET /events/delivery/status` | `200`, accessible |

Seeded event detail checks:

```text
delivery_status=dry_run_sent
delivery_mode=dry_run
dry_run=true
review_result=demo_seed_rule_only
keyframe_count=6
```

## 6. Frontend Acceptance Results

URL:

```text
http://127.0.0.1:8135/demo/?v=final-demo-rehearsal
```

Observed:

- Video element exists.
- Overlay canvas exists.
- Mock stream status reached `画面正常`.
- WebRTC reached `connected`.
- Video ready state reached `4`.
- Video size reached `1280x720`.
- Event Semantic Review panel exists.
- Pipeline status displayed enabled/running.
- Event Summary displayed the seeded incident after selecting it from Recent Events.
- Intelligent Review displayed rule review.
- Delivery displayed `模拟投递完成`, `dry_run / 模拟`, and `是，模拟投递`.
- VLM advisory displayed disabled/rule-review fallback.
- Keyframe Timeline displayed six cards.
- Six keyframe images loaded from relative `/events/...` URLs.
- Timeline Image displayed a reasonable no-process-image state.
- `DIAGNOSTICS` and `RAW STATUS` sections exist.
- Browser page console warning/error count: `0`.

Responsive checks:

| Width | Result |
| ---: | --- |
| `1366` | Passed, no horizontal overflow, six keyframes, dry-run text correct |
| `768` | Passed, no horizontal overflow, six keyframes, dry-run text correct |

## 7. Security Review

- Real POST: no.
- Real main-system endpoint configured: no.
- `target_url` exposed: no.
- `lock_token` exposed: no.
- raw `payload_json` exposed: no.
- provider `raw_response` exposed: no.
- provider request payload exposed: no.
- local absolute path exposed in public event JSON: no.
- token/header exposed: no.
- external VLM enabled: no.
- local Ollama forced on: no.

## 8. Demo Script

Recommended 2-3 minute script:

"The realtime detection path first finds fall candidates through the existing video, detection, tracking, feature, and fusion chain. `FallFusionService` remains the decision authority for the realtime path."

"The event semantic path runs behind the realtime path. It does not block detection. It builds an evidence package, keeps six keyframes around the event, and creates an explainable review result for operators."

"The keyframe timeline helps replay what happened before and after the suspected fall. In this rehearsal all six keyframes are available through safe relative `/events/...` URLs."

"The review explanation and recommended action are produced by the rule review path. Ollama/Qwen is reserved as advisory-only capability, but it remains disabled by default because the latest local evaluation did not meet the latency budget."

"DeliveryOutbox is currently dry-run. `dry_run_sent` means the delivery flow was verified, but no real alert was sent to the main system. The formal current main-system alert path is still `FallEventReporterService`."

Forbidden statements:

- Do not say a large model directly determines falls.
- Do not say dry-run is a formal alert.
- Do not say Kafka, Redis, or Celery are connected.
- Do not say the formal main-system alert path has been replaced.
- Do not say the system can medically diagnose injury.
- Do not say images were sent to external Qwen.
- Do not expose endpoint URLs, headers, tokens, raw payloads, lock tokens, or local paths.

## 9. Issues Found

| Issue | Severity | Blocks Demo | Suggested Handling |
| --- | --- | --- | --- |
| `/events/latest` returned an existing demo event because the temporary SQLite store already had another newer demo record. | Low | No | Before the live demo, start from a clean demo store or use `--clear-demo`, then seed the intended incident. |
| PowerShell background launch methods were blocked by the current tool policy during rehearsal automation. | Low | No | Use the controlled Node/browser rehearsal launcher or manually start the service in an operator terminal for the live demo. |

## 10. Regression Results

```text
node --check frontend_demo/app.js: passed
python -m pytest tests/test_event_api.py tests/test_event_keyframe_api.py tests/test_event_archive.py -q: 19 passed
python -m pytest tests/test_event_pipeline_e2e_smoke.py tests/test_event_pipeline_integration.py -q: 10 passed
python -m pytest tests/test_event_delivery_abc_final_integration_guard.py tests/test_event_delivery_final_e2e_runbook.py -q: 8 passed
python -m pytest tests/test_ollama_vlm_adapter_contract.py tests/test_ollama_vlm_text_only_payload.py tests/test_intelligent_analysis_engine_ollama_advisory_only.py -q: 13 passed
python -m py_compile app/api/event_api.py app/events/delivery.py app/events/delivery_worker.py app/events/vlm.py app/events/vlm_adapter.py app/events/analysis_engine.py app/core/config.py: passed
git diff --check: passed with existing LF/CRLF warnings only
```

## 11. Final Recommendation

Proceed to formal demo rehearsal/presentation.

Manual confirmations before going live:

- Confirm the intended video source or mock/replay source.
- Confirm a clean demo SQLite store or select the intended seeded event in Recent Events.
- Confirm no real endpoint is configured.
- Confirm VLM/Ollama remains disabled.
- Confirm the presenter uses `dry-run` wording and does not describe it as a formal alert.
- Confirm `FallEventReporterService` is described as the retained formal alert path.
