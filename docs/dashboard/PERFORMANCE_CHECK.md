# PERFORMANCE_CHECK

## Frontend Load Changes

- Added one display-only adapter script: `frontend_demo/dashboard-adapter.js`.
- Did not add WebGL, canvas charts, particle effects, or high-frequency animation.
- Did not add an additional MJPEG, WebRTC, WebSocket, or backend polling loop.
- Removed one nested `refreshControlStatus()` call from `refreshStatus()` to avoid overlapping `/runtime-control/status` reads.
- Removed one nested `refreshDeviceDiscoveryStatus()` call from `refreshStatus()`; discovery status still refreshes on startup and after pairing actions.
- Gated the existing `/stream/latest-frame.jpg` fallback loop so an idle dashboard does not start 300ms frame polling until there is a user/frontend connection intent or a fresh backend frame.

## Runtime Observation

| Item | Result | Source |
|---|---|---|
| MJPEG/WebRTC display connections | PASS | Initial page load kept `webrtc_clients=0`. A user-triggered connection attempt created one WebRTC client only. |
| WebSocket connections | PASS | Initial page load kept `ws_clients=0`; failed/no-frame connection did not create duplicate WebSockets. |
| API polling | PASS | Dashboard adapter added no polling loop. Existing `/status`, `/runtime-control/status`, and `/events/*` intervals remain the only loops. |
| Video smoothness | NOT RUN | Real Go2 frames were unavailable, so live smoothness could not be judged. The no-frame path rendered without JS errors. |
| CPU/GPU impact | LIMITED PASS | No new high-cost rendering was added. Local runtime reported Binary provider degraded to `CPUExecutionProvider`; this was displayed as real status, not masked. |

## Browser Layout Checks

- PASS: default in-app browser viewport rendered without console errors or warnings.
- PASS: 1366x768 rendered without horizontal overflow.
- PASS: 1920x1080 rendered without horizontal overflow.
- PASS: idle dashboard load made 0 `/stream/latest-frame.jpg` requests before a live connection path or fresh backend frame existed.

## Expected Request Pattern

- `/status`: existing 2s polling.
- `/runtime-control/status`: existing 1s polling.
- `/events/status`: existing 5s polling.
- `/events/latest`: existing adaptive polling, normally 3s when enabled.
- `/events/outbox`: existing 5s polling.
- `/ws/results`: one WebSocket only after video connection.
- WebRTC: one peer connection only after `connectWebRTC()`.
- `/stream/latest-frame.jpg`: existing fallback loop only starts when WebRTC display needs fallback and either the user/frontend is connecting or `/status` reports a fresh backend frame.
