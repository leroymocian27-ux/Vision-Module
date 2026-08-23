# Ollama Qwen Advisory Evaluation Report

Date: 2026-07-18
Scope: Engineer C, event-level semantic advisory review only.

## Final Freeze

Freeze marker: `VLM_OLLAMA_ADVISORY_FREEZE_READY`.

Final recommendation: `KEEP_DISABLED`.

Local Ollama/Qwen remains a reserved advisory-only capability. The default path
is rule review through `RuleAnalyzer`. Do not enter timeline image or image-input
VLM phases until text-only review passes the enablement gate with real local
samples.

## Evaluation Goal

This report defines the P14 gate for deciding whether local Ollama/Qwen
text-only advisory review is suitable for demo enablement. It does not approve
production use and does not make VLM output authoritative.

## Current Default State

- `EVENT_VLM_ENABLED=false`
- `EVENT_VLM_PROVIDER=dummy`
- Ollama is not called by default.
- Image input is disabled.
- The local `.env` file is not modified by the evaluation.
- No keyframe paths, timeline paths, local absolute paths, base64 data, tokens,
  raw payloads, or lock tokens are sent.

## Tested Models

- Primary candidate: `qwen-vision-cn:latest`
- Comparison/fallback candidate: `qwen3.5:9b`

The first P14 script stage can evaluate either model with the same synthetic
cases. Vision-capable model names are allowed, but this phase remains text-only.

## Test Scenarios

- `fall_candidate_support`: candidate event with low ADL suppression; advisory
  text may enrich explanation and action, but must not confirm a fall alone.
- `fallen_confirmed_high`: confirmed/high-critical rule result; VLM disagreement
  must not downgrade the result.
- `adl_suppressed_review`: high ADL suppression; advisory review must not turn
  the event into a direct alarm.
- `missing_keyframes`: no usable keyframes; text-only review may explain
  structured semantics and should carry uncertainty.
- `vlm_timeout_fallback`: simulated timeout; the rule result must be returned.
- `vlm_invalid_json_fallback`: simulated invalid JSON; the rule result must be
  returned.

## Metrics

- Parse success count and ratio.
- Per-case latency and average latency.
- Timeout count.
- Invalid JSON count.
- Fallback count.
- Policy violation count.
- Local path leak count.
- Advisory-only compliance: no decision, risk, fall state, delivery status, or
  confirmed-fall override.

## Enablement Gates

The first demo gate is intentionally conservative:

- At least 5 consecutive structured event reviews.
- `parse_success >= 80%`.
- Average latency `<= 8s`.
- Single-call latency `<= 15s`.
- `local_path_leak_count=0`.
- `policy_violation_count=0`.
- Rule-confirmed events are never downgraded.
- Candidate events are never confirmed by VLM alone.
- Timeout and invalid JSON fail open to RuleAnalyzer.
- Demo operators can disable VLM with one configuration change.

## Status Values

- `KEEP_DISABLED`: default when samples are insufficient, parsing is unstable,
  policy violations occur, or local model latency is outside the budget.
- `ALLOW_DEMO_ONLY`: acceptable only for a controlled demo where rule results
  remain authoritative and VLM can be turned off immediately.
- `READY_FOR_STAGING`: requires enough real local samples, latency within
  budget, no path leaks, no policy violations, and stable fail-open behavior.

## Current P14 Result

The automated dry-run evaluation and mock failure tests pass. The dry-run
evaluation covered six synthetic scenarios, generated six trusted results,
reported four parse-success advisory cases, one simulated timeout fallback, one
simulated invalid-JSON fallback, zero path leaks, and zero policy violations.

Controlled local smoke was then run against `127.0.0.1:11434/api/chat` with one
sample per model:

| Model | Cases | Parse success | Timeout count | Average latency | Recommended status |
| --- | ---: | ---: | ---: | ---: | --- |
| `qwen-vision-cn:latest` | 1 | 0 | 1 | 15034.416 ms | `KEEP_DISABLED` |
| `qwen3.5:9b` | 1 | 0 | 1 | 15031.970 ms | `KEEP_DISABLED` |

Both local calls failed open with timeout degradation and still returned the
RuleAnalyzer result. No images, keyframe paths, timeline paths, local absolute
paths, base64 data, external endpoint, or main-system POST were used.

Recommended status: `KEEP_DISABLED`. The repeated 15 second timeout across both
local candidates suggests the current advisory latency budget is not yet
compatible with demo enablement on this machine.

## Evaluation Command

Dry-run, no local model call:

```powershell
python scripts/evaluate_ollama_advisory_review.py --max-cases 6
```

Controlled local smoke:

```powershell
python scripts/evaluate_ollama_advisory_review.py `
  --allow-local-ollama `
  --endpoint http://127.0.0.1:11434/api/chat `
  --model qwen-vision-cn:latest `
  --timeout 15 `
  --max-cases 2
```

Comparison model:

```powershell
python scripts/evaluate_ollama_advisory_review.py `
  --allow-local-ollama `
  --endpoint http://127.0.0.1:11434/api/chat `
  --model qwen3.5:9b `
  --timeout 15 `
  --max-cases 2
```

Do not use external endpoints, do not send images, and do not modify `.env`.
