# P3-P5 Real Source Acceptance Preparation

Status: `WAITING_FOR_AUTHORIZED_REAL_RTSP_OR_REPLAY`  
Date: 2026-07-19  
This document prepares acceptance only. No real test is started by it.

## Authorized Input Requirements

- Written authorization for a real camera or a real fall replay, plus a named
  owner and an agreed test window.
- A source reachable from the approved test host and safe to interrupt only as
  agreed with its owner.
- RTSP URL, account, password, token and full network address remain outside
  source control, screenshots, reports and terminal captures. Reports use a
  neutral source label only.
- A separate rollback contact and a resource-monitoring method are available.

Mock, seed, synthetic and unrelated replay material cannot be labelled as a
real-camera result. A synthetic confirmed record cannot substitute for a real
or authorized-replay `fallen_confirmed` result.

## P3 Round A: Realtime Baseline

Run with event pipeline disabled for at least 30 minutes. Record timestamps,
uptime, WebRTC and WS states, REST freshness, capture/detect/publish FPS,
frame age and latency, reconnect count, `camera_lost`, `capture_stale`,
`inference_slow`, CPU, memory and GPU/VRAM. Preserve only redacted source
identity.

`PASS` requires stable realtime outputs without an unexplained disconnect or
material resource regression. `REVISE` permits a bounded, diagnosed issue.
`BLOCKED` applies when the source is unavailable, unsafe, repeatedly unstable,
or a sensitive value is exposed.

## P3 Round B: Event Sidecar Comparison

After Round A, temporarily enable only the event sidecar in a controlled
session. Delivery remains `dry_run`; VLM/Ollama, image input, main-system POST
and legacy alert changes remain disabled. Run 30-60 minutes and compare Round A
metrics. Also record event API availability, SQLite outbox growth, archive
growth, browser console status and any keyframe collection state.

`PASS` requires no material degradation relative to Round A. Immediately stop
the sidecar and return to the approved baseline on realtime regression,
unexpected external activity, disk/capacity risk or privacy exposure.

## P4: Real Or Authorized-Replay Confirmed Event

Use only an authorized real source/replay. Without changing thresholds to force
an outcome, observe `FallFusionService` output for `fallen_confirmed` or its
approved equivalent. Verify REST, WS, event detail, Event Semantic Review,
evidence, trusted result, archive summary, dry-run delivery and VLM disabled.

`PASS` requires a traceable real/replay source and the real algorithm result.
`BLOCKED` is required when the only proof is synthetic.

## P5: Real Six-Keyframe Evidence

For the P4 incident, validate T-3, T-1, T0, T+1, T+3 and T+5 individually via
safe keyframe API calls and the timeline UI. Record `evidence_status`,
`degradation_used`, missing slot and `missing_reason`. Only six accessible
frames with `evidence_status=complete` permit a complete-six-frame claim.

`REVISE` is allowed for correctly reported degradation. Never describe a
degraded package as complete or fill missing frames with synthetic data.

## Required Report Fields

Every P3-P5 report records: source class, authorization reference, time window,
uptime, WebRTC/WS, FPS, latency, frame age, error counters, CPU/memory/VRAM,
event and keyframe API results, archive/outbox changes, screenshots, console
status, safety flags and final `PASS / REVISE / BLOCKED` decision.
