# Event Frontend Final E2E Showcase

## 验收目标

本轮只验收 B 线事件证据归档与前端展示能力。目标是证明 `/demo/` 中的 Event Semantic Review 面板可以用于比赛演示、调试和工程验收，能够展示事件证据、规则/可选 VLM 复核、Delivery 只读状态、降级原因、关键帧时间轴和 Timeline Image，同时不影响实时检测主链路。

本轮不修改 `FallFusionService`、`FallEventReporterService`、`/integration/fall-alerts/poll`、DeliveryOutbox 状态机、VLM provider/prompt、模型或数据集。

## 场景矩阵

| 场景 | 输入/前置条件 | 前端必须展示 | 验收要点 |
| --- | --- | --- | --- |
| EVENT_PIPELINE 关闭 | `EVENT_PIPELINE_ENABLED=false` | `事件语义链路未启用`、6 个占位 keyframe card、Timeline Image 未提供 | 0 个 keyframe 图片请求；console 无 warn/error；video/overlay/Raw Status/Diagnostics 保持存在 |
| demo seed fall_candidate | 使用 `scripts/seed_event_pipeline_demo.py --scenario fall_candidate_support` | `incident_id`、`camera_id`、`track_id`、`fall_state`、`risk_level`、`confidence`、`explanation`、`recommended_action`、6 个关键帧 | 关键帧从相对 `/events/...` URL 加载；JSON 不暴露绝对路径；不伪造成生产事件 |
| 真实回放 fallen_candidate/fall_candidate | 使用真实回放或既有验收证据 | 真实 `incident_id`、`result_source`、Evidence/Semantics/TrustedResult 摘要、关键帧和降级信息 | 如本轮无可用真实回放，引用 `docs/event_pipeline_real_acceptance_20260718.md`，并标记为“本轮未重新跑真实回放” |
| Delivery dry_run | DeliveryOutbox 有 `dry_run_sent` 记录 | Delivery 显示“模拟投递完成”或等价 dry-run 文案 | 不显示为“已正式投递”；`retry_count`、`next_retry_at` 缺失时不报错 |
| Delivery retry / failed | DeliveryOutbox 有 `retry` 或 `failed` 记录 | retry 显示“等待重试”；failed 显示“投递失败”；`last_error` 为脱敏摘要 | 不暴露 endpoint、token、auth header、`lock_token`、原始 `payload_json` |
| VLM disabled / fallback | `EVENT_VLM_ENABLED=false` 或 VLM timeout/invalid_json | VLM 未启用时显示规则复核；fallback 时显示 `degradation_used` | 不把 VLM 说成实时第一判定；规则结果继续展示 |
| Timeline Image | 事件响应提供安全相对 `timeline_image_url` 或仅有归档路径 | 有相对 URL 时显示图片；无 URL 时显示“未提供/仅归档”状态 | 不请求本地路径；只接受相对 API URL |

## 浏览器检查标准

验收页面：

```text
http://127.0.0.1:8000/demo/?v=event-final-e2e-showcase
```

必须覆盖宽度：

| 宽度 | 标准 |
| ---: | --- |
| 1920 | 投影/桌面视图无横向溢出，事件面板不遮挡实时视频 |
| 1366 | 笔记本视图无横向溢出，Delivery/VLM 长文本在面板内换行 |
| 1024 | 窄桌面/平板宽度下事件面板和关键帧时间轴可读 |
| 768 | 单列窄屏仍显示 video、overlay、Raw Status、Diagnostics 和事件面板 |

所有宽度必须满足：

- console 无 `warning` / `error`。
- `video` 节点存在。
- overlay/canvas 节点存在。
- Raw Status 区域存在。
- Diagnostics 区域存在。
- 关键帧时间轴固定展示 `T-3s`、`T-1s`、`T0`、`T+1s`、`T+3s`、`T+5s`。
- 缺失关键帧显示 `missing_reason`，不留空白、不抛前端异常。

## 安全检查标准

公开 API 与前端展示必须满足：

- 不显示 Windows 绝对路径、`D:\...`、`workspace/...`、`logs/event_archive/...` 等本地路径。
- 不显示 `lock_token`。
- 不显示原始 `payload_json`。
- 不显示 auth header、token 或完整内部 endpoint。
- JSON 不内嵌图片 bytes。
- `keyframe_url` 必须是相对 API URL，例如 `/events/{incident_id}/keyframes/t0`。
- 前端只从相对 `/events/...` URL 请求关键帧和 Timeline Image。

## 当前未启用/非目标

- DeliveryOutbox 默认关闭，只有显式环境变量启用时才参与演示。
- 真实 VLM 默认关闭，fallback/disabled 状态必须可解释。
- Kafka、Redis、Celery 未接入。
- 未替换正式主系统报警链路，`FallEventReporterService` 保持原状。
- 前端不硬编码假事件；demo seed 只作为开发/验收输入源。

## B 线 Freeze 状态

B 线已进入最终冻结守门状态，可以作为事件前端演示稳定版进入总项目演示收口。冻结范围为 public event API summary、`normalizeEventPayload`、Event Semantic Review 面板、安全 keyframe URL、Timeline Image 状态和演示文档。

Public delivery summary 不返回真实 `target_url`；当前实现中 `target_url` 被 public forbidden-key guard 移除，前端不可见。`payload_json`、`lock_token`、raw response、auth header、token、内部 endpoint 和本地路径同样不可见。

## 本轮验收产物

本轮浏览器验收输出统一放在：

```text
tmp_event_visual_qa/
```

建议保留：

- `final_e2e_disabled_1366.png`
- `final_e2e_seed_1366.png`
- `final_e2e_seed_768.png`
- `final_e2e_delivery_dry_run.png`
- `final_e2e_vlm_disabled.png`
- `final_e2e_status.json`
- `final_e2e_latest_event.json`
- `final_e2e_console_check.json`
