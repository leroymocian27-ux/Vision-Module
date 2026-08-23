# Qwen VLM Final E2E Acceptance

## Goal

This C-line acceptance proves the event-level VLM/Qwen review layer is
pluggable, fail-open, explainable, and isolated from the realtime fall pipeline.
It validates that VLM is not enabled by default, does not replace rule decisions,
and does not require a real Qwen endpoint.

Realtime detection remains authoritative:

```text
FallFusionService -> ResultPublisherService -> WebRTC / WS / REST
                 -> FallEventReporterService
```

The optional C-line review path remains post-event:

```text
EvidencePackage + EventSemantics + keyframes + timeline_image
-> RuleAnalyzer
-> optional dummy/http/qwen_http VLM review
-> merge policy
-> TrustedEventResult
-> Event API / Archive readable fields
```

## Acceptance Matrix

| Scenario | Configuration / input | Expected result |
| --- | --- | --- |
| VLM disabled | `EVENT_VLM_ENABLED=false` | No VLM adapter is created; `TrustedEventResult` uses rule result; no false provider degradation. |
| Dummy provider | `provider=dummy` | Deterministic local `VLMReviewResult`; explanation/advice may be enriched; rule decision remains authoritative. |
| HTTP mock success | `provider=http` with mock transport | JSON response validates as `VLMReviewResult`; `latency_ms` is recorded; merge keeps safety boundaries. |
| Qwen HTTP mock success | `provider=qwen_http` with mock transport | Reuses HTTP shell; no SDK or hardcoded endpoint; mock JSON parses and merges. |
| Timeout fallback | provider raises timeout | Rule result still generated; `degradation_used` includes `vlm_timeout`. |
| Invalid JSON fallback | provider returns malformed JSON | Rule result still generated; `degradation_used` includes `vlm_invalid_json`. |
| Schema error fallback | wrong schema version or invalid field type | Controlled invalid-output fallback; event result does not fail. |
| Missing keyframes/images | no keyframes and no timeline image | HTTP/Qwen review skips before request; `vlm_skipped_no_images` is recorded; event result remains available. |
| Confirmed fall + VLM disagree | rule confirmed, VLM `support_fall_alarm=false` | Confirmed/high-critical result is not downgraded or cancelled; `vlm_disagree` is recorded. |
| Candidate + VLM support + low ADL | rule candidate, low ADL, VLM support | Explanation/action can be enriched; VLM does not directly confirm the event. |
| Candidate + high ADL suppression | high rule/VLM ADL likelihood | Result remains review/unsupported, not direct alarm confirmation. |
| API/archive path safety | archived local paths and VLM fields present | Public Event API redacts local absolute paths and does not expose `raw_response`. |

## API/B-Line Field Readiness

`TrustedEventResult` exposes optional read-only VLM summary fields for frontend
consumption:

- `vlm_provider`
- `vlm_latency_ms`
- `observed_process`
- `risk_interpretation`
- `adl_likelihood`
- `uncertainty`
- `degradation_used`
- `review_result`
- `recommended_action`
- `alarm_title`
- `alarm_body`

Timeline image remains in archive summary as relative `timeline/timeline.jpg`.
Local absolute keyframe paths and raw provider responses are not public fields.

## Verification Commands

```powershell
python -m pytest tests/test_vlm_adapter_contract.py tests/test_vlm_http_adapter.py tests/test_qwen_vlm_adapter_contract.py tests/test_vlm_prompt_schema_guard.py -q
python -m pytest tests/test_intelligent_analysis_engine.py tests/test_intelligent_analysis_engine_vlm_fallback.py tests/test_intelligent_analysis_engine_vlm_merge_policy.py -q
python -m pytest tests/test_qwen_vlm_final_e2e_acceptance.py -q
python -m pytest tests/test_timeline_image.py tests/test_demo_seed_event_pipeline.py tests/test_event_pipeline_e2e_smoke.py -q
python -m py_compile app/events/vlm.py app/events/vlm_adapter.py app/events/vlm_prompt.py app/events/analysis_engine.py app/events/timeline_image.py app/core/config.py scripts/seed_event_pipeline_demo.py
git diff --check
```

Observed local results:

- VLM adapter/http/qwen/prompt guard: 25 passed.
- Intelligent analysis fallback/merge policy: 14 passed.
- Qwen VLM final E2E acceptance: 10 passed.
- Timeline/demo seed/event pipeline smoke: 15 passed.
- Event API/schema/smoke/final E2E focused regression: 23 passed.
- All `tests/test_event_*.py`: 93 passed.
- `py_compile`: passed.
- `git diff --check`: passed with only existing LF/CRLF warnings.

## Conclusion

C-line VLM/Qwen review is ready for A/B/C final integration acceptance as an
optional advisory layer. A real Qwen endpoint remains not connected, not enabled
by default, and not approved for production until the preflight checklist in
`docs/qwen_vlm_real_endpoint_preflight.md` is completed.
