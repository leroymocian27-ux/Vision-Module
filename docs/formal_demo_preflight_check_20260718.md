# Formal Demo Preflight Check 2026-07-18

## Result

```yaml
formal_demo_preflight: PASS
scope: read_only_preflight
production_ready: false
actual_env_modified: false
real_main_system_post: false
event_vlm_enabled: false
ollama_called: false
```

This is a preflight record for a formal demonstration. It is not a real-camera,
real-algorithm-confirmed, or production-delivery acceptance result.

## Instance Boundary

| Instance | Permitted purpose | Required state |
| --- | --- | --- |
| `8000` | Approved realtime presentation only. | `FallFusionService` remains authoritative; event sidecar and VLM disabled. |
| `8011` | Optional temporary local synthetic event-review demo. | Loopback-only, isolated storage, mock/synthetic data, six demo frames, delivery dry-run, VLM disabled. |

The two instances must be explained as separate demonstration surfaces, not as
one production event path.

## Current Read-Only Checks

| Check | Result | Safe evidence only |
| --- | --- | --- |
| `8000 /healthz` | PASS | HTTP 200 and `status=ok`. |
| `8000 /demo/` | PASS | HTTP 200 HTML response. |
| `8000 /events/status` | PASS | `event_pipeline_enabled=false`; no response body retained. |
| `8011` listener | PASS | Not running before the demonstration. |
| `.env` | PASS | Not modified by this preflight. |

Run the repeatable read-only check immediately before the presentation:

```powershell
python scripts/check_formal_demo_preflight.py --live-url http://127.0.0.1:8000 --json
```

When the temporary `8011` instance is intentionally running, include it:

```powershell
python scripts/check_formal_demo_preflight.py --live-url http://127.0.0.1:8000 --demo-url http://127.0.0.1:8011 --json
```

Use `scripts/run_formal_demo_8011.ps1` in an operator terminal to start the
temporary instance with the required process-scoped configuration. The exact
candidate seed and shutdown procedure are in
`docs/formal_demo_execution_record_template.md`.

The checker only permits credential-free HTTP loopback addresses, never starts
services, never changes configuration, and emits no raw response fields.

## Operator Checklist

- [ ] Confirm `8000` shows only realtime video and the event sidecar is disabled.
- [ ] Confirm the presenter does not display raw `/status` JSON, terminal command lines, RTSP controls, credentials, tokens, or local paths.
- [ ] If `8011` is used, confirm it is bound to `127.0.0.1`, delivery is dry-run, and VLM/Ollama is disabled.
- [ ] Select `demo-rehearsal-20260718-candidate` manually in Recent Events.
- [ ] Do not use **Latest** as the formal event-selection method: a mock runtime may add a newer unrelated record.
- [ ] If showing `demo-rehearsal-20260718-confirmed-synthetic`, state that it is a synthetic UI/data-structure comparison, not a real algorithm-confirmed event.
- [ ] Confirm six relative keyframe URLs load and the browser console has no persistent warning or error.

## Pass Criteria

- `PASS`: both selected instances meet the required state; no sensitive field is displayed; the presenter uses the approved boundary language.
- `REVISE`: the demonstration remains safe but a noncritical presentation check needs correction.
- `BLOCKED`: `8000` is unhealthy, event/VLM state is unsafe, a sensitive field is visible, or the selected demo event cannot be safely shown.

## Required Demonstration Language

Say that realtime fall detection is decided by `FallFusionService`; the event
semantic pipeline is a non-blocking evidence and review sidecar. Say that
`dry_run_sent` verifies delivery handling without sending a real alert, and
that `FallEventReporterService` remains the formal alert path. Do not claim
that a large model decides falls, that dry-run is a real alarm, or that this
preflight proves production readiness.
