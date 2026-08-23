# Vision Service API Reference

Generated at: 2026-06-09 19:20 Asia/Shanghai

Last updated: 2026-06-09 21:24 Asia/Shanghai

Base URL for local service:

```text
http://127.0.0.1:8000
```

Interactive OpenAPI pages:

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/openapi.json
```

## Current Runtime Status

- Backend health: OK, `GET /healthz` returned `{"status":"ok"}`.
- Backend listen address: `0.0.0.0:8000`.
- Camera source: `mock://colorbars`.
- Fall event reporter endpoint currently reported by runtime:

```text
http://192.168.8.254:8000/api/v1/video-bridge/fall-events
```

- Detection model is not fully loaded in the current runtime: `No module named 'ultralytics'`.
- The current host IPv4 is `192.168.8.253`, gateway `192.168.8.1`.
- Current main-system connection test succeeded:

```text
GET  http://192.168.8.254:8000/healthz
GET  http://192.168.8.254:8000/api/v1/video-bridge/status
POST http://192.168.8.254:8000/api/v1/video-bridge/fall-events
```

The latest simulated fall event sent through the Vision Service backend returned `ok=true`, `accepted=true`, and `pushed=true`.

## Main System Push Contract

Vision Service sends fall events to the main system using:

```http
POST http://<MAIN_SYSTEM_IP>:8000/api/v1/video-bridge/fall-events
X-Vision-Service-Token: <MAIN_SYSTEM_ALERT_TOKEN>
Content-Type: application/json
```

The frontend manual alert button only accepts an IP. The backend appends:

```text
:8000/api/v1/video-bridge/fall-events
```

Recommended behavior for repeated tests:

- Use a new `incident_id` for every push.
- Use a new `track_id` for every push if the main system deduplicates by `camera_id + track_id`.
- Treat `409` as "main system received the event but did not create a new alarm" rather than a network failure.
- Treat timeout or connection refused as network/service reachability failure.

## Status APIs

### `GET /healthz`

Health check.

Response example:

```json
{
  "status": "ok"
}
```

### `GET /status`

Returns full runtime state.

Query parameters:

```text
camera_id optional, default camera_01
```

Important response fields:

```text
service_status
cameras[]
detection[]
streaming
tracking
identity
pose
behavior
temporal
pipeline
latest_result
fall_event_reporter
main_stream
analysis_stream
diagnostics
```

### `GET /alerting/status`

Returns current alert endpoint and simulator status.

Response example:

```json
{
  "endpoint": {
    "base_url": "http://192.168.8.254:8000/api/v1",
    "path": "/video-bridge/fall-events",
    "enabled": true
  },
  "simulation": {
    "running": false,
    "interval_seconds": 2.0,
    "target_url": "http://192.168.8.254:8000/api/v1/video-bridge/fall-events",
    "camera_id": "camera_01",
    "track_id": "smoke-track",
    "sent_count": 0,
    "last_status": null,
    "last_error": null,
    "last_sent_at": null,
    "last_payload": null
  }
}
```

## Alerting APIs

### `POST /alerting/endpoint`

Updates the runtime alert endpoint.

Request:

```json
{
  "base_url": "http://192.168.8.254:8000/api/v1",
  "path": "/video-bridge/fall-events",
  "enabled": true
}
```

### `POST /alerting/simulation/send-once`

Sends one simulated fall alert to a target IP. This does not start a background loop.

Request:

```json
{
  "target_ip": "192.168.8.254",
  "camera_id": "camera_01",
  "track_id": "manual-console-probe",
  "fall_prob": 0.91
}
```

Backend target URL:

```text
http://<target_ip>:8000/api/v1/video-bridge/fall-events
```

Response:

```json
{
  "ok": true,
  "target_url": "http://192.168.8.254:8000/api/v1/video-bridge/fall-events",
  "status_code": 200,
  "response_body": "{\"ok\":true,\"accepted\":true,\"pushed\":true,\"alarm_id\":\"98d2da62-0485-4e9a-84aa-afe30cc5aef9\"}",
  "error": null,
  "sent_at": "2026-06-09T13:23:59.688+00:00",
  "incident_id": "vision-fall-smoke-camera_01-manual-console-probe-..."
}
```

### `POST /alerting/simulation/start`

Starts continuous simulated fall alert sending.

Request:

```json
{
  "target_ip": "192.168.8.254",
  "interval_seconds": 2.0,
  "camera_id": "camera_01",
  "track_id": "smoke-track",
  "fall_prob": 0.91
}
```

Alternative request with explicit base URL:

```json
{
  "base_url": "http://192.168.8.254:8000/api/v1",
  "path": "/video-bridge/fall-events",
  "interval_seconds": 2.0,
  "camera_id": "camera_01",
  "track_id": "smoke-track",
  "fall_prob": 0.91
}
```

### `POST /alerting/simulation/stop`

Stops continuous simulated alert sending.

## Stream APIs

### `POST /stream/start`

Starts a camera stream.

Request:

```json
{
  "camera_id": "camera_01",
  "rtsp_url": "mock://colorbars",
  "main_rtsp_url": null,
  "analysis_rtsp_url": null
}
```

### `POST /stream/stop`

Stops a camera stream.

Request:

```json
{
  "camera_id": "camera_01"
}
```

### `GET /stream/source`

Returns current source state.

Query parameters:

```text
camera_id optional, default camera_01
```

### `GET /stream/latest-frame.jpg`

Returns the latest camera frame as JPEG.

Query parameters:

```text
camera_id optional, default camera_01
```

### `POST /stream/probe`

Checks whether a stream host and port are reachable.

Request:

```json
{
  "host": "192.168.8.254",
  "port": 10554,
  "timeout_ms": 1500
}
```

### `POST /stream/switch-host`

Switches camera RTSP host.

Request:

```json
{
  "camera_id": "camera_01",
  "host": "192.168.8.254",
  "username": "admin",
  "password": "<camera password>",
  "port": 10554,
  "main_path": "/tcp/av0_0",
  "analysis_path": "/tcp/av0_1",
  "scheme": "rtsp"
}
```

## WebRTC APIs

### `POST /webrtc/offer`

Creates a WebRTC peer answer.

Request:

```json
{
  "camera_id": "camera_01",
  "sdp": "<offer sdp>",
  "type": "offer"
}
```

Response:

```json
{
  "peer_id": "<peer id>",
  "sdp": "<answer sdp>",
  "type": "answer"
}
```

### `POST /webrtc/candidate`

Adds an ICE candidate.

Request:

```json
{
  "peer_id": "<peer id>",
  "candidate": {}
}
```

## Integration APIs

### `GET /integration/results/{camera_id}/latest`

Returns the latest analysis result for a camera.

Example:

```text
GET /integration/results/camera_01/latest
```

## Identity APIs

### `POST /identity/enroll`

Enrolls an identity. See OpenAPI schema for the current request body.

### `GET /identity/list`

Lists enrolled identities.

### `DELETE /identity/{person_id}`

Deletes an enrolled identity.

## Snapshot API

### `GET /fall-events/snapshots/{filename}`

Returns a fall-event snapshot image by filename.

## Current Main-System Connection Result

Command result through local API:

```json
{
  "ok": true,
  "target_url": "http://192.168.8.254:8000/api/v1/video-bridge/fall-events",
  "status_code": 200,
  "response_body": "{\"ok\":true,\"accepted\":true,\"pushed\":true,\"alarm_id\":\"98d2da62-0485-4e9a-84aa-afe30cc5aef9\"}",
  "error": null,
  "incident_id": "vision-fall-smoke-camera_01-console-config-probe-..."
}
```

Suggested checks for the main-system side:

- Confirm the main system server current IP is still `192.168.8.254`.
- Confirm it listens on `0.0.0.0:8000`, not only `127.0.0.1:8000`.
- Confirm `/api/v1/video-bridge/fall-events` is mounted.
- Confirm Windows/Linux firewall allows inbound TCP `8000`.
- Confirm both machines are on a routable network or the correct VPN/interface is active.
- Confirm this machine `192.168.8.253` is allowed to reach `192.168.8.254:8000`.
