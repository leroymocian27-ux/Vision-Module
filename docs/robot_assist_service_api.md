# Robot Assist Service API V1

服务实现：`robot_assist_service/`  
默认监听建议：`127.0.0.1:8200`  
默认 adapter：`mock`

该服务是独立执行平面，不替代主系统的 `AlarmRecord` 或审批真相源。Vision 不调用此 API。

## Endpoints

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | 只返回 mock 服务健康状态。 |
| GET | `/api/v1/robot/status` | adapter 状态、是否模拟、任务状态计数。 |
| POST | `/api/v1/tasks` | 创建或按 `idempotency_key` 返回已有任务。 |
| GET | `/api/v1/tasks/{task_id}` | 获取当前任务快照。 |
| GET | `/api/v1/tasks/{task_id}/events` | 获取 append-only 审计时间线。 |
| POST | `/api/v1/tasks/{task_id}/approve` | 接收主系统已完成权限校验后的审批人。 |
| POST | `/api/v1/tasks/{task_id}/cancel` | 取消非终态任务。 |

## Create example

```json
{
  "task_id": "robot-task-001",
  "idempotency_key": "alarm-001:fall_scene_check:living-room-point-a",
  "task_type": "fall_scene_check",
  "incident_id": "incident-001",
  "alarm_id": "alarm-001",
  "elder_id": "elder-001",
  "target_room": "living_room",
  "observation_point_id": "living-room-point-a",
  "priority": "high",
  "approval_status": "pending",
  "adapter_mode": "mock"
}
```

成功创建后任务进入 `AWAITING_APPROVAL`。相同 `idempotency_key` 不产生第二条任务或第二组审计事件，响应 `idempotent_replay=true`。

## Error codes

| HTTP | code | 含义 |
| --- | --- | --- |
| 404 | `ROBOT_TASK_NOT_FOUND` | 任务不存在。 |
| 409 | `ROBOT_TASK_APPROVAL_REQUIRED` | 未审批不能进入队列。 |
| 409 | `ROBOT_TASK_INVALID_STATE_TRANSITION` | 非法状态迁移或取消终态任务。 |

## 安全边界

- 服务只允许 `adapter_mode=mock`。
- `UnitreeGo2Adapter` 只存在接口骨架；所有真实执行均抛出禁止错误。
- 不提供速度、角度、电机、导航坐标或自由动作 API。
- 所有状态变化写 SQLite append-only 审计事件。
- 重启发现非终态任务时，统一转为 `SAFETY_BLOCKED`，不自动恢复执行。
