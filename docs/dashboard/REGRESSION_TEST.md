# REGRESSION_TEST

## Static Checks

- PASS: `node --check frontend_demo/dashboard-adapter.js`
- PASS: `node --check frontend_demo/app.js`
- PASS: DOM ID check found no missing IDs referenced by `app.js` or `dashboard-adapter.js`.
- PASS: Figma React/Vite project was not copied into the production frontend.

## Runtime Checks

| Check | Result | Notes |
|---|---|---|
| FastAPI startup | PASS | Verified with local safe runtime on `127.0.0.1:8000`. |
| `/demo` page load | PASS | Returned 200 and included dashboard title plus adapter script. |
| `/demo/styles.css` | PASS | Returned 200 and contained dashboard grid styles. |
| `/demo/dashboard-adapter.js` | PASS | Returned 200 and contained `__VISION_DASHBOARD__` renderer. |
| `/healthz` | PASS | Returned `{"status":"ok"}`. |
| `/status` | PASS | Returned service status JSON. |
| `/runtime-control/status` | PASS | Returned Binary/Qwen/Test control state; default Binary and Qwen stayed OFF. |
| `/events/status` | PASS | Returned disabled event pipeline status in the local safe runtime. |
| `/events/latest?camera_id=camera_01` | PASS | Returned `{"enabled":false,"event":null}` in the local safe runtime. |
| Browser page smoke test | PASS | 5 summary cards rendered, no console errors/warnings, no horizontal overflow. |
| Startup blank-screen check | PASS | Dashboard HTML now includes a critical dark background, deferred scripts, and first-paint-before-polling startup. New cache-busted asset version rendered 5 cards by `DOMContentLoaded`. |
| 1366x768 layout | PASS | Three-column grid and five-card summary rendered without horizontal overflow. |
| 1920x1080 layout | PASS | Three-column grid and five-card summary rendered without horizontal overflow. |
| Idle fallback polling | PASS | Browser resource timing showed 0 `/stream/latest-frame.jpg` requests during idle dashboard load with no fresh backend frame. |
| Binary button wiring | PASS | UI remained disabled without stream; direct API returned 409 `请先连接视频流。` |
| Qwen button wiring | PASS | UI remained disabled while Binary was OFF. |
| Start/stop test wiring | PASS | `test/start`, status read, and `test/stop` succeeded. |
| Video connection | NOT RUN | Real Go2 video frames were not available in this local verification environment. A failed source correctly displayed connecting/stale state instead of fake online data. |
| Real fall event flow | NOT RUN | Requires replay or real event trigger with available video frames. |
| Main-system delivery | NOT RUN | Requires configured reachable main-system endpoint and a real confirmed event. |

## Notes

The dashboard adapter is display-only. Production alert sending remains in backend services and existing manual diagnostic buttons only fire on explicit user action.
