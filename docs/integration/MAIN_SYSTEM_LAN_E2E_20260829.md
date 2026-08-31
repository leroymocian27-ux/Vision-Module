# Main System LAN E2E Report 2026-08-29

## Summary

Final result: **FAIL, blocked at TEST B**.

Blocking class: **E main system FastAPI**.

Reason: the camera-service PC can reach `192.168.8.254:8000` over TCP, but the final integration health endpoint
`GET /api/integrations/fall-detection/health` did not return `200 ok=true`. A direct request first returned `404 Not Found`, and later requests to the same main-system service timed out. Per the requested acceptance order, TEST C-H and the real fall test were not executed.

## Network Identity

| Item | Value | Evidence |
| --- | --- | --- |
| Main system IPv4 | `192.168.8.254` | User confirmed current main-system IP. TCP preflight reached this host. |
| Camera-service PC IPv4 | `192.168.8.253` | `Test-NetConnection` source address. |
| Main system URL | `http://192.168.8.254:8000` | Site configuration and preflight target. |
| Camera-service local URL during latest-code probe | `http://127.0.0.1:8001` | Temporary latest-code uvicorn probe. Existing `127.0.0.1:8000` was occupied by an older local process. |

## Protocol Diff

| Field | Expected final protocol | camera-service current alignment | Evidence |
| --- | --- | --- | --- |
| HTTP method | `GET` health, `POST` alerts | Implemented | `app/api/alerting_api.py:59`, `app/services/fall_event_reporter_service.py:244` |
| Alert path | `/api/integrations/fall-detection/alerts` | Implemented and configured | `app/core/config.py:464`, `app/services/fall_event_reporter_service.py:1600` |
| Health path | `/api/integrations/fall-detection/health` | Implemented and configured | `app/core/config.py:468`, `app/services/fall_event_reporter_service.py:391` |
| Content-Type | JSON via `requests.post(json=...)` | Implemented | `app/services/fall_event_reporter_service.py:244` |
| Token header | `X-Vision-Service-Token` unless final main-system report says otherwise | Configured as single header; token value from `MAIN_SYSTEM_INTEGRATION_TOKEN`, fallback `MAIN_SYSTEM_ALERT_TOKEN` | `app/core/config.py:478`, `app/services/fall_event_reporter_service.py:1456` |
| `event_id` | PFV2 `FallEvent.incident_id` | Implemented | `app/post_fall_v2/post_fall_runtime_service.py:1018`, `app/services/fall_event_reporter_service.py:1300` |
| `schema_version` | `1.0` | Implemented | `app/services/fall_event_reporter_service.py:1333` |
| `safety_outcome` | `alert` only | Implemented | `app/post_fall_v2/post_fall_runtime_service.py:973`, `app/services/fall_event_reporter_service.py:706` |
| `alert_type` | `fall` | Implemented | `app/services/fall_event_reporter_service.py:1341` |
| `event_time` | Event timestamp | Implemented | `app/services/fall_event_reporter_service.py:1301`, `app/services/fall_event_reporter_service.py:1339` |
| `sent_at` | Send timestamp | Implemented | `app/services/fall_event_reporter_service.py:1272`, `app/services/fall_event_reporter_service.py:1340` |
| `test_event` | `true` for manual test | Implemented | `app/services/alert_simulator_service.py:260` |
| ACK `event_id` | Must match local event id | Enforced; mismatch stays retryable | `app/services/fall_event_reporter_service.py:264` |
| ACK `duplicate` | `true` still delivered | Implemented | `app/services/fall_event_reporter_service.py:278` |

Main-system source check: `D:\Program\410health` currently exposes the old `video-bridge` receiver only in the searched code:

| Main-system item | Observed implementation |
| --- | --- |
| Existing old receiver | `D:\Program\410health\backend\api\video_bridge_api.py:15`, prefix `/video-bridge`, mounted under `/api/v1` |
| Existing old duplicate response | `D:\Program\410health\backend\api\video_bridge_api.py:20` to `:24`, returns `incident_id` and `duplicate` |
| Existing websocket | `D:\Program\410health\backend\main.py:283`, `/ws/alarms` |
| New final `/api/integrations/fall-detection/...` routes | Not found by repository search in `D:\Program\410health`, `D:\Program\410health_git`, `D:\Program\410health_release`, `D:\Program\410health_publish_clean`, `D:\Program\410health_backups` |

## Camera-Service Changes In This Pass

Necessary code/config changes were made to support real A-H verification:

1. `.env`: set `MAIN_SYSTEM_BASE_URL=http://192.168.8.254:8000`, `MAIN_SYSTEM_ALERT_ENABLED=true`, `MAIN_SYSTEM_REPORT_DRY_RUN=false`, new alert/health paths, token header, and outbox enabled.
2. `configs/original_camera_79.env`: set the same main-system base URL and enabled outbox for current-camera field use.
3. `configs/production_candidate.env`: updated the documented main-system IP to `192.168.8.254`; preserved its conservative disabled/dry-run profile.
4. `app/schemas/alerting.py`, `app/api/alerting_api.py`, `app/services/alert_simulator_service.py`: `POST /alerting/simulation/send-once` now accepts optional `event_id` for duplicate testing and reuses reporter delivery evidence.
5. `app/services/fall_event_reporter_service.py`: added `send_external_alert_once()` so manual probes use the same `main_system_alert.json`, `main_system_delivery.json`, ACK validation, and outbox path as real alerts.
6. `tests/test_alerting_manual_send.py`: updated tests to cover reporter-backed manual sends and explicit duplicate `event_id`.

No EfficientNet, ONNX model, `POST_FALL_V2_SAMPLE_FPS`, video decoding, MJPEG, Qwen prompt, or `follow_target` behavior was modified.

## Preflight Results

| Check | Result | Evidence |
| --- | --- | --- |
| `MAIN_SYSTEM_BASE_URL` configured | PASS on latest-code probe | `/alerting/status` returned base URL `http://192.168.8.254:8000` |
| `MAIN_SYSTEM_REPORT_DRY_RUN=false` | PASS on latest-code probe | `/alerting/status` returned `dry_run=false` |
| `MAIN_SYSTEM_ALERT_ENABLED=true` | PASS on latest-code probe | `/alerting/status` returned `enabled=true` |
| `ALERT_OUTBOX_ENABLED=true` | PASS on latest-code probe | `/status` showed outbox `enabled=true` |
| Health reachable | FAIL | `GET http://192.168.8.254:8000/api/integrations/fall-detection/health` returned `404 Not Found` once, then timed out |
| Token can pass | NOT TESTED | Health route failed before token validation could be distinguished |
| Current local `8000` is not old uvicorn | FAIL | `127.0.0.1:8000/alerting/status` showed old endpoint `http://127.0.0.1:8090/api/v1/video-bridge/fall-events`, `dry_run=true` |
| GPU Conda Python | PASS for local `8000` and latest-code `8001` probe | Process path `E:\MathModelingTools\conda-envs\camera-service-gpu\python.exe` |
| Port `8000` has only expected service | FAIL for latest code | Local `8000` occupied by PID `30176`, old config. Latest code was tested on temporary `8001`. |

Additional local observation: the latest-code `8001` probe logged `follow_target` UDP port `8766` already in use. This was not investigated further because this pass did not enter video/model testing and the task explicitly forbids changing `follow_target` without log proof.

## Ordered A-H Acceptance

| Test | Result | Evidence / Reason |
| --- | --- | --- |
| TEST A TCP | PASS | `TcpTestSucceeded=True`, remote `192.168.8.254:8000`, source `192.168.8.253`, interface `WLAN` |
| TEST B Health | FAIL | Direct `GET /api/integrations/fall-detection/health` did not return `200 ok=true`; observed `404 Not Found` and later read timeout |
| TEST C Test event | NOT RUN | Blocked by TEST B failure |
| TEST D Duplicate | NOT RUN | Blocked by TEST B failure |
| TEST E Non-alert | CODE/UNIT PASS, live not run | Gate exists at PFV2 and reporter; live sequence blocked by TEST B |
| TEST F Disconnect | NOT RUN | Blocked by TEST B failure |
| TEST G Recover | NOT RUN | Blocked by TEST B failure |
| TEST H Restart camera-service | NOT RUN | Blocked by TEST B failure |

## Real Fall Test

Not run.

Reason: TEST A-H were not all PASS. The requested rule says not to start a human fall test until A-H pass.

Fields not available because the test was correctly stopped:

| Field | Status |
| --- | --- |
| Real fall `event_id` | NOT AVAILABLE |
| `safety_outcome` | NOT AVAILABLE |
| Main-system ACK | NOT AVAILABLE |
| Main-system popup | NOT AVAILABLE |
| Main-system JSON/database record | NOT AVAILABLE |
| Duplicate alarm check | NOT AVAILABLE |
| HTTP impact on realtime video/model | NOT AVAILABLE |

## Expected Evidence Paths After Main-System Fix

For the next run, camera-service should produce these files under:

`E:\国赛\event\<camera_id>\<event_id>\`

Required files:

1. `event.json`
2. `qwen_review.json`
3. `main_system_alert.json`
4. `main_system_delivery.json`

`main_system_delivery.json` must end with:

1. `status=delivered`
2. `attempts >= 1`
3. `last_http_status=200`
4. `delivered_at` populated
5. `ack.event_id` equal to local `event_id`

## Verification Commands Run

```powershell
Test-NetConnection 192.168.8.254 -Port 8000
Invoke-WebRequest -UseBasicParsing -Uri 'http://192.168.8.254:8000/api/integrations/fall-detection/health' -TimeoutSec 5
Invoke-WebRequest -UseBasicParsing -Uri 'http://192.168.8.254:8000/openapi.json' -TimeoutSec 8
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/alerting/status' -TimeoutSec 3
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8001/alerting/status' -TimeoutSec 5
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8001/alerting/main-system/health' -TimeoutSec 8
Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8001/status' -TimeoutSec 5
python -m py_compile app/services/alert_simulator_service.py app/services/fall_event_reporter_service.py app/api/alerting_api.py app/schemas/alerting.py
python -m pytest tests/test_fall_event_reporter_service.py tests/test_alerting_manual_send.py tests/test_async_workers_and_outbox.py tests/test_integration_connection_status.py tests/test_device_connection_discovery.py tests/test_post_fall_v2_runtime_service.py -q
```

Test result:

`62 passed in 6.86s`

## Next Required Main-System Fix

Before rerunning TEST C-H, the main system at `192.168.8.254:8000` must expose and serve:

1. `GET /api/integrations/fall-detection/health`
2. `POST /api/integrations/fall-detection/alerts`

The health endpoint must return HTTP `200` with `ok=true`. The alerts endpoint must return:

```json
{
  "ok": true,
  "event_id": "<same event_id>",
  "duplicate": false,
  "received_at": "<timestamp>"
}
```

For an exact duplicate `event_id`, it must return `duplicate=true` and must not emit a second frontend popup.

