# Event Frontend Final Acceptance

## Completed B-Line Capabilities

- Event keyframe API serves archived images through bounded event routes.
- `/events/latest` and `/events/{incident_id}` expose frontend-safe keyframe summaries.
- The `/demo/` Event Semantic Review panel displays pipeline health, event summary, semantic review text, recent events, archive/delivery status, and a six-point keyframe timeline.
- The panel accepts A-line DeliveryOutbox fields and C-line VLM/Qwen advisory fields without requiring those optional paths to be enabled.
- The Recent Events list reads `/events/outbox?camera_id=<camera>&limit=5` and selected rows load `/events/{incident_id}` without mutating backend state.
- Missing keyframes and failed images show explicit reasons.
- The panel degrades safely when the event pipeline is disabled, no event exists, or event APIs fail.

## API List

- `GET /events/status`
- `GET /events/outbox?status=&camera_id=&limit=`
- `GET /events/latest?camera_id=`
- `GET /events/{incident_id}`
- `GET /events/{incident_id}/keyframes/{keyframe_id}`
- `GET /events/{incident_id}/keyframes/by-offset/{offset_ms}`

Delivery read APIs may also be present when the delivery module is enabled:

- `GET /events/delivery/status`
- `GET /events/delivery/outbox`
- `GET /events/delivery/by-incident/{incident_id}`
- `GET /events/delivery/{delivery_id}`

## keyframe_url Rules

The frontend never receives image bytes in JSON. When a keyframe is available, JSON contains a relative URL:

`/events/{incident_id}/keyframes/{keyframe_id}`

Stable IDs:

- `t_minus_3s`
- `t_minus_1s`
- `t0`
- `t_plus_1s`
- `t_plus_3s`
- `t_plus_5s`

## Path Safety Strategy

- The API finds the event outbox record first.
- It selects a keyframe from the event `EvidencePackage`.
- It accepts only relative `keyframes/...` image paths.
- It rejects absolute paths, Windows drive-letter paths, empty segments, and `..`.
- It resolves the final file path and verifies it remains below `EVENT_ARCHIVE_DIR` and the selected incident archive directory.
- It never mounts the whole archive or logs directory.

## Frontend Fields

The event evidence panel displays:

- Pipeline: enabled/disabled, worker running/stopped, outbox counts.
- Recent Events: last five outbox records for the current camera.
- Event summary: incident, camera, track, type, fall state, risk, confidence, event status, result source, archive.
- Review text: review result, explanation, recommended action, uncertainty, degradation tags, observed process, risk interpretation, ADL likelihood, and VLM advisory state.
- Delivery text: delivery status, mode, dry-run marker, retry count, next retry time, delivered time, backend, and redacted last error.
- Timeline Image: safe relative image URL when provided, otherwise an archived-only or no-image state.
- Keyframes: label, role, offset, frame, state, risk, bbox, missing reason, image availability.

## State Handling

- Disabled: shows `事件语义链路未启用`.
- No event: shows `暂无事件归档`.
- Partial keyframes: shows missing reason per card.
- Image failure: shows `关键帧不可用`.
- API error: shows a non-blocking unavailable state and avoids console error flooding.
- Delivery missing: shows `暂无投递状态`.
- VLM disabled or missing: shows `VLM 复核未启用，当前为规则复核结果`.

## Final Integrated Review

The final B-line integration accepts fields from A-line DeliveryOutbox and C-line VLM/Qwen review without changing their producer logic.

Delivery compatibility:

- `delivery_status`
- `delivery_mode`
- `dry_run`
- `retry_count` / `attempt_count`
- `next_retry_at`
- `last_error`
- `delivered_at`
- `delivery_backend`

VLM/Qwen compatibility:

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

Safety rules:

- `dry_run_sent` is displayed as `模拟投递完成`, never as formal delivery.
- Formal `已投递` is reserved for `sent + post + dry_run=false`.
- `retry` displays retry count and next retry time when available.
- `failed` displays a redacted error summary; full internal URLs, local paths, tokens, and lock tokens are not shown.
- `lock_token` is never rendered.
- Timeline Image is loaded only from a relative `/events/...` API URL.
- Missing optional fields use safe defaults and never crash the page.

## Browser Acceptance Result

Checked disabled state on local service at:

`http://127.0.0.1:8000/demo/?v=event-review-next-final-check`

Observed:

- Disabled state rendered correctly.
- Six timeline cards existed.
- Pipeline/worker/outbox health rendered.
- Video and overlay nodes existed.
- Raw Status and Diagnostics nodes existed.
- Console warning/error list was empty during the check.

Checked seeded event state on `2026-07-17` at:

`http://127.0.0.1:8000/demo/?v=event-demo-cdp-check2`

Seed input:

```powershell
python .\scripts\seed_event_pipeline_demo.py --incident-id codex-demo-evidence-b5 --camera-id camera_01 --event-type fall_candidate
```

Temporary validation environment:

```powershell
EVENT_PIPELINE_ENABLED=true
EVENT_OUTBOX_BACKEND=sqlite
EVENT_OUTBOX_SQLITE_PATH=data/event_outbox.sqlite3
EVENT_ARCHIVE_ENABLED=true
EVENT_ARCHIVE_DIR=logs/event_archive
```

Observed seeded event:

- `incident_id=codex-demo-evidence-b5`
- `event_type=fall_candidate`
- `fall_state=fallen_candidate`
- `risk_level=high`
- `confidence=90%`
- `delivery_status=delivery_pending`
- `degradation_used=none`
- Explanation and recommended action rendered.
- Archive status rendered as `archived (6 saved / 0 missing)`.
- Recent Events contained the seeded incident.
- The timeline rendered `T-3s`, `T-1s`, `T0`, `T+1s`, `T+3s`, and `T+5s`.
- All six keyframe images loaded from `/events/codex-demo-evidence-b5/keyframes/...`.
- Browser/CDP checks at 1920, 1366, 1024, and 768 widths found no horizontal overflow and no console warn/error entries.
- Video, overlay, Raw Status, and Diagnostics DOM nodes remained present.

Checked current disabled state again on a temporary `EVENT_PIPELINE_ENABLED=false` service at:

`http://127.0.0.1:8011/demo/?v=event-disabled-cdp-check`

Observed:

- Pipeline badge showed `disabled`.
- Empty state showed `事件语义链路未启用`.
- Six timeline placeholders existed.
- No keyframe images were requested.
- Video, overlay, Raw Status, and Diagnostics DOM nodes remained present.
- Console warning/error list was empty.

Checked final integrated review on `2026-07-18` at:

`http://127.0.0.1:8000/demo/?v=event-final-integrated-review`

Seed input:

```powershell
python .\scripts\seed_event_pipeline_demo.py --incident-id codex-final-integrated-b --camera-id camera_01 --event-type fall_candidate
```

Temporary validation environment kept optional paths default-off unless needed for archive display:

```powershell
EVENT_PIPELINE_ENABLED=true
EVENT_OUTBOX_BACKEND=sqlite
EVENT_OUTBOX_SQLITE_PATH=data/event_outbox.sqlite3
EVENT_ARCHIVE_ENABLED=true
EVENT_ARCHIVE_DIR=logs/event_archive
EVENT_KEYFRAME_SERVING_ENABLED=true
EVENT_DELIVERY_ENABLED=false
EVENT_VLM_ENABLED=false
```

Observed final integrated event:

- `incident_id=codex-final-integrated-b`
- `camera_id=camera_01`
- `track_id=1`
- `event_type=fall_candidate`
- `fall_state=fallen_candidate`
- `risk_level=high`
- `confidence=86%`
- `result_source=事件级复核 / 规则`
- `review_result=规则复核结果`
- `observed_process=standing_to_low_posture`
- `risk_interpretation=need_attention`
- `adl_likelihood=日常活动相似度：低`
- `vlm_status=VLM 复核未启用，当前为规则复核结果`
- `delivery_status=暂无投递状态`
- `delivery_mode=not configured`
- `delivery_backend=memory`
- Timeline Image reported archived-only state because no safe `timeline_image_url` is exposed.
- Six keyframes loaded from relative `/events/codex-final-integrated-b/keyframes/...` URLs.
- `/events/latest?camera_id=camera_01` had no local absolute path leaks.
- All six keyframe image APIs returned `200 image/jpeg`.
- Browser/CDP checks at 1920, 1366, 1024, and 768 widths found no horizontal overflow and no console warn/error entries.
- Video, overlay, Raw Status, and Diagnostics DOM nodes remained present.

Checked final integrated disabled state on `2026-07-18` at:

`http://127.0.0.1:8011/demo/?v=event-final-integrated-review-disabled`

Observed:

- Pipeline badge showed `disabled`.
- Empty state showed `事件语义链路未启用`.
- Six timeline placeholders existed.
- No keyframe images were requested.
- Delivery state showed `暂无投递状态`.
- VLM state showed `VLM 复核未启用`.
- Timeline Image showed `不提供事件过程图`.
- Video, overlay, Raw Status, and Diagnostics DOM nodes remained present.
- Console warning/error list was empty.

## Test Result

Latest verified commands:

```powershell
node --check frontend_demo/app.js
python -m pytest tests/test_event_api.py tests/test_event_keyframe_api.py tests/test_event_archive.py -q
git diff --check
```

Current result on `2026-07-18`:

- `node --check frontend_demo/app.js` passed.
- `python -m py_compile app/api/event_api.py app/events/archive.py` passed.
- `python -m pytest tests/test_event_api.py tests/test_event_keyframe_api.py tests/test_event_archive.py -q` passed with `19 passed`.
- `git diff --check` passed with Windows LF/CRLF warnings only.

## Realtime Chain Impact

No intended impact. The B-line frontend reads event APIs asynchronously and does not modify:

- `FallFusionService`
- `FallEventReporterService`
- `/integration/fall-alerts/poll`
- WebRTC playback
- WebSocket result stream
- REST realtime status endpoints
- Canvas overlay rendering
- Realtime detection services

## Remaining Limits

- Real VLM remains disabled/unconnected.
- DeliveryOutbox remains opt-in and disabled by default.
- Kafka/Redis remain unconnected.
- Celery is not introduced.
- Real camera event validation needs replay or demo seed when no physical fall event occurs.
- The UI does not fabricate production events.
- The formal main-system alert chain still uses `FallEventReporterService`.

## Final E2E Showcase Review 2026-07-18

本轮 Final E2E showcase 只覆盖 B 线前端展示与证据归档验收，不处理 A 线 DeliveryOutbox 状态机，不处理 C 线 VLM provider/prompt，不修改实时检测主链路。

本轮新增验收材料：

- `docs/event_frontend_final_e2e_showcase.md`
- `docs/event_frontend_demo_operator_guide.md`
- `tmp_event_visual_qa/final_e2e_status.json`
- `tmp_event_visual_qa/final_e2e_latest_event.json`
- `tmp_event_visual_qa/final_e2e_console_check.json`
- `tmp_event_visual_qa/final_e2e_seed_1920.png`
- `tmp_event_visual_qa/final_e2e_seed_1366.png`
- `tmp_event_visual_qa/final_e2e_seed_1024.png`
- `tmp_event_visual_qa/final_e2e_seed_768.png`
- `tmp_event_visual_qa/final_e2e_disabled_1366.png`
- `tmp_event_visual_qa/final_e2e_delivery_dry_run.png`
- `tmp_event_visual_qa/final_e2e_vlm_disabled.png`

Final showcase seed input:

```powershell
python .\scripts\seed_event_pipeline_demo.py --incident-id codex-final-e2e-showcase-b --camera-id camera_01 --scenario fall_candidate_support
```

本轮 additionally created one local SQLite dry-run delivery record for the same incident through the existing `DeliveryOutbox` API. The result was `delivery_status=dry_run_sent` and `dry_run=true`; no main-system POST was sent.

Observed final seed event:

- `incident_id=codex-final-e2e-showcase-b`
- `event_type=fall_candidate`
- `fall_state=fallen_candidate`
- `risk_level=high`
- `confidence=86%`
- `delivery_status=模拟投递完成`
- `dry_run=是，模拟投递`
- `vlm_status=VLM 复核未启用，当前为规则复核结果`
- keyframe timeline labels: `T-3s`, `T-1s`, `T0`, `T+1s`, `T+3s`, `T+5s`

A/B/C 展示确认：

- B 线展示 EvidencePackage、EventSemantics、TrustedEventResult 摘要和关键帧时间轴。
- A 线 DeliveryOutbox 字段以只读摘要展示；`dry_run_sent` 不显示成正式投递。
- C 线 VLM/Qwen 字段兼容展示；VLM 关闭时显示规则复核/fallback，不作为实时第一判定。

真实回放事件说明：

- 本轮浏览器验收使用 dev/demo seed 固定输入，未重新跑真实回放。
- 真实回放证据沿用 `docs/event_pipeline_real_acceptance_20260718.md` 和 `tmp_event_visual_qa/event_pipeline_real_acceptance_20260718.png` 中的 2026-07-18 验收记录。

Security conclusion:

- `/events/latest?camera_id=camera_01` returned six relative `/events/codex-final-e2e-showcase-b/keyframes/...` URLs.
- `target_url` is omitted from public delivery summaries.
- No local absolute path, `logs/event_archive`, `payload_json`, `lock_token`, auth header, token, or full endpoint was detected in the final public JSON.

## B-Line Final Freeze Gate 2026-07-18

B 线已通过最终冻结守门，可以冻结为“事件前端演示稳定版”，并进入总项目演示收口。

A/B/C 总验收展示守门状态：

- A 线 Delivery 字段可只读承接：`delivery_status`、`delivery_mode`、`dry_run`、`retry_count`、`next_retry_at`、`delivered_at`、`delivery_backend`、redacted `last_error`。
- Public delivery summary 不返回真实 `target_url`，不返回 `payload_json`、`lock_token` 或内部 endpoint。
- B 线展示层已覆盖 Pipeline、Event Summary、Intelligent Review、Delivery、Keyframe Timeline、Timeline Image，以及 disabled/no event/missing/image fail 状态。
- C 线 VLM/Qwen/Ollama advisory-only 字段可兼容展示：provider、latency、observed process、risk interpretation、ADL likelihood、uncertainty、degradation、review result、recommended action、timeline image summary。
- VLM/Ollama 被冻结为事件级辅助复核展示，不作为实时第一判定，不作为医疗诊断。
- 冻结报告见 `docs/event_frontend_final_freeze_report.md`，演示彩排清单见 `docs/event_frontend_demo_rehearsal_checklist.md`。

Browser freeze check:

- URL: `http://127.0.0.1:8000/demo/?v=event-frontend-freeze-check`
- Disabled URL: `http://127.0.0.1:8011/demo/?v=event-frontend-freeze-check-disabled`
- Seed incident: `codex-frontend-freeze-b`
- 1920 / 1366 / 1024 / 768 passed with 6/6 keyframes loaded, no horizontal overflow, and no console warn/error.
- Disabled state passed with 6 placeholder cards, 0 image requests, and “事件语义链路未启用”.
- Evidence artifacts: `tmp_event_visual_qa/freeze_console_check.json` and `tmp_event_visual_qa/freeze_seed_*.png`.
