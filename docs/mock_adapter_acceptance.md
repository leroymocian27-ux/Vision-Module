# MockRobotAdapter 验收

日期：2026-07-19  
证据类型：`MOCK` + 自动化测试

## 已验证

```text
pending task -> AWAITING_APPROVAL
approved task -> QUEUED -> DISPATCHING -> EXECUTING -> ARRIVED -> CHECKING -> COMPLETED
mock failed -> FAILED
mock timeout -> TIMED_OUT
mock offline -> SAFETY_BLOCKED
cancel -> CANCELLED
restart with non-terminal task -> SAFETY_BLOCKED
same idempotency_key -> existing task only
```

Mock 每个执行事件明确包含：

```json
{"adapter": "mock", "simulated": true}
```

## 未验证且禁止宣称

- 任何 Go2 移动、DDS、相机、音频、电量或状态读取。
- 任何真实导航或房间到达。
- 任何真实主系统审批权限、数据库迁移或 WebSocket 广播。

## 验收命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_robot_assist_mock_service.py -q
```
