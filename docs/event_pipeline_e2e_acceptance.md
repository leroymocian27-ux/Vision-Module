# Event Pipeline E2E Acceptance

## Scope

The smoke path validates synthetic event records from `VisionResult` through:

```text
EventOutbox -> EvidencePackage -> EventSemantics -> TrustedEventResult
-> EventArchive -> Event API -> frontend keyframe summary
```

Realtime detection remains authoritative and unchanged.

## C-Line Freeze

The VLM/Ollama advisory line is frozen under
`VLM_OLLAMA_ADVISORY_FREEZE_READY`.

Current recommendation is `KEEP_DISABLED`. Ollama is default-off, text-only, and
advisory-only. The event semantic pipeline continues to use `RuleAnalyzer` as
the stable default review mechanism. No image input, timeline-image VLM review,
external Qwen endpoint, or realtime first-decision integration is enabled.

## Covered Scenarios

- Pipeline disabled: no outbox writes and no publisher/reporter interruption.
- Pipeline enabled with worker disabled: event remains `pending`.
- Worker lifecycle: `pending -> processing -> evidence_ready -> semantic_ready -> reviewed -> delivery_pending`.
- Missing keyframes: evidence, semantics, and trusted result are still produced with degradation.
- Confirmed fall: rule result keeps support enabled and risk is not downgraded to low.
- High ADL suppression: candidate becomes review/unsupported rather than confirmed.
- SQLite outbox: records can be reopened and retry state persists.
- Archive enabled: JSON files are written even when frames are missing.
- Archive enabled: timeline image summary uses relative `timeline/timeline.jpg`.
- Event API: `/events/latest` returns keyframe summaries without local absolute paths.
- VLM failures: timeout, invalid JSON, and generic failure preserve the rule result.
- VLM disabled with `EVENT_VLM_PROVIDER=qwen_http`: no adapter call and rule-only result.
- Qwen/HTTP no-image skip: no request is made and `vlm_skipped_no_images` is recorded.
- C-line Final E2E: disabled, dummy, http mock, qwen_http mock, timeout,
  invalid JSON, schema error, missing images, confirmed disagreement, candidate
  enrichment, high ADL review, and API path redaction.
- Local Ollama text-only: disabled by default, mock success, unavailable
  fallback, timeout fallback, invalid JSON fallback, and payload privacy.
- Ollama advisory evaluation: script-level dry-run, loopback-only endpoint
  guard, local-path leak guard, policy guard, latency/fallback reporting, and
  conservative enablement recommendation.

## Rule/VLM Strategy Matrix

| Rule result | VLM advisory | ADL | Final policy |
| --- | --- | --- | --- |
| confirmed | any | any | Keep confirmed; never downgrade to low. |
| confirmed | not support | any | Keep confirmed and add `vlm_disagree` uncertainty. |
| candidate | support | low | Keep rule-supported candidate and enrich explanation/action. |
| candidate | support | high | Add uncertainty/review context; do not upgrade to confirmed. |
| candidate | not support | high | Review/unsupported according to rule result. |
| review/unsupported | support | low | Advisory only; do not directly confirm. |
| any | timeout/invalid/failed | any | Use rule result and append degradation. |
| any | qwen_http disabled | any | No VLM call; rule-only result. |
| any | no images for HTTP/Qwen | any | Skip before request and append `vlm_skipped_no_images`. |

## Demo Seed Matrix

`scripts/seed_event_pipeline_demo.py` supports dev/demo-only scenarios:

- `fall_candidate_support`
- `fallen_confirmed_high`
- `adl_suppressed_review`
- `missing_keyframes`
- `vlm_timeout_fallback`
- `vlm_invalid_json_fallback`

These scenarios write synthetic outbox/archive records only when explicitly
run. They do not call the main-system alert path.

| Scenario | Expected review signal |
| --- | --- |
| `fall_candidate_support` | Candidate reaches `delivery_pending` with `need_attention`. |
| `fallen_confirmed_high` | Confirmed fall remains high/critical and supported. |
| `adl_suppressed_review` | High ADL suppression requires review/unsupported. |
| `missing_keyframes` | Evidence and timeline placeholders are still generated. |
| `vlm_timeout_fallback` | Rule result remains and `vlm_timeout` is recorded. |
| `vlm_invalid_json_fallback` | Rule result remains and `vlm_invalid_json` is recorded. |

## C-Line Final E2E Matrix

| Scenario | Test coverage |
| --- | --- |
| VLM disabled | `test_final_e2e_vlm_disabled_uses_rule_result` |
| Dummy provider | `test_final_e2e_dummy_provider_merges_explanation` |
| HTTP mock success | `test_final_e2e_http_provider_mock_success` |
| Qwen HTTP mock success | `test_final_e2e_qwen_http_provider_mock_success` |
| Timeout fallback | `test_final_e2e_timeout_fallback` |
| Invalid JSON fallback | `test_final_e2e_invalid_json_fallback` |
| Confirmed fall disagreement | `test_final_e2e_confirmed_not_downgraded_by_vlm_disagree` |
| Candidate high ADL review | `test_final_e2e_candidate_high_adl_goes_review` |
| Missing images skip | `test_final_e2e_missing_images_skips_vlm_safely` |
| Public API path safety | `test_final_e2e_no_absolute_path_in_public_summary` |

## Local Ollama Text-Only Matrix

| Scenario | Test coverage |
| --- | --- |
| Ollama disabled | `test_disabled_settings_do_not_build_ollama_adapter` |
| `ollama` provider config | `test_ollama_provider_builds_only_when_enabled` |
| `qwen_ollama` provider config | `test_qwen_ollama_provider_uses_configured_model` |
| Ollama unavailable | `test_connection_error_maps_to_adapter_error` |
| Ollama timeout | `test_timeout_is_typed` |
| Ollama invalid/schema error | `test_ollama_forbidden_decision_fields_do_not_override_rules` |
| Ollama valid JSON | `test_valid_ollama_json_returns_vlm_result` |
| Text-only payload safety | `test_payload_excludes_media_paths_and_base64` |
| Advisory-only merge | `test_candidate_ollama_support_only_enriches_advisory_fields` |

## P14 Ollama Advisory Evaluation Matrix

| Scenario | Test coverage |
| --- | --- |
| Evaluation script defaults to no real call | `test_default_effective_dry_run_does_not_call_ollama` |
| `--allow-local-ollama` gate | `test_allow_local_ollama_required_before_call` |
| Non-local endpoint rejection | `test_non_localhost_endpoint_is_rejected` |
| JSON/JSONL report output | `test_output_json_and_jsonl_format_are_written` |
| Insufficient samples stay conservative | `test_missing_samples_keep_recommendation_conservative` |
| Timeout fail-open | `test_timeout_records_degradation_and_generates_result` |
| Connection refused fail-open | `test_connection_refused_records_failed_degradation` |
| Slow response budget fallback | `test_slow_response_over_budget_can_fail_open` |
| Forbidden decision fields ignored/rejected | `test_ollama_advisory_policy_guard.py` |

## Commands

```powershell
python -m pytest tests/test_event_pipeline_e2e_smoke.py -q
python -m pytest tests/test_event_*.py -q
```

On PowerShell, expand the glob if needed:

```powershell
$files = Get-ChildItem tests -Filter 'test_event_*.py' | ForEach-Object { $_.FullName }
python -m pytest $files -q
```

## Non-Goals

The smoke test does not require a real camera, real VLM, Kafka, Redis, or a running service port.
