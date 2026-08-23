# P2 8000 Controlled Restart Plan

Status: `WAITING_FOR_APPROVAL_RESTART_8000`  
Date: 2026-07-19  
This document is a plan only. It does not approve or perform a restart.

## Purpose And Authority

The current `8000` process predates the backend source-redaction schema change.
The frontend already avoids filling or displaying raw source data, but a
controlled restart is required before the backend `/status` and `/stream/start`
redaction implementation can become the running process behavior.

`8000` is the approved realtime path. Restarting it can interrupt video and
WebRTC clients; it must not occur without the explicit user reply:

```text
批准重启 8000
```

## Preconditions

- [ ] Named operator and a presentation-free maintenance window are available.
- [ ] Current `8000` `/healthz`, `/demo/`, `/status` safe summaries are saved.
- [ ] `.env` SHA256 is recorded without copying its contents.
- [ ] Original launch profile is known to the operator without exposing RTSP,
  credentials, token values, paths or process command lines in the report.
- [ ] Event pipeline, DeliveryOutbox, VLM/Ollama and main-system alert are
  confirmed disabled on `8000`.
- [ ] Rollback operator can restore the exact prior approved launch profile.

## Controlled Steps

1. Record safe pre-restart summaries: `/healthz`, `/demo/`, event status,
   redacted `/status` field presence, and `.env` SHA256.
2. Gracefully stop only the current `8000` service process.
3. Restart it with the existing approved realtime configuration. Do not write
   `.env`, add a target URL, or enable sidecars.
4. Wait for `/healthz` HTTP 200, then verify stream health and `/demo/`.
5. Run the post-restart checks below and the source-redaction regression tests.
6. Write `docs/p2_8000_restart_redaction_acceptance_YYYYMMDD.md` with safe
   summaries only.

## Post-Restart Acceptance

| Area | Required result |
| --- | --- |
| Health | `/healthz` is 200 and normal service state is restored. |
| Main path | Main and analysis stream states are connected; no camera-loss regression. |
| Browser | `/demo/` opens; WebRTC and WS reach connected; overlay and REST results continue. |
| Event boundary | `/events/status` keeps pipeline and VLM disabled. |
| Status redaction | Public `/status` has no raw `source_url`, RTSP credential, token or local path. |
| Start response | `/stream/start` exposes only a masked stream URL; test only with an approved safe request, never a real credential. |
| Legacy contract | `FallFusionService` decision logic and `FallEventReporterService` remain unchanged. |
| Configuration | `.env` SHA256 is unchanged; no real POST, VLM/Ollama, Kafka, Redis or Celery is enabled. |

Required regressions:

```powershell
python -m pytest tests/test_stream_source_redaction.py tests/test_event_api.py -q
python -m py_compile app/schemas/status.py app/services/status_service.py app/api/rest_api.py
```

## Decision Rules

- `PASS`: service recovers, realtime transport and stream checks pass, backend
  redaction is effective, and configuration is unchanged.
- `REVISE`: main path works and no sensitive data leaks, but a nonblocking
  diagnostic or presentation issue remains documented.
- `BLOCKED`: service cannot recover, stream/WebRTC/WS fails materially, a
  sensitive field leaks, or `.env` changed.

## Rollback

Stop the newly started `8000` process and restore the prior approved launch
profile only. Do not restore by copying credentials into a document or editing
`.env`. Keep event pipeline, DeliveryOutbox, VLM/Ollama and main-system alert
disabled. Verify `/healthz`, `/demo/`, realtime stream state and `.env` hash
after restoration. Preserve logs for diagnosis; do not delete SQLite or
archives as part of a restart rollback.
