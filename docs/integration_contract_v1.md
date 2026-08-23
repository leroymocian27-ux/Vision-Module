# 三模块集成合同 V1

版本：`eldercare.integration.v1`  
状态：Phase 02 `PASS`（合同与自动化测试），未授权外部调用。

静态 JSON Schema 位于 `docs/contracts/`，由 `scripts/export_integration_contract_schemas.py` 从
`app/contracts/integration_v1.py` 生成。

## 1. Vision -> 主系统：兼容扩展

旧 `/api/v1/video-bridge/fall-events` 顶层字段不删除、不重命名。新能力只写入：

```json
{
  "metadata": {
    "extension_schema": "eldercare.vision-event-extension.v1",
    "evidence": {
      "evidence_status": "complete",
      "keyframe_count": 6,
      "keyframe_urls": ["/events/{incident_id}/keyframes/t0"],
      "missing_reasons": []
    },
    "semantic_analysis": {
      "support_fall_alarm": true,
      "final_event_type": "fall_confirmed",
      "final_risk_level": "high",
      "explanation": "rule-based result"
    },
    "robot_advisory": {
      "robot_assist_recommended": true,
      "reason": "staff review requested",
      "advisory_only": true
    }
  }
}
```

`keyframe_urls` 仅允许相对 `/events/` API 路径，禁止绝对路径、协议 URL、反斜杠和目录穿越。
主系统仍以 `incident_id` 作为告警幂等键；扩展不授权机器人执行。

## 2. Qwen advisory 合同

输入 Schema：`eldercare.qwen-advisory-input.v1`。允许字段只有跌倒状态、风险、地面时长、姿态、运动状态、证据完整度、规则信号和非敏感区域编号。

明确禁止：`incident_id`、`track_id`、`elder_id`、姓名、电话、地址、图片、视频、音频、文件路径、URL、RTSP 和 Token。

输出 Schema：`eldercare.qwen-advisory.v1`：

```json
{
  "summary": "需要工作人员复核。",
  "possible_false_positive_reasons": [],
  "care_recommendations": ["查看实时画面并联系现场人员"],
  "robot_assist_recommended": false,
  "robot_assist_reason": "",
  "uncertainty_notes": ["本结论为辅助建议"],
  "advisory_confidence": "low"
}
```

该输出只能作为 UI/人工审批参考。规则结果和 `FallFusionService` 始终优先。

## 3. 主系统 -> Robot Assist Service：RobotAssistTask

`task_type` 在 V1 固定为 `fall_scene_check`。必填关联包括 `task_id`、`idempotency_key`、`incident_id`、`alarm_id`、`elder_id`、`target_room`、`observation_point_id`、审批信息和 adapter 模式。

幂等键推荐：

```text
{alarm_id}:fall_scene_check:{observation_point_id}
```

每一个告警在相同观察点默认只能有一个活动任务。主系统是任务真相源；Vision 和 Qwen 无权创建、审批或派遣真实任务。

## 4. 状态机

```text
CREATED -> POLICY_CHECKED -> AWAITING_APPROVAL -> QUEUED
-> DISPATCHING -> EXECUTING -> ARRIVED -> CHECKING -> COMPLETED
```

任何非终态可转入 `FAILED`、`CANCELLED`、`TIMED_OUT` 或 `SAFETY_BLOCKED`。终态不允许重新进入执行态。`QUEUED` 必须已经有 `approval_status=approved`、`approved_by` 和带时区的 `approved_at`。

## 5. Robot Assist Service -> 主系统：任务事件

事件 Schema：`eldercare.robot-task-event.v1`。

```json
{
  "event_id": "task-event-001",
  "task_id": "robot-task-001",
  "event_type": "state_changed",
  "previous_state": "QUEUED",
  "current_state": "DISPATCHING",
  "timestamp": "2026-07-19T12:00:00+00:00",
  "source": "mock_adapter",
  "message": "simulated dispatch started",
  "details": {"adapter": "mock", "simulated": true}
}
```

所有事件为 append-only 审计记录。主系统回调接收方需要以 `event_id` 幂等，不能依赖到达顺序覆盖较高状态。

## 6. API 草案与错误码

Robot 服务 API 草案：

```text
GET  /healthz
GET  /api/v1/robot/status
POST /api/v1/tasks
GET  /api/v1/tasks/{task_id}
GET  /api/v1/tasks/{task_id}/events
POST /api/v1/tasks/{task_id}/approve
POST /api/v1/tasks/{task_id}/cancel
```

稳定错误码：`ROBOT_TASK_NOT_FOUND`、`ROBOT_TASK_INVALID_STATE_TRANSITION`、`ROBOT_TASK_APPROVAL_REQUIRED`、`ROBOT_TASK_IDEMPOTENCY_CONFLICT`、`ROBOT_ADAPTER_OFFLINE`、`ROBOT_TASK_SAFETY_BLOCKED`。

## 7. 兼容性边界

- 旧 Vision fall event 顶层字段不改变。
- DeliveryOutbox 和 `FallEventReporterService` 仍独立；本合同不触发真实 POST。
- `adapter=mock` 与 `simulated=true` 是 Mock 结果的强制标识。
- Go2 adapter 尚未在本合同中获得控制权限。
