# Final E2E Acceptance Checklist

## 1. Realtime Main Path

- [ ] `/healthz` returns 200.
- [ ] `/status` is normal.
- [ ] WebRTC video exists.
- [ ] WS has result updates.
- [ ] REST result endpoint has data.
- [ ] Overlay exists.

## 2. Event Path

- [ ] `/events/status` is accessible.
- [ ] `/events/latest?camera_id=<camera>` is accessible.
- [ ] Demo seed can generate an event.
- [ ] Evidence package exists.
- [ ] Event semantics exists.
- [ ] Trusted result exists.
- [ ] Archive summary exists.

## 3. Frontend Display

- [ ] Event panel exists.
- [ ] Six keyframe cards are present.
- [ ] `keyframe_url` values are relative `/events/...` paths.
- [ ] Disabled state renders correctly.
- [ ] No-event state renders correctly.
- [ ] Browser console has no warnings or errors during the check.

## 4. Delivery

- [ ] Delivery is default-off.
- [ ] `dry_run_sent` can be displayed as simulated delivery.
- [ ] No real POST is sent.
- [ ] `target_url` is not exposed.
- [ ] `lock_token` is not exposed.
- [ ] raw `payload_json` is not exposed.

## 5. VLM/Ollama

- [ ] VLM is default-off.
- [ ] RuleAnalyzer is the default review path.
- [ ] Ollama status remains `KEEP_DISABLED`.
- [ ] No images are sent to VLM/Ollama.
- [ ] No local paths are sent to VLM/Ollama.
- [ ] VLM/Ollama does not affect result generation when disabled or failed.

## 6. Documents

- [ ] A handover pack exists: `docs/event_delivery_final_handover_pack.md`.
- [ ] B final freeze docs exist: `docs/event_frontend_final_freeze_report.md` and `docs/event_frontend_demo_rehearsal_checklist.md`.
- [ ] C freeze/readiness docs exist: `docs/ollama_qwen_advisory_evaluation_report.md`, `docs/ollama_qwen_event_review_integration.md`, and `docs/event_vlm_activation_readiness.md`.
- [ ] Final demo runbook exists: `docs/final_demo_runbook.md`.
- [ ] Final checklist exists: `docs/final_e2e_acceptance_checklist.md`.
- [ ] Final change guard exists: `docs/final_change_freeze_guard.md`.
- [ ] Final handover pack exists: `docs/event_pipeline_final_handover_pack.md`.
