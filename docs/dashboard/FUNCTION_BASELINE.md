# FUNCTION_BASELINE

## Scope

This baseline was captured before the dashboard presentation upgrade on 2026-08-31. The project already had many uncommitted changes; those changes were preserved and were not reverted.

## Frontend Stack

- Frontend stack: plain HTML, CSS, and JavaScript.
- Static frontend directory: `frontend_demo/`.
- Mounted route: `/demo`, configured in `app/main.py` with `StaticFiles(directory=frontend_demo, html=True)`.
- Page entry: `frontend_demo/index.html`.
- CSS entry: `frontend_demo/styles.css`.
- JS entries before upgrade: `frontend_demo/overlay.js`, `frontend_demo/app.js`.
- JS entries after upgrade: `frontend_demo/dashboard-adapter.js`, `frontend_demo/app.js`.

## Video Display

- Primary display path: WebRTC.
- Video DOM node: `video#video`.
- WebRTC offer API: `POST /webrtc/offer`.
- ICE candidate API: `POST /webrtc/candidate`.
- Result WebSocket: `GET /ws/results?camera_id=...`.
- Fallback still frame API: `GET /stream/latest-frame.jpg?camera_id=...`.
- Stream start API: `POST /stream/start`.
- Stream stop API exists in backend: `POST /stream/stop`.
- Default page input value before upgrade: `http://192.168.8.254:8093/stream.mjpg`.

## Status APIs

- Overall service status: `GET /status?camera_id=...`.
- Runtime/model/test control status: `GET /runtime-control/status?camera_id=...`.
- Event pipeline status: `GET /events/status`.
- Latest event: `GET /events/latest?camera_id=...`.
- Recent event outbox: `GET /events/outbox?camera_id=...&limit=5`.
- Event detail: `GET /events/{incident_id}`.
- Event delivery status: `GET /events/delivery/status`.
- Device discovery status: `GET /device-discovery/status`.
- Alerting status: `GET /alerting/status`.
- Main system health probe: `GET /alerting/main-system/health`.

## Control Functions

- Connect video button: `connectWebRTC()`, which calls `startStreamRequest()` and then creates one WebRTC peer and one result WebSocket.
- Start stream button: `startStream()` -> `POST /stream/start`.
- Binary toggle button: `toggleBinaryModel()` -> `POST /runtime-control/binary`, then refreshes real control status.
- Qwen toggle button: `toggleQwenModel()` -> `POST /runtime-control/qwen`, then refreshes real control status.
- Start test button: `startTimedTest()` -> `POST /runtime-control/test/start`.
- Stop test button: `stopTimedTest()` -> `POST /runtime-control/test/stop`.
- Main system endpoint save: `POST /alerting/endpoint`.
- Manual alert probe: `POST /alerting/simulation/send-once`.

## Backend Source Of Truth

- Video state fields: `/status` cameras, `main_stream`, `analysis_stream`, `diagnostics`.
- Binary fields: `/runtime-control/status` `binary_enabled`, `binary_requested`, and `runtime.*`.
- Qwen fields: `/runtime-control/status` `qwen_enabled`, `qwen_requested`, `runtime.vlm_*`.
- Event fields: `/events/latest`, `/events/outbox`, `/events/{incident_id}`.
- Alarm fields: `/events/*` delivery record and `/status.fall_event_reporter`.
- Test fields: `/runtime-control/status.test`.

## Default Behavior

- Dashboard loading does not auto-enable Binary or Qwen.
- Existing auto frontend connection behavior is preserved: it may connect WebRTC only when the backend reports fresh frames and `manualConnect=1` is not present.
- The dashboard does not make fall decisions and does not send production alerts. It only displays backend results and keeps the existing manual alert probe as a user-triggered diagnostic.
