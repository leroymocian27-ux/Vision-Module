# Event Frontend Demo Notes

## Panel Fields

The Event Semantic Review panel is a read-only evidence-chain view for demo, debugging, and acceptance. It does not replace the realtime fall decision or the official alarm reporter.

The panel displays:

- Pipeline health: pipeline enabled/disabled, worker running/stopped, total outbox count, and outbox pending/processing/reviewed/failed counts.
- Event summary: `incident_id`, `camera_id`, `track_id`, `event_type`, `fall_state`, `risk_level`, `confidence`, event status, result source, and archive status.
- Semantic review: `review_result`, `explanation`, `recommended_action`, `uncertainty`, `degradation_used`, `observed_process`, `risk_interpretation`, `adl_likelihood`, and VLM advisory status.
- Delivery review: `delivery_status`, `delivery_mode`, `dry_run`, retry count, next retry time, delivered time, backend, and a redacted `last_error` summary.
- Recent events: up to five read-only outbox records from `/events/outbox?camera_id=<camera>&limit=5`; clicking an item loads `/events/{incident_id}`.
- Keyframe timeline: six fixed cards for `T-3s`, `T-1s`, `T0`, `T+1s`, `T+3s`, and `T+5s`.
- Keyframe metadata: `role`, `offset_ms`, `frame_seq`, `fall_state`, `risk_level`, `bbox`, `missing_reason`, and image availability.
- Timeline Image: displays a safe relative `timeline_image_url` when provided. Without a safe URL, the panel shows an archived-only or no-image state and does not request local files.

## Frontend States

- `disabled`: event pipeline is closed. The panel shows `事件语义链路未启用`, keeps timeline placeholders, and does not request images.
- `no_event`: pipeline is enabled but no event is available. The panel shows `暂无事件归档`.
- `event_ready`: event details and all known keyframes are available.
- `partial_keyframes`: event details are available, but one or more keyframes are missing or unavailable. Missing cards show the reason.
- `api_error`: event APIs are temporarily unavailable. The panel shows a non-blocking error state and avoids console error flooding.

## Recent Event Reading

The panel defaults to the latest event. The `Recent Events` list is read-only and uses the current page camera ID. Selecting a row loads that event detail without changing backend state. The `Latest` button clears the selected incident and returns to automatic latest-event rendering.

## Delivery Status Text

Delivery is a read-only side path and does not replace `FallEventReporterService`.

| Raw status | UI text | Notes |
| --- | --- | --- |
| `dry_run_sent` | `模拟投递完成` | Never shown as formal production delivery. |
| `sent` with `delivery_mode=post` and `dry_run=false` | `已投递` | Formal post delivery only. |
| `retry` | `等待重试` | Shows retry count and `next_retry_at` when present. |
| `failed` | `投递失败` | Shows a redacted `last_error`; tokens, full URLs, and local paths are suppressed. |
| `pending` | `等待投递` | Read-only pending state. |
| `sending` | `投递中` | Read-only sending state. |
| missing/null/disabled | `暂无投递状态` | Safe default when DeliveryOutbox is disabled or no record exists. |

The frontend never displays `lock_token`. It does not mutate DeliveryOutbox records and does not call delivery worker actions.

## VLM / Qwen Advisory Fields

VLM is optional and remains disabled by default. The Event Semantic Review panel treats VLM output as event-level advisory explanation, not the realtime first decision.

Compatible fields:

- `vlm_provider`
- `vlm_latency_ms`
- `observed_process`
- `risk_interpretation`
- `adl_likelihood`
- `uncertainty`
- `alarm_title`
- `alarm_body`
- `recommended_action`
- `review_result`
- `degradation_used`
- `timeline_image_url`

When VLM is closed or fields are absent, the UI shows `VLM 复核未启用，当前为规则复核结果` and continues to render the rule result. `degradation_used` is shown as compact tags. `uncertainty` is converted into short readable labels instead of dumping raw JSON.

## Keyframe Timeline Meaning

- `T-3s`: pre-context before the suspected fall.
- `T-1s`: immediate pre-fall frame.
- `T0`: trigger frame.
- `T+1s`: early post-fall frame.
- `T+3s`: post-fall confirmation context.
- `T+5s`: later post-check context.

The timeline is meant to support the demo explanation: the system not only reports an alarm, it also shows the evidence chain before, at, and after the fall.

## keyframe_url Rules

`/events/latest` and `/events/{incident_id}` add a frontend summary to each evidence keyframe:

- `label`: timeline label such as `T0` or `T+5s`.
- `available`: true only when the archived image path is valid and the file exists.
- `missing_reason`: the archived reason, or a generated unavailable reason.
- `keyframe_url`: a relative API URL only when `available=true`.

Stable keyframe IDs:

- `t_minus_3s` for `-3000`
- `t_minus_1s` for `-1000`
- `t0` for `0`
- `t_plus_1s` for `1000`
- `t_plus_3s` for `3000`
- `t_plus_5s` for `5000`

Example URL: `/events/{incident_id}/keyframes/t0`. The API also supports `/events/{incident_id}/keyframes/by-offset/{offset_ms}`.

## Keyframe API Safety

Keyframe bytes are served only by `GET /events/{incident_id}/keyframes/{keyframe_id}` or the by-offset variant. The API finds the outbox record first, then resolves the selected `EvidencePackage.keyframes[*].image_path` relative to that event archive.

Safety rules:

- No local absolute paths are returned to the frontend.
- Raw image bytes are never embedded in JSON.
- The whole `logs` directory and the whole archive directory are not mounted.
- Absolute paths, Windows drive-letter paths, empty path segments, and `..` traversal are rejected.
- The resolved file must remain under `EVENT_ARCHIVE_DIR` and under the selected incident archive directory.
- Missing events, missing keyframes, disabled pipeline state, and missing files return HTTP 404 with a clear `detail.reason`.

## Demo Honesty

The production UI does not hard-code fake events. If no real or replayed event exists, the panel must show `暂无事件归档`. Visual validation may use test data, a mock API, or seeded outbox records, but the acceptance notes should mark that path as replay/mock validation.

## Demo Seed Validation

Current B5 validation used the existing dev/demo seed script only as an input source:

```powershell
python .\scripts\seed_event_pipeline_demo.py --incident-id codex-demo-evidence-b5 --camera-id camera_01 --event-type fall_candidate
```

The service was then started temporarily with:

```powershell
$env:EVENT_PIPELINE_ENABLED="true"
$env:EVENT_OUTBOX_BACKEND="sqlite"
$env:EVENT_OUTBOX_SQLITE_PATH="data/event_outbox.sqlite3"
$env:EVENT_ARCHIVE_ENABLED="true"
$env:EVENT_ARCHIVE_DIR="logs/event_archive"
```

Observed result on `2026-07-17`:

- `/events/latest?camera_id=camera_01` returned `incident_id=codex-demo-evidence-b5`.
- The response contained six relative `/events/codex-demo-evidence-b5/keyframes/...` URLs.
- No local absolute archive path was exposed in the public response.
- All six keyframe image APIs returned `200 image/jpeg`.
- `/demo/?v=event-demo-cdp-check2` rendered the seeded event, summary, explanation, recommended action, archive status, and timeline.
- Browser/CDP checks at 1920, 1366, 1024, and 768 widths loaded six keyframe images with no console warn/error entries.
- This remains dev/demo validation only; the frontend did not fabricate an event.

## Manual Acceptance

1. Start the service and open `/demo/?v=event-final-integrated-review`.
2. With `EVENT_PIPELINE_ENABLED=false`, confirm the event panel shows `事件语义链路未启用`, six timeline placeholders exist, video/overlay are present, and the browser console has no error/warn flood.
3. Enable event pipeline/archive flags and trigger or seed an archived event.
4. Confirm `/events/latest?camera_id=<camera>` contains relative `keyframe_url` values and no Windows absolute paths.
5. Confirm the panel shows `incident_id`, `camera_id`, `track_id`, `risk_level`, `confidence`, `review_result`, `explanation`, `recommended_action`, delivery/archive state, VLM/rule review state, and six keyframe cards.
6. Confirm missing keyframes show `missing_reason`.
7. Confirm failed image loads show `关键帧不可用`.
8. Confirm realtime video, overlay, raw status, and diagnostics still work.

## Current Limits

- Real VLM is not connected.
- Kafka and Redis are not connected.
- Events are not fabricated by the UI.
- Keyframe images display only when the event pipeline is enabled and an archive exists.
- Archive image serving is local to archived event records and is not a general static file server.

## Tests

```powershell
python -m pytest tests/test_event_api.py tests/test_event_keyframe_api.py tests/test_event_archive.py -q
node --check frontend_demo/app.js
git diff --check
```

## Final Demo Notes 2026-07-18

本轮 Final E2E showcase 使用 `codex-final-e2e-showcase-b` 作为 dev/demo seed 事件，并额外生成本地 SQLite dry-run delivery 记录用于展示。该输入只用于演示/验收，不是生产事件，也没有向主系统发送 POST。

演示时建议按以下顺序讲：

1. 先说明实时视频和 overlay 仍是主链路，事件面板是旁路证据链。
2. 展示 Pipeline 状态。如果关闭，说明“事件语义链路未启用”，页面仍保持稳定。
3. 展示事件摘要：`incident_id`、摄像头、track、风险等级、置信度。
4. 展示智能复核：解释规则复核、降级原因和 VLM disabled/fallback。
5. 展示 Delivery：`dry_run_sent` 只能解释为“模拟投递完成”，不能说成正式推送主系统。
6. 展示关键帧时间轴：`T-3s`、`T-1s`、`T0`、`T+1s`、`T+3s`、`T+5s`。
7. 展示 Timeline Image：有安全相对 URL 时显示图片；没有时显示未提供或仅归档状态。

边界话术：

- 不说“大模型直接判断跌倒”。
- 不说“已经正式推送主系统”，除非状态明确为 `sent + post + dry_run=false` 并经过单独验收。
- 不说“系统能医疗诊断老人受伤情况”。
- 不把 demo seed 或 dry-run 解释成生产实报。

异常解释：

- no event：当前没有事件归档，面板显示“暂无事件归档”。
- missing keyframe：关键帧缺失或未归档，卡片显示 `missing_reason`。
- image load failed：前端显示“关键帧不可用”，不请求本地路径。
- VLM disabled：当前是规则复核结果，VLM 可选且默认关闭。
- Delivery disabled/missing：当前没有投递状态，正式主系统告警链路仍保持原状。
