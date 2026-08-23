# 主系统 RobotAssistTask 后端 API

实现位置：主系统 `backend/api/robot_assist_api.py`  
API 前缀：`/api/v1/robot-assist`  
状态：代码已实现，尚未在主系统运行实例中启用验收。

| 方法 | 路径 | 权限 | 作用 |
| --- | --- | --- | --- |
| POST | `/alarms/{alarm_id}/tasks` | community/admin | 针对活动跌倒告警创建任务。 |
| GET | `/tasks` | community/admin | 查询任务。 |
| GET | `/tasks/{task_id}` | community/admin | 查询任务快照。 |
| POST | `/tasks/{task_id}/approve` | community/admin | 记录审批并转入 `QUEUED`。 |
| POST | `/tasks/{task_id}/cancel` | community/admin | 取消非终态任务。 |
| POST | `/tasks/{task_id}/events` | community/admin | 接收 Robot Assist Service 的状态事件。 |
| GET | `/tasks/{task_id}/events` | community/admin | 查询 append-only 审计。 |
| GET | `/robots/status` | community/admin | 当前 adapter 状态。 |

创建请求必须给出 `incident_id`、`elder_id`、`target_room`、`observation_point_id`。服务验证：

1. `alarm_id` 必须是活动的跌倒告警；
2. 事件 ID 必须匹配告警元数据；
3. 同一告警只能保留一个活动 `fall_scene_check`；
4. 只有 community/admin 能创建、审批、取消或回传事件；
5. 任务状态改变广播 `type=robot_assist_task` 到既有 alarm WebSocket。

本阶段没有 HTTP 调用 Robot Assist Service；`/robots/status` 明确返回未连接、控制不可用。
