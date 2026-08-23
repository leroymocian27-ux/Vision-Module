# 三模块职责边界冻结 V1

## 权威边界

```text
Vision Service: 采集、检测、跟踪、姿态、时序、FallFusion、事件证据。
Qwen/Ollama: 异步、文本、脱敏、JSON advisory。
主系统: AlarmRecord、业务关联、人工审批、RobotAssistTask 真相源。
机器人服务: 任务状态机、策略、审计、Mock/Go2 Adapter。
```

## 强制数据流

```text
Vision 事件和证据 -> 主系统 AlarmRecord -> 人工审批
-> RobotAssistTask -> Robot Assist Service -> Mock 或经批准的 Go2 Adapter
-> 状态事件回到主系统 -> WebSocket/前端时间线
```

## 不允许的数据流

```text
Vision -> Go2 真实控制
Qwen -> Go2 控制参数
DeliveryOutbox -> Go2 控制
Qwen -> FallFusion 判定覆盖
```

## 第一版范围

- 仅 `fall_scene_check`。
- 默认人工审批，家属只读。
- 固定房间观察点，不做动态人体定位、靠近老人、音视频采集或回传。
- `MockRobotAdapter` 为唯一允许的自动执行器；真实 Go2 控制需要独立 Gate。

## 不变约束

- 不改 `FallFusionService` 判定。
- 不替换 `FallEventReporterService`。
- 不修改实际 `.env`。
- Delivery、VLM、Go2 真实能力均默认关闭。
