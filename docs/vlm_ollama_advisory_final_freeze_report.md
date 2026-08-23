# VLM Ollama Advisory Final Freeze Report

Date: 2026-07-18
Owner: Engineer C
Freeze marker: `VLM_OLLAMA_ADVISORY_FREEZE_READY`

## Final Conclusion

The event-level VLM/Ollama advisory line is freeze-ready as a default-disabled,
fail-open, advisory-only reserved capability.

Current recommended status: `KEEP_DISABLED`.

The default review path remains `RuleAnalyzer` / rule review. Local
Ollama/Qwen is retained only as an optional event-level advisory enrichment
path and is not enabled by default.

## Current Capability

- `dummy` provider for deterministic local contract testing.
- `http` provider shell for future controlled HTTP providers.
- `qwen_http` legacy/mock provider shell; not the current recommended path.
- `ollama`, `qwen_ollama`, and `ollama_qwen` compatibility provider names.
- Local Ollama text-only payload builder.
- Advisory-only merge into `TrustedEventResult`.
- Fail-open fallback on provider failure.
- Timeout, invalid JSON, and schema error fallback.
- Demo seed scenarios for candidate, confirmed, high ADL, missing keyframes,
  timeout, and invalid JSON.
- `scripts/evaluate_ollama_advisory_review.py` for small-sample local
  evaluation.

## Current Evaluation Result

| Evaluation | Cases | Result | Recommendation |
| --- | ---: | --- | --- |
| Dry-run synthetic evaluation | 6 | 4 parse-success advisory cases, 1 simulated timeout, 1 simulated invalid JSON, zero path leaks, zero policy violations | `ALLOW_DEMO_ONLY` dry-run signal only |
| `qwen-vision-cn:latest` local smoke | 1 | 15 second timeout, fail-open to rules | `KEEP_DISABLED` |
| `qwen3.5:9b` local smoke | 1 | 15 second timeout, fail-open to rules | `KEEP_DISABLED` |

The current system does not meet the enablement gate.

## Enablement Gate

Any future enablement must pass all of these gates:

- At least 5 consecutive structured text-only events.
- `parse_success >= 80%`.
- Average latency `<= 8s`.
- Single-call latency `<= 15s`.
- `policy_violation_count=0`.
- `local_path_leak_count=0`.
- Rule-confirmed events are not downgraded.
- Candidate events are not confirmed by VLM alone.
- Timeout and invalid JSON fail open to `RuleAnalyzer`.
- Operators can disable the feature with one configuration change.

## Why KEEP_DISABLED

- Both local model candidates timed out at the 15 second advisory budget.
- The real local sample size is insufficient for staging or default demo use.
- The latency budget is not currently compatible with the event review
  experience.
- Timeout is correctly handled, but timeout handling is not an enablement pass.
- The project should not enter image input or timeline-image VLM stages until
  text-only review is stable.

## Re-Evaluation Conditions

Re-evaluate only when:

- Ollama model response is stable on the target machine.
- The evaluation starts with text-only 5 to 10 event samples.
- Latency and parse-success gates are met.
- Privacy and advisory-only policy checks remain clean.
- Demo-only can be disabled immediately.
- Timeline image evaluation is considered only after text-only review passes.

## Main Chain Impact

This freeze does not modify or replace:

- `FallFusionService`
- `FallEventReporterService`
- `/integration/fall-alerts/poll`
- WebRTC / WebSocket / REST realtime outputs

The realtime rule/fusion path remains authoritative.
