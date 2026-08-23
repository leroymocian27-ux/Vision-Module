# RobotAssistTask SQLite 设计

主系统复用现有 `database_url` 指向的 SQLite 数据库，没有新建第二个业务真相源。

```text
robot_assist_tasks
  task_id PRIMARY KEY
  idempotency_key UNIQUE
  alarm_id INDEX
  state
  task_json
  updated_at

robot_assist_task_events
  sequence AUTOINCREMENT
  event_id UNIQUE
  task_id INDEX
  event_json
```

`task_json` 和 `event_json` 使用合同 `eldercare.robot-assist-task.v1` / `eldercare.robot-task-event.v1`，便于保持 Schema 版本和审计上下文。`event_id` 唯一约束保证重复回调不会产生重复任务状态。

回滚方式：停止主系统路由接入并保留两张表和审计数据；不得通过删除任务记录回滚。
