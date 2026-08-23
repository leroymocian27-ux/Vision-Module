# Formal Demo Execution Record Template

Use this document only after a complete formal rehearsal or formal presentation.
Do not fill a field from synthetic, mock, replay, or real-camera evidence of a
different scope. Preserve `NOT_RUN` when a step was not actually performed.

## Controlled Operator Commands

Run the following in the VS Code operator terminal. The first command remains
in the foreground and starts a loopback-only synthetic instance; it never
writes `.env`.

```powershell
.\scripts\run_formal_demo_8011.ps1
```

`8011` is the preferred port. If it is occupied by an unrelated process, do
not stop that process. Use a documented, loopback-only fallback port only after
the presenter approves it; record the deviation in the execution evidence.

In a second terminal, after the `8011` health endpoint is available, seed only
the required synthetic candidate event into the isolated runtime storage:

```powershell
python scripts\seed_event_pipeline_demo.py `
  --incident-id demo-rehearsal-20260718-candidate `
  --camera-id camera_01 `
  --scenario fall_candidate_support `
  --clear-demo `
  --db tmp_event_visual_qa\formal_demo_execution_20260718\event_outbox.sqlite3 `
  --archive-dir tmp_event_visual_qa\formal_demo_execution_20260718\archive `
  --delivery-db tmp_event_visual_qa\formal_demo_execution_20260718\delivery_outbox.sqlite3 `
  --seed-delivery-dry-run
```

Then run the safe dual-instance check:

```powershell
python scripts\check_formal_demo_preflight.py `
  --live-url http://127.0.0.1:8000 `
  --demo-url http://127.0.0.1:8011 --json
```

Collect the P1 API evidence summary without storing raw responses or images:

```powershell
python scripts\capture_formal_demo_evidence.py `
  --output tmp_event_visual_qa\formal_demo_execution_20260718\p1_api_summary.json
```

Stop the foreground `8011` process with `Ctrl+C` after recording the results;
then repeat the read-only `8000` health check. Do not use this process for real
RTSP, real main-system POST, VLM/Ollama, or real-confirmed acceptance.

## Result

```yaml
formal_demo_execution: NOT_RUN
presentation_type: rehearsal_or_formal_demo
actual_env_modified: false
real_main_system_post: false
event_vlm_enabled: false
ollama_called: false
production_ready: false
```

## Instance Boundary

| Instance | Observed state | Result |
| --- | --- | --- |
| `8000` realtime presentation | `TODO: health, video, WebRTC, WS, sidecar disabled` | `NOT_RUN` |
| `8011` local synthetic review | `TODO: loopback only, demo seed, dry-run, VLM disabled` | `NOT_RUN` |

## Ordered Evidence

| Step | Expected result | Actual safe summary | Result |
| --- | --- | --- | --- |
| `8000 /healthz` | healthy | `TODO` | `NOT_RUN` |
| `8000 /demo/` | realtime video and overlay | `TODO` | `NOT_RUN` |
| `8000` WebRTC and WS | connected | `TODO` | `NOT_RUN` |
| `8000` event pipeline | disabled | `TODO` | `NOT_RUN` |
| `8011 /healthz` | healthy | `TODO` | `NOT_RUN` |
| `8011 /events/status` | sidecar enabled; VLM disabled | `TODO` | `NOT_RUN` |
| candidate selection | manual `demo-rehearsal-20260718-candidate` selection | `TODO` | `NOT_RUN` |
| six keyframes | each returns `200 image/jpeg` | `TODO` | `NOT_RUN` |
| rule review | fallback/rule result visible | `TODO` | `NOT_RUN` |
| delivery | `dry_run_sent`, never real POST | `TODO` | `NOT_RUN` |
| browser console | no persistent warning/error | `TODO` | `NOT_RUN` |
| privacy check | no RTSP, token, path, source URL, raw status shown | `TODO` | `NOT_RUN` |
| shutdown check | `8011` closed and `8000` still healthy | `TODO` | `NOT_RUN` |

## Evidence And Speaking Boundary

- Screenshot paths: `TODO: safe relative project paths only`.
- Synthetic confirmed comparison: `NOT_RUN`; if used, record it as synthetic only.
- Real POST: `false`.
- VLM/Ollama call: `false`.
- Real-camera acceptance: `NOT_RUN` unless separately documented under P3.
- Real algorithm `fallen_confirmed` acceptance: `NOT_RUN` unless separately documented under P4.

Use the wording in `docs/formal_demo_preflight_check_20260718.md`. The
presentation record must not claim a production alert, production readiness,
real confirmed detection, or VLM-based decision-making from the synthetic demo.
