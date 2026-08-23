# Final Change Freeze Guard

## 1. Frozen Scope

The final demo freeze covers:

- Realtime detection main path.
- Event API public summary.
- DeliveryOutbox safe summary.
- Frontend Event Review display.
- VLM/Ollama default-disabled posture.
- Demo runbook and final acceptance checklist.

## 2. Allowed Changes

- Small documentation corrections.
- Small copy changes.
- Focused test additions.
- Stronger public-field redaction.
- Demo script clarification.

Allowed changes must preserve the main path, default-off optional paths, and public API safety.

## 3. Forbidden Changes

- Do not enable Delivery by default.
- Do not enable VLM/Ollama by default.
- Do not send real POST to the main system.
- Do not replace `FallEventReporterService`.
- Do not modify `FallFusionService`.
- Do not show local paths.
- Do not show tokens, headers, endpoints, `target_url`, `payload_json`, or lock tokens.
- Do not display dry-run as formal delivery.
- Do not add Kafka, Redis, Celery, or new production infrastructure without separate approval.

## 4. Required Regression After Changes

Run at least:

```powershell
python -m pytest tests/test_event_api.py tests/test_event_keyframe_api.py tests/test_event_archive.py -q
python -m pytest tests/test_event_pipeline_e2e_smoke.py tests/test_event_pipeline_integration.py -q
python -m pytest tests/test_event_delivery_abc_final_integration_guard.py tests/test_event_delivery_final_e2e_runbook.py -q
python -m pytest tests/test_event_delivery_payload_compat.py tests/test_event_delivery_security_payload.py -q
python -m pytest tests/test_ollama_vlm_adapter_contract.py tests/test_ollama_vlm_text_only_payload.py tests/test_intelligent_analysis_engine_ollama_advisory_only.py -q
python -m pytest tests/test_event_frontend_public_summary_guard.py -q
node --check frontend_demo/app.js
python -m py_compile app/api/event_api.py app/events/delivery.py app/events/delivery_worker.py app/events/vlm.py app/events/vlm_adapter.py app/events/analysis_engine.py app/core/config.py
git diff --check
```

The final handover marker is `EVENT_SEMANTIC_PIPELINE_FINAL_HANDOVER_READY`.
The final project freeze marker is `EVENT_SEMANTIC_PIPELINE_FINAL_FREEZE_READY`.

These markers do not authorize default-on Delivery, real main-system POST,
default-on VLM/Ollama, external Qwen access, Kafka/Redis/Celery integration, or
replacement of `FallEventReporterService`.
