# DASHBOARD_ARCHITECTURE

## Design Approach

The Figma React project is treated as `UI_REFERENCE` only. The implemented page keeps the existing plain HTML/CSS/JavaScript frontend and reuses the current APIs, WebRTC flow, WebSocket flow, model controls, test controls, event APIs, and alerting diagnostics.

## Layout

- Header: system title, business chain subtitle, WebRTC/WebSocket/Stream status, browser-local clock.
- Status summary: five cards for video stream, Binary model, Qwen model, current event, and main-system linkage.
- Main dashboard: left 24 percent, center primary video, right event analysis.
- Center video: existing `video#video`, `img#frameFallback`, and `canvas#overlay` nodes are preserved.
- Pipeline: `视频输入 -> 二分类筛查 -> 千问复核 -> JSON生成 -> 主系统告警`.
- Engineering drawer: lower collapsible area for pairing, manual alert probe, detailed target diagnostics, event evidence chain, raw status, and performance details.

## Adapter

`frontend_demo/dashboard-adapter.js` is a thin presentation adapter. It reads already-fetched frontend state and maps it to visual cards, overlay labels, and pipeline node states.

It does not:

- Open an extra WebSocket.
- Open an extra MJPEG/WebRTC stream.
- Poll APIs by itself.
- Send alerts.
- Decide whether a fall happened.
- Invent CPU, GPU, FPS, confidence, person, ward, nurse, or alarm ACK values.

## Integration Points

`frontend_demo/app.js` calls `renderDashboard()` after these existing update points:

- `/status` refresh.
- `/runtime-control/status` refresh.
- `/ws/results` message.
- video quality sampling.
- normalized event panel render.

This keeps a single data flow: backend state and event streams update existing frontend state, then the dashboard adapter renders the presentation.

## Performance Notes

- The video path is unchanged.
- The annotated overlay remains disabled by `ANNOTATED_OVERLAY_ENABLED = false`.
- No particle background, WebGL scene, or high-frequency chart was added.
- Existing polling intervals are kept lightweight; a nested runtime-control refresh inside `/status` was removed to reduce duplicate requests.
