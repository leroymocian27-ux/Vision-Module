# Event Frontend Final Freeze Report

## B 线冻结结论

B 线可以冻结为“事件前端演示稳定版”，可以进入总项目演示收口。

冻结范围仅包含事件证据归档与 `/demo/` Event Semantic Review 前端展示：public event API summary -> `normalizeEventPayload` -> Event Semantic Review 面板 -> Pipeline / Event / Review / Delivery / Keyframes / Timeline 展示。冻结不包含 A 线 DeliveryOutbox 状态机变更，不包含 C 线 VLM/Ollama provider 变更，也不修改实时检测主链路。

## 冻结能力

| 能力 | 冻结状态 |
| --- | --- |
| Pipeline 状态展示 | 显示 event pipeline enabled/disabled、worker、outbox counts。 |
| 事件摘要展示 | 显示 `incident_id`、camera、track、event type、fall state、risk、confidence、result source。 |
| 智能复核展示 | 显示 `review_result`、`explanation`、`recommended_action`、`uncertainty`、`degradation_used`、observed/risk/ADL 字段。 |
| Delivery 展示 | 只读显示 status、mode、dry-run、retry、next retry、delivered time、backend、redacted last error。 |
| 关键帧时间轴展示 | 固定展示 `T-3s`、`T-1s`、`T0`、`T+1s`、`T+3s`、`T+5s`。 |
| Timeline Image 展示 | 仅在安全相对 URL 存在时展示；否则显示未提供或仅归档状态。 |
| 关闭态 | 显示“事件语义链路未启用”，保留 6 个占位卡，不请求关键帧图片。 |
| 无事件 | 显示“暂无事件归档”。 |
| 缺帧/图片失败 | 显示 `missing_reason` 或“关键帧不可用”。 |
| VLM disabled | 显示规则复核结果，不把 VLM 说成实时第一判定。 |
| Delivery missing | 显示“暂无投递状态”。 |

## A 字段兼容

| 字段 | 冻结状态 |
| --- | --- |
| `delivery_status` | 支持 `pending`、`sending`、`retry`、`failed`、`sent`、`dry_run_sent`。 |
| `delivery_mode` | 支持 `dry_run` / `post` 展示。 |
| `dry_run` | `true` 时显示“是，模拟投递”。 |
| `retry_count` | 缺失时安全显示 `-`，存在时显示次数。 |
| `next_retry_at` | 缺失时安全显示 `-`。 |
| `delivered_at` | 缺失时安全显示 `-`。 |
| `delivery_backend` | 支持 memory/sqlite 等只读展示。 |
| `last_error` | 前端展示 redacted/bounded 文本，不显示完整 URL、本地路径或 token。 |
| `target_url` | public summary 不返回真实 URL；当前冻结实现为 public response 中移除该 key。 |

`dry_run_sent` 冻结为“模拟投递完成”，不显示成正式投递。正式“已投递”仅保留给 `sent + post + dry_run=false`。

## C 字段兼容

| 字段 | 冻结状态 |
| --- | --- |
| `vlm_provider` | 支持 `dummy`、`http`、`qwen_http`、`ollama`、`qwen_ollama`、`ollama_qwen` 等 provider 名称只读展示。 |
| `vlm_latency_ms` | 存在时追加毫秒级延迟文案。 |
| `observed_process` | 存在时展示；缺失时显示 `-`。 |
| `risk_interpretation` | 存在时展示；缺失时显示 `-`。 |
| `adl_likelihood` | 显示为日常活动相似度低/中/高/未知。 |
| `uncertainty` | 显示为短标签/文本列表。 |
| `degradation_used` | 显示为降级标签，覆盖 timeout/invalid_json/skipped/failed 等 fallback。 |
| `review_result` | VLM/Ollama 存在时显示为事件级辅助解释；缺失时显示规则复核。 |
| `recommended_action` | 存在时展示；缺失时显示 `-`。 |
| `alarm_title` / `alarm_body` | 可作为兼容字段进入 event result，但前端不把它们展示为医疗诊断。 |
| timeline image summary | 只接受安全相对 `timeline_image_url`；仅有归档路径时显示 archived-only 状态。 |

Ollama/Qwen 本地语义模型如启用，只按“事件级辅助复核”或“辅助解释”展示，不作为实时第一判定，不作为医疗诊断。

## 安全冻结

- 不暴露本地绝对路径、Windows 路径、`/workspace/...`、`logs/event_archive/...`。
- 不暴露 `lock_token`、`lock_owner`、`lock_until`。
- 不暴露 raw `payload_json`。
- 不暴露真实 `target_url`。
- 不暴露 auth header、authorization、token。
- 不暴露 raw VLM response。
- `keyframe_url` 使用相对 `/events/...` API URL。
- Timeline Image 仅使用相对 `/events/...` URL，其他路径只显示文本状态。
- JSON 不内嵌图片 bytes。

## 浏览器冻结验收

冻结验收页面：

```text
http://127.0.0.1:8000/demo/?v=event-frontend-freeze-check
```

冻结标准：

| 宽度 | 标准 |
| ---: | --- |
| 1920 | 事件面板、视频、overlay、Raw Status、Diagnostics 均存在，无横向溢出。 |
| 1366 | Delivery/VLM 文案换行正常，无横向溢出。 |
| 1024 | 关键帧时间轴可读，主链路节点存在。 |
| 768 | 窄屏布局可读，主链路节点存在。 |

冻结验收要求 console 无 warn/error。EVENT_PIPELINE disabled 时必须显示“事件语义链路未启用”、6 个占位卡、0 图片请求。

本轮冻结验收结果：

- Seed incident: `codex-frontend-freeze-b`
- Enabled URL: `http://127.0.0.1:8000/demo/?v=event-frontend-freeze-check`
- Disabled URL: `http://127.0.0.1:8011/demo/?v=event-frontend-freeze-check-disabled`
- 1920 / 1366 / 1024 / 768: all passed.
- Enabled state: 6 keyframe cards, 6 loaded images, no horizontal overflow, console warn/error count 0.
- Disabled state: “事件语义链路未启用”, 6 placeholder cards, 0 image requests, console warn/error count 0.
- Main nodes: video, overlay, Raw Status, Diagnostics all present.

冻结验收产物：

- `tmp_event_visual_qa/freeze_status.json`
- `tmp_event_visual_qa/freeze_latest_event.json`
- `tmp_event_visual_qa/freeze_console_check.json`
- `tmp_event_visual_qa/freeze_seed_1920.png`
- `tmp_event_visual_qa/freeze_seed_1366.png`
- `tmp_event_visual_qa/freeze_seed_1024.png`
- `tmp_event_visual_qa/freeze_seed_768.png`
- `tmp_event_visual_qa/freeze_disabled_1366.png`
- `tmp_event_visual_qa/freeze_delivery_dry_run.png`
- `tmp_event_visual_qa/freeze_vlm_disabled.png`

## 演示口径

禁止说：

- “大模型直接判断跌倒”
- “dry-run 已正式报警”
- “系统做医疗诊断”
- “demo seed 是生产事件”

推荐说：

- “实时检测链路先发现跌倒候选。”
- “事件链路抽取前后关键帧形成证据包。”
- “规则和大模型/本地语义模型用于辅助复核和解释。”
- “当前 Delivery 是 dry-run 或受控验收模式。”
- “原正式主系统告警链路仍保留。”

## 未启用项

- DeliveryOutbox 默认关闭。
- 真实外部 VLM 默认关闭。
- 本地 Ollama 不强制启用。
- Kafka/Redis/Celery 未接入。
- `FallEventReporterService` 未替换。
- 正式主系统告警链路未替换。
