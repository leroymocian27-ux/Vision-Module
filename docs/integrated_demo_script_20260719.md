# 三模块稳定演示脚本

状态：`INTEGRATED_DEMO_READY` 的软件轨道准备，证据类型为 `SYNTHETIC + MOCK`。

## 演示边界

- Vision 实时主链路：展示 WebRTC/WS/REST，但事件旁路保持关闭。
- 事件复核：使用隔离 synthetic/replay 实例，明确标记 dry-run。
- Robot：使用 MockRobotAdapter，明确标记 `simulated=true`。
- Qwen：关闭或展示规则 fallback，不称为模型识别。

## 固定流程

1. 展示 Vision 实时链路健康和 `FallFusionService` 权威边界。
2. 展示指定 synthetic/replay 事件的证据、规则解释和降级状态。
3. 展示主系统活动跌倒告警。
4. community 角色选择告警、老人、房间和固定观察点，创建任务。
5. community 角色审批任务。
6. 展示 Mock 时间线：`QUEUED -> DISPATCHING -> EXECUTING -> ARRIVED -> CHECKING -> COMPLETED`。
7. 明确 Mock 不是真实机器狗移动，Qwen 不参与跌倒第一判定，Delivery 未发送真实 POST。

## 故障演示

- Qwen disabled/timeout：规则结果保留。
- 关键帧缺失：显示 degraded 与 missing reason。
- Mock offline：任务进入 `SAFETY_BLOCKED`。
- Mock failure：任务进入 `FAILED`。
- 取消：任务进入 `CANCELLED`，不允许恢复。

## 禁止话术

不得称为真实摄像头 confirmed、真实主系统投递、Qwen 图像分析、真实 Go2 到达或生产可用。
