# Realtime Demo Gap List - 2026-06-22

本清单只记录明天实时摄像头最小演示相关缺口。未修改生产代码。

## P0 - 必须今晚确认

| 缺口 | 当前证据 | 风险 | 建议处理 |
|---|---|---|---|
| 现场摄像头人体检测未实测 | 当前 `/status` 摄像头 connected，但 `latest_raw_person_count=0` | 明天站到画面中才发现检测角度/距离不合适 | 今晚让单人全身入镜，确认 bbox、track_id、risk panel 更新 |
| 本地 replay 需复测 | 既有 runbook 显示 replay 可 `fallen_confirmed`，但本次未重跑 | 明天临场切 replay 时不熟 | 今晚按 runbook 完整走一遍 |
| dry-run 需开场确认 | 当前 `/alerting/status` 显示 `dry_run=true` | 误触真实 POST 是最高演示风险 | 演示前先展示并口头确认 dry-run |

## P1 - 明天会影响观感

| 缺口 | 当前证据 | 风险 | 建议处理 |
|---|---|---|---|
| 前端不醒目展示降级原因 | 前端显示 fallState/risk/fallProbability，但未显示 `suppressed_reason` / `rejected_reason` | 误报降级只能口头讲或看 raw JSON | 可选补一个只读字段；若不改代码，用 `/integration/results/.../latest` 讲解 |
| 实时确认跌倒稳定性未知 | 当前 live 无人体；稳定确认来自本地 replay | 现场模拟跌倒可能只到候选或不触发 | 主演示用本地 replay，实时摄像头只做加分 |
| 摄像头 read 历史慢读 | `/status` 有 `read_timeout_count=140`、`read_latency_max_ms=176500ms` | 现场可能卡顿或重连 | 开场前重启当前服务或保持已稳定运行；备好本地视频 |

## P2 - 不影响最小演示但容易被问到

| 缺口 | 当前状态 | 建议话术 |
|---|---|---|
| 0-5 VisualRiskMarker 未实时接入 | 离线/审计 PARTIAL，runtime 只有 low/medium/high/critical | “0-5 分级是下一步风险审核层，今天实时页展示的是当前 runtime 风险等级。” |
| pose 当前关闭 | `pose_enabled=false`, `pose_provider=disabled_placeholder` | “当前 demo 是 no-pose 安全基线，避免引入额外模型不稳定。” |
| Temporal 当前关闭 | `/status temporal.enabled=false` | “时序模块存在，但明天最小演示不依赖它；确认主要来自 fall detector 连续候选。” |
| 多人/遮挡/半身入镜未保证 | 明天只要求单人全身无遮挡 | “这些是后续困难负样本和误报降级的专项验证项。” |
| 正式主系统联动不展示 | dry-run true | “本阶段只展示视觉链路与 dry-run 事件，不发送正式告警。” |

## 明天推荐判定

| 能力 | 判定 |
|---|---|
| 摄像头实时输入 | 可用 |
| 实时画面展示 | 可用 |
| 人体框 + track_id | 大概率可用，需现场确认 |
| 实时跌倒确认 | 不建议作为唯一证明 |
| 本地视频跌倒确认 | 可作为主演示 |
| dry-run 安全 | 可用 |
| 误报降级 | 可讲概念和部分字段，不建议强演 |
| 0-5 视觉风险分级 | 只建议离线讲解 |

## 最短今晚检查清单

```text
1. GET http://127.0.0.1:8000/status?camera_id=camera_01
   确认 connected=true, stream_state=connected, frame_age_ms 不大。

2. GET http://127.0.0.1:8000/alerting/status
   确认 dry_run=true。

3. 打开 http://127.0.0.1:8000/demo/
   确认 WebRTC connected, WS connected。

4. 人站到画面中。
   确认 personCount > 0, bbox 出现, target/track id 出现。

5. 本地 replay 跌倒视频。
   确认 fall_state=fallen_confirmed 或至少 fallen_candidate/high。

6. 复查 reporterStatus。
   确认 dry_run_skipped 或 no real POST。
```

