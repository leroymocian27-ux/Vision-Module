# RobotAssistTask Mock 闭环验收

```text
phase: P8
status: PASS
evidence_type: MOCK
environment: temporary in-process SQLite
```

## 实际链路

```text
活动跌倒 AlarmRecord
-> 主系统 RobotAssistTask CREATED/POLICY_CHECKED/AWAITING_APPROVAL
-> community-user-001 审批
-> 主系统 QUEUED
-> MockRobotAdapter DISPATCHING/EXECUTING/ARRIVED/CHECKING/COMPLETED
-> append-only 状态事件回传主系统
-> 主系统任务 COMPLETED
```

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest \
  tests\test_robot_assist_cross_system_mock_e2e.py \
  tests\test_robot_assist_mock_service.py \
  tests\test_integration_contract_v1.py -q
```

结果：`10 passed`。

## 已证明

- 主系统而非 Vision 创建任务。
- 审批前不进入队列。
- 主系统和 Mock 服务均使用幂等与状态机。
- 执行事件包含 `adapter=mock`、`simulated=true`。
- 状态回传可推进主系统到 `COMPLETED`。

## 未证明

- HTTP 服务间认证、网络超时、回调签名、WebSocket 页面刷新。
- 真实 Go2、DDS、移动、固定观察点真实到达。
- 真实 RTSP、真实 confirmed、真实主系统 Delivery。
