# CHANGELOG

## 2026-08-31

- Converted the existing demo page into a data-dashboard presentation for `智脉康养 · 移动视觉跌倒检测大屏`.
- Preserved the original plain HTML/CSS/JavaScript stack.
- Preserved existing backend APIs, WebRTC display flow, fallback frame flow, result WebSocket, model toggles, test controls, event APIs, and alerting diagnostics.
- Added `dashboard-adapter.js` as a display-only mapping layer for status cards, video overlay labels, link status, performance summaries, Qwen JSON summary, and pipeline node states.
- Reworked `styles.css` for a dark blue technical dashboard visual style inspired by the Figma reference.
- Reworked `index.html` into header, five summary cards, left status/control column, central live video, right event/Qwen/alarm column, bottom pipeline, and collapsible engineering diagnostics.
- Avoided Figma demo data such as robot dog fleets, ward/person/nurse mock data, simulated Qwen output, RealSense, YOLOv8-Pose, and patrol metrics.
- Reduced duplicate frontend polling by removing nested control/discovery refresh calls from the main status refresh path.
- Gated the existing latest-frame fallback polling so opening the dashboard while idle does not continuously request still frames before there is a live connection path or fresh backend frame.
- Improved first-screen startup by adding a critical dark background, changing dashboard scripts to `defer`, moving initial polling until after first paint, and bumping asset versions to avoid stale browser cache.
