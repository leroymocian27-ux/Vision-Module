# Event Frontend Visual QA

## Scope

This QA note covers the `/demo/` Event Semantic Review panel only. The realtime video, WebRTC connection, WebSocket result channel, canvas overlay, raw status, and diagnostics panels must remain visible and unchanged by the event evidence-chain UI.

## Viewports To Check

- 1920px desktop or projector view
- 1366px laptop view
- 1024px tablet/narrow desktop view
- 768px narrow view

## Required Checks

- Event panel does not cover the video viewer.
- Keyframe timeline wraps instead of overflowing.
- Keyframe images use fixed card dimensions and do not stretch the layout.
- Long `incident_id`, `explanation`, `uncertainty`, and `degradation_used` text wraps inside the panel.
- Delivery retry/error text and VLM advisory text wrap inside the panel and do not expose full internal URLs.
- Timeline Image either renders from a relative `/events/...` URL or shows the no-image state.
- Raw Status and Diagnostics remain reachable.
- Console has no error/warn flood.

## State Checks

### Disabled

Expected:

- Pipeline badge shows disabled.
- Empty state shows `事件语义链路未启用`.
- Six timeline cards are present as placeholders.
- No keyframe images are requested.

### No Event

Expected:

- Pipeline is enabled but no event is selected.
- Empty state shows `暂无事件归档`.
- Recent Events list shows an empty state.

### Event Ready

Expected:

- Event summary fields are populated.
- Explanation and recommended action are readable.
- Archive and delivery status are visible.
- Timeline shows six fixed offsets.

### Partial Keyframes

Expected:

- Missing cards show `missing_reason`.
- Available cards use relative `/events/...` keyframe URLs.
- Image load failures show `关键帧不可用`.

## Current Manual Result

Checked with `/demo/?v=event-review-next-final-check` while the event pipeline was disabled:

- Event panel showed disabled state.
- Six keyframe cards existed.
- Video and overlay DOM nodes existed.
- Raw Status and Diagnostics existed.
- Browser console had no warning/error entries during the check.

## Current Automated Browser Result

Checked on `2026-07-17` with Chrome headless/CDP against:

- Seed event page: `http://127.0.0.1:8000/demo/?v=event-demo-cdp-check2`
- Disabled page: `http://127.0.0.1:8011/demo/?v=event-disabled-cdp-check`

Seed event source:

```powershell
python .\scripts\seed_event_pipeline_demo.py --incident-id codex-demo-evidence-b5 --camera-id camera_01 --event-type fall_candidate
```

Viewport results:

| Width | Incident | Cards | Loaded images | Horizontal overflow | Console warn/error |
| --- | --- | ---: | ---: | --- | --- |
| 1920 | `codex-demo-evidence-b5` | 6 | 6 | no | none |
| 1366 | `codex-demo-evidence-b5` | 6 | 6 | no | none |
| 1024 | `codex-demo-evidence-b5` | 6 | 6 | no | none |
| 768 | `codex-demo-evidence-b5` | 6 | 6 | no | none |

Observed seed event fields:

- `event_type=fall_candidate`
- `fall_state=fallen_candidate`
- `risk_level=high`
- `confidence=90%`
- `delivery_status=delivery_pending`
- `archive_status=archived (6 saved / 0 missing)`
- `explanation=Dev/demo synthetic event for validating event archive and keyframe UI.`
- `recommended_action=Review the demo timeline. Do not treat this as a real alarm.`

Disabled-state result:

- Pipeline badge: `disabled`
- Empty state: `事件语义链路未启用`
- Timeline cards: 6
- Keyframe image requests: 0
- Video, overlay, Raw Status, and Diagnostics nodes: present
- Horizontal overflow: no
- Console warn/error: none

Generated local QA artifacts:

- `tmp_event_visual_qa/cdp_event_visual_result.json`
- `tmp_event_visual_qa/cdp_disabled_result.json`
- `tmp_event_visual_qa/cdp_eventpanel_1920.png`
- `tmp_event_visual_qa/cdp_eventpanel_1366.png`
- `tmp_event_visual_qa/cdp_eventpanel_1024.png`
- `tmp_event_visual_qa/cdp_eventpanel_768.png`

## Integrated Field QA

The final integrated panel adds A/C-line fields on top of the previous layout:

- Event summary: camera, track, event status, result source.
- Intelligent review: review result, observed process, risk interpretation, ADL likelihood, VLM advisory state.
- Delivery: mode, dry-run marker, retry count, next retry time, delivered time, backend, redacted last error.
- Timeline Image: safe URL image when provided, otherwise a no-image or archived-only text state.

Required viewport result for the final integrated review:

| Width | Expected result |
| --- | --- |
| 1920 | No horizontal overflow; event panel stays separate from the video viewer. |
| 1366 | No horizontal overflow; delivery/VLM text wraps inside the right rail. |
| 1024 | Event panel stacks below the main viewer; timeline wraps. |
| 768 | Single-column/narrow layout remains readable; video/overlay/raw/diagnostics nodes remain present. |

Latest integrated browser check should use:

`http://127.0.0.1:8000/demo/?v=event-final-integrated-review`

Current integrated result on `2026-07-18`:

| Width | Incident | Cards | Loaded images | Horizontal overflow | Console warn/error | Main nodes |
| --- | --- | ---: | ---: | --- | --- | --- |
| 1920 | `codex-final-integrated-b` | 6 | 6 | no | none | video/overlay/raw/diagnostics present |
| 1366 | `codex-final-integrated-b` | 6 | 6 | no | none | video/overlay/raw/diagnostics present |
| 1024 | `codex-final-integrated-b` | 6 | 6 | no | none | video/overlay/raw/diagnostics present |
| 768 | `codex-final-integrated-b` | 6 | 6 | no | none | video/overlay/raw/diagnostics present |

Observed integrated fields:

- Event summary showed `camera_01`, track `1`, `fall_candidate`, `fallen_candidate`, `high`, and `86%`.
- Result source showed `事件级复核 / 规则`.
- VLM state showed `VLM 复核未启用，当前为规则复核结果`.
- Delivery state showed `暂无投递状态`, `not configured`, backend `memory`, and no last error.
- Timeline Image showed `事件过程图已归档，当前未开放前端访问 URL`.

Disabled integrated result on `2026-07-18`:

- URL: `http://127.0.0.1:8011/demo/?v=event-final-integrated-review-disabled`
- Pipeline badge: `disabled`
- Empty state: `事件语义链路未启用`
- Timeline cards: 6
- Keyframe image requests: 0
- Delivery state: `暂无投递状态`
- VLM state: `VLM 复核未启用`
- Horizontal overflow: no
- Console warn/error: none
- Video, overlay, Raw Status, and Diagnostics nodes: present

Generated local QA artifacts:

- `tmp_event_visual_qa/integrated_event_visual_result.json`
- `tmp_event_visual_qa/integrated_disabled_result.json`
- `tmp_event_visual_qa/integrated_eventpanel_1920.png`
- `tmp_event_visual_qa/integrated_eventpanel_1366.png`
- `tmp_event_visual_qa/integrated_eventpanel_1024.png`
- `tmp_event_visual_qa/integrated_eventpanel_768.png`

## Known Limits

- Real camera event playback still needs replay or demo seed validation when no physical fall event is available.
- The UI does not fabricate events.
- Archive image serving is intentionally scoped to event keyframe API URLs.

## Final E2E Showcase Browser QA 2026-07-18

Final E2E URL:

`http://127.0.0.1:8000/demo/?v=event-final-e2e-showcase`

Disabled-state URL:

`http://127.0.0.1:8011/demo/?v=event-final-e2e-showcase-disabled`

Final seed incident:

`codex-final-e2e-showcase-b`

Viewport result:

| Width | Incident | Cards | Loaded images | Horizontal overflow | Console warn/error | Main nodes |
| --- | --- | ---: | ---: | --- | --- | --- |
| 1920 | `codex-final-e2e-showcase-b` | 6 | 6 | no | none | video/overlay/raw/diagnostics present |
| 1366 | `codex-final-e2e-showcase-b` | 6 | 6 | no | none | video/overlay/raw/diagnostics present |
| 1024 | `codex-final-e2e-showcase-b` | 6 | 6 | no | none | video/overlay/raw/diagnostics present |
| 768 | `codex-final-e2e-showcase-b` | 6 | 6 | no | none | video/overlay/raw/diagnostics present |

Observed final seed fields:

- `risk_level=high`
- `confidence=86%`
- `delivery_status=模拟投递完成`
- `dry_run=是，模拟投递`
- `vlm_status=VLM 复核未启用，当前为规则复核结果`
- Timeline Image showed archived-only/no-frontend-URL state because no safe `timeline_image_url` was provided.
- All six keyframe images loaded through `/events/codex-final-e2e-showcase-b/keyframes/...`.

Disabled result:

- Empty state: `事件语义链路未启用`
- Timeline cards: 6
- Keyframe image requests: 0
- Horizontal overflow: no
- Console warn/error: none
- video/overlay/Raw Status/Diagnostics nodes: present

Generated final artifacts:

- `tmp_event_visual_qa/final_e2e_console_check.json`
- `tmp_event_visual_qa/final_e2e_seed_1920.png`
- `tmp_event_visual_qa/final_e2e_seed_1366.png`
- `tmp_event_visual_qa/final_e2e_seed_1024.png`
- `tmp_event_visual_qa/final_e2e_seed_768.png`
- `tmp_event_visual_qa/final_e2e_disabled_1366.png`
- `tmp_event_visual_qa/final_e2e_delivery_dry_run.png`
- `tmp_event_visual_qa/final_e2e_vlm_disabled.png`
