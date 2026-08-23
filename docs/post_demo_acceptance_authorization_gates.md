# Post-Demo Acceptance Authorization Gates

This document turns the post-demo roadmap into a strict execution order. It
does not approve a restart, real-camera test, main-system request, or VLM call.

## Current State

```yaml
formal_demo_preflight: PASS
formal_demo_execution: PASS
formal_demo_execution_scope: synthetic_demo_only
formal_demo_port: 8135
approved_8000_restart: false
authorized_real_rtsp: false
authorized_main_system_staging: false
ollama_advisory_admission: REVISE
production_ready: false
```

## Gate 1: Source-Redaction Restart

**Unlock condition:** explicit user approval to restart the existing `8000`
process.

**Allowed action:** controlled stop/start only; preserve `.env`, leave event
pipeline, Delivery, VLM, and main alert disabled.

**Required evidence:** health, realtime video, WebRTC, WS, REST, masked stream
response, and no raw source URL in public status output. Record only redacted
summaries in `docs/status_redaction_restart_acceptance_YYYYMMDD.md`.

## Gate 2: Real RTSP And Evidence

**Unlock condition:** an authorized real RTSP source supplied through an
approved operational channel. Do not place the URL or credentials in source,
tests, screenshots, terminal captures, or documentation.

**Required order:**

1. Round A, event sidecar disabled, 30 minutes minimum.
2. Round B, event sidecar temporarily enabled with Delivery dry-run and VLM
   disabled, 30-60 minutes.
3. Real-camera or real-replay `fallen_confirmed` accepted by
   `FallFusionService` without synthetic seeding.
4. Verify T-3, T-1, T0, T+1, T+3, and T+5 keyframes individually. Only six
   safe `200 image/jpeg` responses and `evidence_status=complete` permit a
   complete-six-frame claim.

**Required records:** `real_rtsp_round_ab_acceptance`,
`real_fallen_confirmed_acceptance`, and
`real_stream_keyframe_completeness`, each dated when actually run.

## Gate 3: Delivery Staging And Canary

**Unlock condition:** Gate 2 passes, a receiver contract identifies endpoint,
method, acknowledgement, idempotency behavior, timeout, retry policy, token
header, and accountable owner, and the user explicitly approves staging.

**Required order:** local mock -> isolated staging receiver -> one-camera
canary. Every stage must be able to return to dry-run immediately. The legacy
`FallEventReporterService` remains intact and must not cause duplicate alerts.

**Forbidden until unlocked:** production endpoint calls, hard-coded tokens, and
any change to the actual `.env`.

## Gate 4: Local Ollama Advisory

**Unlock condition:** a separate evaluation plan for the local loopback model.
The current result is `REVISE`, not an approval.

**Required evidence:** bounded latency, JSON-only schema compliance, timeout
and invalid-JSON fallback, concurrency/resource limits, privacy review, and
human quality review. Inputs remain synthetic/redacted structured text only;
images, keyframes, paths, URLs, incident IDs, and track IDs remain forbidden.

The advisory result may enrich explanations only. It must never change the
authoritative `FallFusionService` decision or delay realtime outputs.

## Gate 5: Production Handover

Only after Gates 1-4 have actual dated evidence may the final handover choose
`PRODUCTION_READY_WITH_LIMITS`. Until then the only valid conclusion is
`DEMO_READY_ONLY`, `STAGING_READY_ONLY`, or `BLOCKED`, according to the
completed evidence.
